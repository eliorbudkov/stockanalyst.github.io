import type { Indicators, Quote } from '@/lib/types';
import { fmtNum, fmtPct } from '@/lib/format';
import { Card } from './Card';
import { StatusDot, type Status } from './StatusDot';

export function IndicatorPanel({ quote, indicators }: { quote: Quote; indicators: Indicators }) {
  const price = quote.price ?? 0;
  const rsi = indicators.rsi14;
  const rsiLabel =
    rsi === null
      ? '—'
      : rsi >= 70
      ? 'קנייתיתר (Overbought)'
      : rsi <= 30
      ? 'מכירת יתר (Oversold)'
      : 'אזור ניטרלי';

  return (
    <Card title="אינדיקטורים טכניים" hint="MA / RSI / ATR">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
        <Row label="MA 20" value={fmtNum(indicators.ma20)} hint={diffHint(price, indicators.ma20)} status={maStatus(price, indicators.ma20)} />
        <Row label="MA 50" value={fmtNum(indicators.ma50)} hint={diffHint(price, indicators.ma50)} status={maStatus(price, indicators.ma50)} />
        <Row label="MA 150" value={fmtNum(indicators.ma150)} hint={diffHint(price, indicators.ma150)} status={maStatus(price, indicators.ma150)} />
        <Row label="MA 200" value={fmtNum(indicators.ma200)} hint={diffHint(price, indicators.ma200)} status={maStatus(price, indicators.ma200)} />
        <Row label="RSI (14)" value={fmtNum(indicators.rsi14)} hint={rsiLabel} status={rsiStatus(indicators.rsi14)} />
        <Row
          label="ATR (14)"
          value={fmtNum(indicators.atr14)}
          hint={indicators.atr_pct !== null ? `${fmtPct(indicators.atr_pct)} מהמחיר` : ''}
          status={atrStatus(indicators.atr_pct)}
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

function diffHint(price: number, ma: number | null): string {
  if (ma === null || price === 0) return '';
  const pct = ((price - ma) / ma) * 100;
  return `${fmtPct(pct)} מהמחיר`;
}

function maStatus(price: number, ma: number | null): Status {
  if (ma === null || price === 0) return 'neutral';
  return price >= ma ? 'good' : 'bad';
}

function rsiStatus(rsi: number | null): Status {
  if (rsi === null) return 'neutral';
  if (rsi >= 70 || rsi <= 30) return 'bad';
  return 'good';
}

function atrStatus(atrPct: number | null): Status {
  if (atrPct === null) return 'neutral';
  return atrPct <= 4 ? 'good' : 'bad';
}
