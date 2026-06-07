'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { TrumpHoldings } from '@/lib/types';
import { Card } from './Card';

export function TrumpHoldingsWidget() {
  const [data, setData] = useState<TrumpHoldings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .trumpHoldings()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'שגיאה'));
  }, []);

  return (
    <Card
      title="דיווחי OGE — דונלד ג' טראמפ"
      hint={data ? `${data.source} · ${data.last_filing}` : ''}
    >
      {error && !data && <div className="text-sm text-bad">שגיאה: {error}</div>}
      {!data && !error && (
        <div className="grid h-40 place-items-center text-sm text-muted">טוען...</div>
      )}
      {data && (
        <>
          <div
            className={`mb-3 rounded-md border px-3 py-2 text-xs font-semibold ${
              data.bonus_active
                ? 'border-good/40 bg-good/10 text-good'
                : 'border-warn/40 bg-warn/10 text-warn'
            }`}
          >
            {data.bonus_active
              ? 'בונוס OGE פעיל עבור החזקות מאומתות'
              : data.source_fresh
                ? 'המקור עדכני, אך אין החזקה מאומתת הזכאית לבונוס'
                : `מקור הנתונים ישן מ-12 חודשים — הבונוס מושעה מאז ${data.bonus_suspended_after}`}
          </div>

          <ul className="space-y-2">
            {data.holdings.map((holding) => (
              <li key={holding.symbol}>
                <a
                  href={`/stock/${encodeURIComponent(holding.symbol)}`}
                  className="flex items-center justify-between rounded-lg border border-border bg-panel2/60 p-3 transition hover:border-accent hover:bg-panel2"
                >
                  <div className="flex items-center gap-3">
                    {holding.category === 'primary' && (
                      <span className="rounded-md border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[10px] font-bold text-accent">
                        עיקרית
                      </span>
                    )}
                    {holding.category === 'reported_sale' && (
                      <span className="rounded-md border border-bad/40 bg-bad/10 px-1.5 py-0.5 text-[10px] font-bold text-bad">
                        מכירה מדווחת
                      </span>
                    )}
                    <div>
                      <div className="ltr text-base font-bold text-accent">
                        {holding.symbol}
                      </div>
                      <div className="text-[11px] text-muted">{holding.name}</div>
                    </div>
                  </div>
                  {holding.sector && (
                    <div className="text-[11px] text-muted">{holding.sector}</div>
                  )}
                </a>
              </li>
            ))}
          </ul>

          <div className="mt-4 space-y-1.5 border-t border-border pt-3 text-[11px] leading-relaxed text-muted">
            <p>{data.disclaimer}</p>
            <p>
              מקור:{' '}
              <a
                href={data.source_url}
                target="_blank"
                rel="noreferrer"
                className="ltr text-accent hover:underline"
              >
                {data.source_url}
              </a>
            </p>
          </div>
        </>
      )}
    </Card>
  );
}
