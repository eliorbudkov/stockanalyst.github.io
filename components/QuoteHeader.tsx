import type { Quote } from '@/lib/types';
import { changeColor, fmtNum, fmtPct } from '@/lib/format';
import { WatchlistButton } from './WatchlistButton';

export function QuoteHeader({ quote }: { quote: Quote }) {
  return (
    <div className="mb-4 flex flex-col gap-3 sm:mb-6 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="ltr text-2xl font-bold sm:text-3xl">{quote.symbol}</h1>
          {quote.name && (
            <span className="truncate text-xs text-muted sm:text-base">— {quote.name}</span>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1 sm:mt-2">
          <span className="ltr text-3xl font-extrabold sm:text-4xl">{fmtNum(quote.price)}</span>
          {quote.currency && <span className="text-xs text-muted sm:text-sm">{quote.currency}</span>}
          <span className={`ltr text-base font-semibold sm:text-lg ${changeColor(quote.change_pct)}`}>
            {fmtPct(quote.change_pct)}
          </span>
        </div>
      </div>
      <WatchlistButton symbol={quote.symbol} />
    </div>
  );
}
