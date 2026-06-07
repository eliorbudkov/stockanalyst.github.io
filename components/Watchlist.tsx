'use client';

import { useEffect, useState } from 'react';
import { loadWatchlist, removeFromWatchlist } from '@/lib/watchlist';
import type { WatchlistItem } from '@/lib/types';
import { Card } from './Card';

export function Watchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([]);

  useEffect(() => {
    setItems(loadWatchlist());
  }, []);

  if (items.length === 0) {
    return (
      <Card title="רשימת מעקב" hint="ריקה">
        <p className="text-sm text-muted">
          הוסף מניה לרשימת המעקב מעמוד הניתוח (כפתור "הוסף למעקב") כדי שתופיע כאן.
        </p>
      </Card>
    );
  }

  return (
    <Card title="רשימת מעקב" hint={`${items.length} סימולים`}>
      <ul className="divide-y divide-border">
        {items.map((item) => (
          <li key={item.symbol} className="flex items-center justify-between py-2">
            <a
              href={`/stock/${encodeURIComponent(item.symbol)}`}
              className="ltr text-base font-semibold text-accent hover:underline"
            >
              {item.symbol}
            </a>
            <button
              onClick={() => setItems(removeFromWatchlist(item.symbol))}
              className="text-xs text-muted hover:text-bad"
            >
              הסר
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
