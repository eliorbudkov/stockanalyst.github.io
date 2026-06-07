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

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    cache: 'no-store',
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  quote: (symbol: string) => get<Quote>(`/api/quote?symbol=${encodeURIComponent(symbol)}`),
  analyze: (symbol: string, period = '2y') =>
    get<AnalysisResult>(`/api/analyze?symbol=${encodeURIComponent(symbol)}&period=${period}`),
  fearGreed: (force = false) =>
    get<FearGreed>(`/api/fear-greed${force ? '?force=true' : ''}`),
  heatmap: (force = false) =>
    get<Heatmap>(`/api/heatmap${force ? '?force=true' : ''}`),
  scan: (force = false) =>
    get<ScanResult>(`/api/scan${force ? '?force=true' : ''}`),
  globalLiquidity: (force = false) =>
    get<GlobalLiquidity>(`/api/global-liquidity${force ? '?force=true' : ''}`),
  trumpHoldings: () => get<TrumpHoldings>(`/api/holdings/trump`),
};
