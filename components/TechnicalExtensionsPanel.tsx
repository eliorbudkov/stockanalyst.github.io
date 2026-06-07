import type { Indicators, Quote } from '@/lib/types';
import { fmtNum, fmtPct } from '@/lib/format';
import { Card } from './Card';
import { StatusDot, type Status } from './StatusDot';

export function TechnicalExtensionsPanel({
  quote,
  indicators,
}: {
  quote: Quote;
  indicators: Indicators;
}) {
  const price = quote.price ?? null;

  return (
    <Card title="אינדיקטורים משלימים" hint="MACD / Bollinger Bands / VWAP">
      <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-3">
        <Row
          label="MACD"
          value={fmtNum(indicators.macd)}
          hint={`Signal ${fmtNum(indicators.macd_signal)} · Hist ${fmtNum(indicators.macd_histogram)}`}
          status={macdStatus(indicators.macd_histogram)}
        />
        <Row
          label="Bollinger Bands"
          value={`${fmtNum(indicators.bb_lower)} - ${fmtNum(indicators.bb_upper)}`}
          hint={bollingerHint(price, indicators)}
          status={bollingerStatus(price, indicators.bb_lower, indicators.bb_upper)}
        />
        <Row
          label="VWAP 20"
          value={fmtNum(indicators.vwap)}
          hint={price && indicators.vwap ? diffHint(price, indicators.vwap) : ''}
          status={vwapStatus(price, indicators.vwap)}
        />
      </dl>
    </Card>
  );
}

function Row({ label, value, hint, status }: { label: string; value: string; hint?: string; status: Status }) {
  return (
    <div>
      <dt className="flex items-center gap-2 text-xs text-muted">
        <StatusDot status={status} />
        <span>{label}</span>
      </dt>
      <dd className="ltr text-lg font-semibold">{value}</dd>
      {hint && <p className="mt-0.5 text-[11px] text-muted">{hint}</p>}
    </div>
  );
}

function macdStatus(histogram: number | null): Status {
  if (histogram === null) return 'neutral';
  return histogram >= 0 ? 'good' : 'bad';
}

function bollingerStatus(price: number | null, lower: number | null, upper: number | null): Status {
  if (!price || lower === null || upper === null) return 'neutral';
  return price >= lower && price <= upper ? 'good' : 'bad';
}

function vwapStatus(price: number | null, vwap: number | null): Status {
  if (!price || vwap === null) return 'neutral';
  return price >= vwap ? 'good' : 'bad';
}

function diffHint(price: number, level: number): string {
  const pct = ((price - level) / level) * 100;
  return `${fmtPct(pct)} מהמחיר`;
}

function bollingerHint(price: number | null, indicators: Indicators): string {
  const width = indicators.bb_width_pct !== null ? `רוחב ${fmtPct(indicators.bb_width_pct)}` : '';
  if (!price || indicators.bb_lower === null || indicators.bb_upper === null) return width;
  if (price > indicators.bb_upper) return `מעל הרצועה העליונה · ${width}`;
  if (price < indicators.bb_lower) return `מתחת לרצועה התחתונה · ${width}`;
  return `בתוך הרצועות · ${width}`;
}
