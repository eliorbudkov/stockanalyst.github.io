'use client';

import { useState } from 'react';
import type { Quote } from '@/lib/types';
import { fmtCompact } from '@/lib/format';
import { Card } from './Card';

const COLLAPSED_CHARS = 360;

export function CompanyDescriptionPanel({ quote }: { quote: Quote }) {
  const [expanded, setExpanded] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);

  const heDesc = quote.description_he?.trim() || null;
  const enDesc = quote.description?.trim() || null;
  const primaryDesc = heDesc ?? enDesc;
  const usingHebrew = !!heDesc && !showOriginal;
  const displayDesc = usingHebrew ? heDesc! : enDesc ?? heDesc ?? '';

  if (!primaryDesc && !quote.website && !quote.sector) return null;

  const isLong = displayDesc.length > COLLAPSED_CHARS;
  const visible =
    !displayDesc
      ? ''
      : !isLong || expanded
      ? displayDesc
      : displayDesc.slice(0, COLLAPSED_CHARS).trimEnd() + '…';

  return (
    <Card title={`אודות ${quote.name ?? quote.symbol}`} hint={quote.industry ?? quote.sector ?? ''}>
      {displayDesc && (
        <>
          <p
            dir={usingHebrew ? 'rtl' : 'ltr'}
            className={`text-sm leading-relaxed text-text ${usingHebrew ? 'text-right' : 'text-left'}`}
            style={{ unicodeBidi: 'isolate' }}
          >
            {visible}
            {isLong && (
              <>
                {' '}
                <button
                  onClick={() => setExpanded((v) => !v)}
                  className="ms-1 text-xs font-semibold text-accent hover:underline"
                >
                  {expanded ? 'הצג פחות' : 'הצג עוד'}
                </button>
              </>
            )}
          </p>
          {heDesc && enDesc && heDesc !== enDesc && (
            <button
              onClick={() => {
                setShowOriginal((v) => !v);
                setExpanded(false);
              }}
              className="mt-2 text-[11px] text-muted hover:text-accent hover:underline"
            >
              {showOriginal ? '🌐 הצג בעברית' : '🌐 הצג את המקור באנגלית'}
            </button>
          )}
        </>
      )}

      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 border-t border-border pt-4 text-xs sm:grid-cols-4">
        {quote.sector && <Meta label="סקטור" value={quote.sector} />}
        {quote.industry && <Meta label="ענף" value={quote.industry} />}
        {quote.country && <Meta label="מדינה" value={quote.country} />}
        {quote.employees && quote.employees > 0 && (
          <Meta label="עובדים" value={fmtCompact(quote.employees)} />
        )}
        {quote.website && (
          <div className="col-span-2 sm:col-span-4">
            <dt className="text-[11px] text-muted">אתר</dt>
            <dd className="ltr">
              <a
                href={quote.website}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-accent hover:underline"
              >
                {quote.website}
              </a>
            </dd>
          </div>
        )}
      </dl>
    </Card>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] text-muted">{label}</dt>
      <dd className="text-sm font-semibold text-text">{value}</dd>
    </div>
  );
}
