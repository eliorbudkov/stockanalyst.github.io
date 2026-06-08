"""Supabase JWT verification for protected API routes."""
from __future__ import annotations

import hmac
import os
from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient


def auth_required() -> bool:
    return os.getenv("AUTH_REQUIRED", "0").strip().lower() in {"1", "true", "yes", "on"}


def app_password() -> str:
    """The single shared site password, set server-side only (never NEXT_PUBLIC_)."""
    return os.getenv("APP_PASSWORD", "").strip()


def auth_enabled() -> bool:
    """True when any auth mode is active — shared password or Supabase JWT."""
    return bool(app_password()) or auth_required()


def _supabase_url() -> str:
    return os.getenv("SUPABASE_URL", "").rstrip("/")


def _allowed_emails() -> set[str]:
    return {
        email.strip().lower()
        for email in os.getenv("ALLOWED_USER_EMAILS", "").split(",")
        if email.strip()
    }


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    url = _supabase_url()
    if not url:
        raise RuntimeError("SUPABASE_URL is required when AUTH_REQUIRED=1")
    return PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", cache_keys=True)


def _decode_token(token: str) -> dict[str, Any]:
    url = _supabase_url()
    if not url:
        raise RuntimeError("SUPABASE_URL is required when AUTH_REQUIRED=1")

    jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    if jwt_secret:
        return jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
            issuer=f"{url}/auth/v1",
        )

    signing_key = _jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256", "RS256"],
        audience="authenticated",
        issuer=f"{url}/auth/v1",
    )


def authenticate_request(request: Request) -> dict[str, Any] | None:
    password = app_password()
    if password:
        # Single shared-password mode. The secret lives only in the server
        # environment (APP_PASSWORD) and the user's browser; it is verified here
        # with a constant-time compare, so it never ships in client code.
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not hmac.compare_digest(token, password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {"mode": "password"}

    if not auth_required():
        return None

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = _decode_token(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if claims.get("aal") != "aal2":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Multi-factor authentication is required",
        )

    allowed = _allowed_emails()
    email = str(claims.get("email") or "").lower()
    if allowed and email not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not authorized for this application",
        )

    return claims
