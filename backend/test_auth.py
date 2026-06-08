from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from starlette.requests import Request

from auth import authenticate_request


JWT_SECRET = "test-secret-that-is-long-enough-for-hs256"
SUPABASE_URL = "https://example.supabase.co"


def _request(token: str | None = None) -> Request:
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/scan",
            "headers": headers,
        },
    )


def _token(*, aal: str = "aal2", email: str = "owner@example.com") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "email": email,
            "role": "authenticated",
            "aud": "authenticated",
            "iss": f"{SUPABASE_URL}/auth/v1",
            "aal": aal,
            "iat": now,
            "exp": now + 300,
        },
        JWT_SECRET,
        algorithm="HS256",
    )


class SupabaseAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "AUTH_REQUIRED": "1",
                "APP_PASSWORD": "",  # keep the Supabase path active for these tests
                "SUPABASE_URL": SUPABASE_URL,
                "SUPABASE_JWT_SECRET": JWT_SECRET,
                "ALLOWED_USER_EMAILS": "owner@example.com",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_missing_token_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            authenticate_request(_request())
        self.assertEqual(raised.exception.status_code, 401)

    def test_invalid_token_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            authenticate_request(_request("not-a-jwt"))
        self.assertEqual(raised.exception.status_code, 401)

    def test_aal1_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            authenticate_request(_request(_token(aal="aal1")))
        self.assertEqual(raised.exception.status_code, 403)

    def test_unlisted_email_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            authenticate_request(_request(_token(email="other@example.com")))
        self.assertEqual(raised.exception.status_code, 403)

    def test_aal2_allowed_user_is_accepted(self) -> None:
        claims = authenticate_request(_request(_token()))
        self.assertIsNotNone(claims)
        self.assertEqual(claims["email"], "owner@example.com")


class PasswordAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        # Password mode activates purely from APP_PASSWORD; AUTH_REQUIRED stays
        # off here to prove the password gate doesn't depend on it.
        self.env = patch.dict(
            os.environ,
            {"APP_PASSWORD": "s3cret-pass", "AUTH_REQUIRED": "0"},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_missing_password_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            authenticate_request(_request())
        self.assertEqual(raised.exception.status_code, 401)

    def test_wrong_password_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            authenticate_request(_request("wrong-pass"))
        self.assertEqual(raised.exception.status_code, 401)

    def test_correct_password_is_accepted(self) -> None:
        claims = authenticate_request(_request("s3cret-pass"))
        self.assertEqual(claims, {"mode": "password"})


if __name__ == "__main__":
    unittest.main()
