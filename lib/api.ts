import type {
  AnalysisResult,
  FearGreed,
  GlobalLiquidity,
  Heatmap,
  Quote,
  ScanResult,
  TrumpHoldings,
} from './types';
import { clearStoredPassword, getStoredPassword } from './auth';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

// Render's free tier sleeps after ~15 min idle; the first request then waits
// ~50s for the dyno to boot. Without an abort the UI hangs forever on a stuck
// request; without a retry a cold-start wake looks like a hard failure.
type GetOptions = { timeoutMs?: number; retries?: number };
const DEFAULT_TIMEOUT_MS = 60_000;

async function resolveAccessToken(explicitToken?: string): Promise<string | undefined> {
  if (explicitToken !== undefined) return explicitToken;
  // Unconfigured local dev: the backend has no auth, so send no Bearer.
  if (
    process.env.NODE_ENV === 'development' &&
    process.env.NEXT_PUBLIC_AUTH_ALLOW_UNCONFIGURED_LOCAL === '1'
  ) {
    return undefined;
  }
  // The shared password lives only in this browser (localStorage). Every
  // authenticated call in this app runs client-side; a server context has no
  // access to the secret by design, so it simply sends no token.
  return getStoredPassword() ?? undefined;
}

// A 401 means the stored password is missing or no longer valid. Drop it and
// bounce to /login so the user can re-enter it. No-op on the server / on /login.
function handleUnauthorized(): void {
  if (typeof window === 'undefined') return;
  clearStoredPassword();
  if (window.location.pathname !== '/login') {
    const here = `${window.location.pathname}${window.location.search}`;
    window.location.assign(`/login?next=${encodeURIComponent(here)}`);
  }
}

async function get<T>(
  path: string,
  opts: GetOptions = {},
  explicitToken?: string,
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, retries = 1 } = opts;
  const accessToken = await resolveAccessToken(explicitToken);
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${API_URL}${path}`, {
        headers: {
          'Content-Type': 'application/json',
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        cache: 'no-store',
        signal: ctrl.signal,
      });
      if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(`API ${res.status}: ${body || res.statusText}`);
      }
      return (await res.json()) as T;
    } catch (e) {
      lastErr = e;
      // 401 ⇒ the shared password is missing/stale: clear it and bounce to login.
      if (e instanceof Error && /^API 401\b/.test(e.message)) {
        handleUnauthorized();
        throw e;
      }
      // Deterministic HTTP errors (4xx/5xx) won't change on retry — surface now.
      if (e instanceof Error && /^API \d/.test(e.message)) throw e;
      // Otherwise: timeout/network error, likely a cold-start wake → retry once.
    } finally {
      clearTimeout(timer);
    }
  }
  void lastErr;
  throw new Error('השרת מתעורר (יקיצה ראשונה עד דקה) או שיש בעיית רשת — נסה שוב בעוד רגע');
}

async function post<T>(
  path: string,
  body?: unknown,
  opts: GetOptions = {},
  explicitToken?: string,
): Promise<T> {
  // No auto-retry by default: a workflow dispatch is NOT idempotent — a retried
  // POST whose first response was merely lost would start a second scan run.
  const { timeoutMs = DEFAULT_TIMEOUT_MS, retries = 0 } = opts;
  const accessToken = await resolveAccessToken(explicitToken);
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${API_URL}${path}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
        signal: ctrl.signal,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(`API ${res.status}: ${text || res.statusText}`);
      }
      return (await res.json()) as T;
    } catch (e) {
      lastErr = e;
      if (e instanceof Error && /^API 401\b/.test(e.message)) {
        handleUnauthorized();
        throw e;
      }
      if (e instanceof Error && /^API \d/.test(e.message)) throw e;
    } finally {
      clearTimeout(timer);
    }
  }
  void lastErr;
  throw new Error('השרת מתעורר (יקיצה ראשונה עד דקה) או שיש בעיית רשת — נסה שוב בעוד רגע');
}

// Validates the shared password against the backend without doing data work.
// Returns true on 200 and false on 401; throws on network/other errors so the
// login page can tell "wrong password" apart from "server still waking up".
export async function authCheck(password: string): Promise<boolean> {
  // Login is usually the first contact, so it tends to hit a cold Render dyno.
  // A 401 is definitive (wrong password) and returns immediately; a timeout or
  // 5xx is retried once to ride out the ~50s cold-start wake.
  let lastErr: unknown;
  for (let attempt = 0; attempt < 2; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), DEFAULT_TIMEOUT_MS);
    try {
      const res = await fetch(`${API_URL}/api/auth/check`, {
        headers: { Authorization: `Bearer ${password}` },
        cache: 'no-store',
        signal: ctrl.signal,
      });
      if (res.ok) return true;
      if (res.status === 401) return false;
      throw new Error(`API ${res.status}`);
    } catch (e) {
      lastErr = e;
    } finally {
      clearTimeout(timer);
    }
  }
  void lastErr;
  throw new Error('auth-check-unreachable');
}

// Result of POST /api/scan/trigger — see DailyScanner for the polling flow.
export type ScanTriggerResult = {
  status: 'triggered' | 'already_running';
  baseline_fetched_at?: number | null;
  retry_after_seconds?: number;
  eta_seconds?: number;
};

export const api = {
  quote: (symbol: string, accessToken?: string) =>
    get<Quote>(`/api/quote?symbol=${encodeURIComponent(symbol)}`, {}, accessToken),
  analyze: (symbol: string, period = '2y', accessToken?: string) =>
    get<AnalysisResult>(
      `/api/analyze?symbol=${encodeURIComponent(symbol)}&period=${period}`,
      {},
      accessToken,
    ),
  fearGreed: (force = false) =>
    get<FearGreed>(`/api/fear-greed${force ? '?force=true' : ''}`),
  heatmap: (force = false) =>
    get<Heatmap>(`/api/heatmap${force ? '?force=true' : ''}`),
  scan: (force = false) =>
    get<ScanResult>(`/api/scan${force ? '?force=true' : ''}`, {
      // A manual rescan recomputes the full ~516-symbol universe — allow up to
      // 3 min. Cached/seed reads return immediately, so 60s covers a cold boot.
      timeoutMs: force ? 180_000 : 60_000,
    }),
  // Ask GitHub Actions to run a fresh scan (the 512MB dyno can't — it OOMs).
  // Returns immediately after dispatch; the caller polls api.scan() for the new
  // data once the workflow finishes and Render redeploys the seed (~5-10 min).
  triggerScan: () =>
    post<ScanTriggerResult>('/api/scan/trigger', undefined, { timeoutMs: 60_000 }),
  globalLiquidity: (force = false) =>
    get<GlobalLiquidity>(`/api/global-liquidity${force ? '?force=true' : ''}`),
  trumpHoldings: () => get<TrumpHoldings>(`/api/holdings/trump`),
};
