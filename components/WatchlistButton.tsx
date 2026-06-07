'use client';

import { useEffect, useState } from 'react';
import { addToWatchlist, loadWatchlist, removeFromWatchlist } from '@/lib/watchlist';

export function WatchlistButton({ symbol }: { symbol: string }) {
  const [inList, setInList] = useState(false);

  useEffect(() => {
    setInList(!!loadWatchlist().find((i) => i.symbol === symbol));
  }, [symbol]);

  function toggle() {
    if (inList) {
      removeFromWatchlist(symbol);
      setInList(false);
    } else {
      addToWatchlist(symbol);
      setInList(true);
    }
  }

  return (
    <button
      onClick={toggle}
      className={
        inList
          ? 'rounded-xl border border-bad/40 bg-bad/10 px-4 py-2 text-sm text-bad hover:bg-bad/20'
          : 'rounded-xl border border-accent/40 bg-accent/10 px-4 py-2 text-sm text-accent hover:bg-accent/20'
      }
    >
      {inList ? 'הסר ממעקב' : 'הוסף למעקב'}
    </button>
  );
}
