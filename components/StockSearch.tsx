'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

const SUGGESTIONS = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'SPY', 'QQQ'];

export function StockSearch() {
  const router = useRouter();
  const [value, setValue] = useState('');

  function go(symbol: string) {
    const sym = symbol.trim().toUpperCase();
    if (!sym) return;
    router.push(`/stock/${encodeURIComponent(sym)}`);
  }

  return (
    <div className="rounded-xl border border-border bg-panel/70 p-4 shadow-card sm:rounded-2xl sm:p-6">
      <h1 className="mb-1 text-xl font-bold sm:text-2xl">סורק וניתוח מניות</h1>
      <p className="mb-4 text-xs text-muted sm:mb-5 sm:text-sm">
        הזן סימול בבורסה האמריקאית (לדוגמה: AAPL, NVDA, SPY) לקבלת ניתוח טכני, פונדמנטלי וציון כניסה 1-10.
      </p>
      <form
        className="flex flex-col gap-3 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          go(value);
        }}
      >
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="הקלד סימול… לדוגמה AAPL"
          className="ltr flex-1 rounded-xl border border-border bg-panel2 px-4 py-3 text-base outline-none focus:border-accent sm:text-lg"
          dir="ltr"
          autoFocus
          autoComplete="off"
          inputMode="text"
          autoCapitalize="characters"
        />
        <button
          type="submit"
          className="rounded-xl bg-accent px-6 py-3 font-semibold text-bg transition hover:brightness-110 sm:w-auto"
        >
          נתח
        </button>
      </form>
      <div className="mt-4 flex flex-wrap gap-2">
        <span className="text-xs text-muted">פופולריים:</span>
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => go(s)}
            className="ltr rounded-full border border-border bg-panel2 px-3 py-1 text-xs hover:border-accent hover:text-accent"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
