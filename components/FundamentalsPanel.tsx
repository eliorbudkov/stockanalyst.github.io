import type { Quote } from '@/lib/types';
import { fmtCompact, fmtNum, fmtPct } from '@/lib/format';
import { Card } from './Card';
import { StatusDot, type Status } from './StatusDot';

export function FundamentalsPanel({ quote }: { quote: Quote }) {
  return (
    <Card title="פונדמנטלס" hint={quote.sector ?? ''}>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
        <Row label="שווי שוק" value={fmtCompact(quote.market_cap)} status="neutral" />
        <Row label="מכפיל רווח (P/E)" value={fmtNum(quote.pe)} status={peStatus(quote.pe)} />
        <Row label="מכפיל הון (P/B)" value={fmtNum(quote.pb)} status={pbStatus(quote.pb)} />
        <Row
          label="תשואת דיבידנד"
          value={quote.dividend_yield !== null ? fmtPct((quote.dividend_yield ?? 0) * 100) : '—'}
          status={dividendStatus(quote.dividend_yield)}
        />
        <Row label="ביטא" value={fmtNum(quote.beta)} status={betaStatus(quote.beta)} />
        <Row label="ענף" value={quote.industry ?? '—'} status="neutral" />
      </dl>
    </Card>
  );
}

function Row({ label, value, status }: { label: string; value: string; status: Status }) {
  return (
    <div>
      <dt className="flex items-center gap-2 text-xs text-muted">
        <StatusDot status={status} />
        <span>{label}</span>
      </dt>
      <dd className="text-base font-semibold">{value}</dd>
    </div>
  );
}

function peStatus(pe: number | null): Status {
  if (pe === null) return 'neutral';
  if (pe <= 0) return 'bad';
  if (pe <= 25) return 'good';
  if (pe > 40) return 'bad';
  return 'neutral';
}

function pbStatus(pb: number | null): Status {
  if (pb === null) return 'neutral';
  if (pb <= 3) return 'good';
  if (pb > 6) return 'bad';
  return 'neutral';
}

function dividendStatus(dy: number | null): Status {
  if (dy === null || dy === 0) return 'neutral';
  return dy >= 0.02 ? 'good' : 'neutral';
}

function betaStatus(beta: number | null): Status {
  if (beta === null) return 'neutral';
  const b = Math.abs(beta);
  if (b >= 0.7 && b <= 1.3) return 'good';
  if (b > 1.7) return 'bad';
  return 'neutral';
}
