# Stock Analyst authentication setup (shared password)

The site is protected by a single shared password.

- One password for the whole site — no accounts, no sign-up, no Supabase.
- The password is enforced on the **server** (Render / FastAPI), not just in the
  browser, so the API cannot be reached without it.
- The password is **never** shipped to the browser in code and is **never** a
  `NEXT_PUBLIC_` variable. The user types it once at `/login`; it is stored only
  in that browser and sent as `Authorization: Bearer <password>` over HTTPS,
  where the backend verifies it with a constant-time compare.
- Automatic logout after inactivity.
- The login page masks the input and only allows same-site redirects.

## How it works

1. A visitor without the login marker is redirected to `/login`.
2. They enter the password. The page calls `GET /api/scan`'s sibling probe
   `GET /api/auth/check` with the password as a Bearer token.
3. On `200` the password is saved in this browser (localStorage) and a
   non-secret marker cookie is set so the app stops redirecting to `/login`.
4. Every API call attaches the password as a Bearer header. Render verifies it
   and returns `401` if it is wrong or missing — at which point the app clears
   the saved password and returns to `/login`.

The marker cookie holds no secret. The real gate is always the backend.

## 1. Render environment variables

Set these in the Render dashboard (**Environment** tab). `APP_PASSWORD` turns the
gate on by its mere presence — you do **not** need `AUTH_REQUIRED`.

```text
APP_PASSWORD=choose-a-long-random-passphrase
ALLOWED_ORIGINS=https://YOUR_PRODUCTION_VERCEL_DOMAIN
GH_DISPATCH_TOKEN=ghp_...   # PAT for the on-demand scan button (Actions: read/write)
```

- For several allowed origins, use comma-separated values
  (e.g. add `http://localhost:3000` while testing locally).
- `GH_DISPATCH_TOKEN` is only needed for the "סרוק עכשיו" button. Without it the
  app still works; the button returns a clear "not configured" message.
- Never put `APP_PASSWORD` in Git, in `render.yaml`, or in any Vercel variable.

## 2. Vercel environment variables

Set these for Production and Preview:

```text
NEXT_PUBLIC_API_URL=https://stockanalyst-github-io.onrender.com
NEXT_PUBLIC_AUTH_IDLE_MINUTES=30
```

Do **not** set `NEXT_PUBLIC_AUTH_ALLOW_UNCONFIGURED_LOCAL` in Vercel, and never
add the password as a `NEXT_PUBLIC_` variable.

## 3. Local development

- Frontend: copy `.env.local.example` to `.env.local`. Keep
  `NEXT_PUBLIC_AUTH_ALLOW_UNCONFIGURED_LOCAL=1` to skip the login gate while the
  local backend has no password.
- To test the real gate locally, set `APP_PASSWORD` in `backend/.env`, add
  `http://localhost:3000` to Render's (or your local) `ALLOWED_ORIGINS`, and
  remove `NEXT_PUBLIC_AUTH_ALLOW_UNCONFIGURED_LOCAL` from `.env.local`.

## 4. Deployment order

1. Add the Render variables (`APP_PASSWORD`, `ALLOWED_ORIGINS`, and
   `GH_DISPATCH_TOKEN` if you want the scan button).
2. Add the Vercel variables.
3. Push the code to GitHub.
4. Wait for both Vercel and Render deployments to finish.
5. Open the site, enter the password at `/login`.

## 5. Verification checklist

1. Opening the production site redirects to `/login`.
2. A wrong password shows "סיסמה שגויה" and does not log in.
3. The correct password loads the dashboard.
4. A direct request to `https://stockanalyst-github-io.onrender.com/api/scan`
   without the password returns `401`.
5. The same endpoint works from the authenticated website.
6. `https://stockanalyst-github-io.onrender.com/` stays `200` for Render health
   checks.
7. `/docs` and `/openapi.json` are unavailable while `APP_PASSWORD` is set.

## Changing or revoking the password

Change `APP_PASSWORD` in the Render dashboard and redeploy. Every browser is
logged out automatically: their saved password no longer matches, so the next
request returns `401` and bounces them back to `/login`.
