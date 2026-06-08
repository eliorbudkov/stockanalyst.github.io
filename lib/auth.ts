// Client-side shared-password helpers.
//
// Security model: the password is typed by the user at /login and kept ONLY in
// this browser (localStorage). It is sent as `Authorization: Bearer <password>`
// straight to the Render backend over HTTPS, and is verified there with a
// constant-time compare. It is never embedded in client code, never put in a
// NEXT_PUBLIC_ env var, and never placed in a cookie sent to Vercel — so it
// can't leak through the page source or the app host's request logs.
//
// The cookie below holds NO secret: it is a boolean marker ("1") that lets the
// Next.js middleware redirect logged-out visitors to /login. Real enforcement
// always happens on the backend, which rejects any request whose Bearer token
// doesn't match — so faking the marker only reaches a UI that can't load data.

const PW_STORAGE_KEY = 'sa_pw';
export const AUTH_MARKER_COOKIE = 'sa_auth';

export function getStoredPassword(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(PW_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredPassword(password: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(PW_STORAGE_KEY, password);
  } catch {
    /* storage disabled (private mode) — the Bearer just won't persist */
  }
  const secure = window.location.protocol === 'https:' ? '; Secure' : '';
  // 30-day non-secret marker for middleware UX gating only.
  document.cookie = `${AUTH_MARKER_COOKIE}=1; Path=/; Max-Age=2592000; SameSite=Lax${secure}`;
}

export function clearStoredPassword(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(PW_STORAGE_KEY);
  } catch {
    /* ignore */
  }
  document.cookie = `${AUTH_MARKER_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
}
