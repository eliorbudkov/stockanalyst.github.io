import type { WatchlistItem } from './types';

const KEY = 'stock-analyst:watchlist:v1';

export function loadWatchlist(): WatchlistItem[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as WatchlistItem[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveWatchlist(items: WatchlistItem[]): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(KEY, JSON.stringify(items));
}

export function addToWatchlist(symbol: string): WatchlistItem[] {
  const sym = symbol.trim().toUpperCase();
  if (!sym) return loadWatchlist();
  const items = loadWatchlist();
  if (items.find((i) => i.symbol === sym)) return items;
  const next = [...items, { symbol: sym, added_at: Date.now() }];
  saveWatchlist(next);
  return next;
}

export function removeFromWatchlist(symbol: string): WatchlistItem[] {
  const items = loadWatchlist().filter((i) => i.symbol !== symbol);
  saveWatchlist(items);
  return items;
}
