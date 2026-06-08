import type {
  AnalysisResult,
  FearGreed,
  GlobalLiquidity,
  Heatmap,
  Quote,
  ScanResult,
  TrumpHoldings,
} from './types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

// Render's free tier sleeps after ~15 min idle; the first request then waits
// ~50s for the dyno to boot. Without an abort the UI hangs forever on a stuck
// request; without a retry a cold-start wake looks like a hard failure.
type GetOptions = { timeoutMs?: number; retries?: number };
const DEFAULT_TIMEOUT_MS = 60_000;

async function get<T>(path: string, opts: GetOptions = {}): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, retries = 1 } = opts;
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${API_URL}${path}`, {
        headers: { 'Content-Type': 'application/json' },
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

async function post<T>(path: string, body?: unknown, opts: GetOptions = {}): Promise<T> {
  // No auto-retry by default: a workflow dispatch is NOT idempotent — a retried
  // POST whose first response was merely lost would start a second scan run.
  const { timeoutMs = DEFAULT_TIMEOUT_MS, retries = 0 } = opts;
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${API_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
      if (e instanceof Error && /^API \d/.test(e.message)) throw e;
    } finally {
      clearTimeout(timer);
    }
  }
  void lastErr;
  throw new Error('השרת מתעורר (יקיצה ראשונה עד דקה) או שיש בעיית רשת — נסה שוב בעוד רגע');
}

// Result of POST /api/scan/trigger — see DailyScanner for the polling flow.
export type ScanTriggerResult = {
  status: 'triggered' | 'already_running';
  baseline_fetched_at?: number | null;
  retry_after_seconds?: number;
  eta_seconds?: number;
};

export const api = {
  quote: (symbol: string) => get<Quote>(`/api/quote?symbol=${encodeURIComponent(symbol)}`),
  analyze: (symbol: string, period = '2y') =>
    get<AnalysisResult>(`/api/analyze?symbol=${encodeURIComponent(symbol)}&period=${period}`),
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
