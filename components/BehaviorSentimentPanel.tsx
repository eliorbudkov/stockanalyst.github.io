import type { BehaviorSentiment } from '@/lib/types';
import { fmtCompact, fmtNum, fmtPct } from '@/lib/format';
import { Card } from './Card';
import { StatusDot, type Status } from './StatusDot';

export function BehaviorSentimentPanel({ data }: { data: BehaviorSentiment | null }) {
  if (!data) {
    return (
      <Card title="סנטימנט והתנהגות שוק" hint="PCR / VIX / Social / Insider / Short Interest">
        <p className="text-sm text-muted">הנתונים לא זמינים כרגע.</p>
      </Card>
    );
  }

  return (
    <Card
      title="סנטימנט והתנהגות שוק"
      hint={`Composite ${data.composite_score === null ? '—' : data.composite_score.toFixed(1)} / 10 · ${data.label}`}
    >
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <Metric
          title="Put/Call Ratio"
          value={fmtNum(data.put_call_ratio.value ?? null, 2)}
          score={data.put_call_ratio.score}
          hint={data.put_call_ratio.rating ?? data.put_call_ratio.status}
        />
        <Metric
          title="VIX"
          value={fmtNum(data.vix.value ?? null, 2)}
          score={data.vix.score}
          hint={data.vix.rating ?? data.vix.status}
        />
        <Metric
          title="Social"
          value={scoreValue(data.social_sentiment.score)}
          score={data.social_sentiment.score}
          hint={socialHint(data)}
        />
        <Metric
          title="Insider"
          value={scoreValue(data.insider_trading.score)}
          score={data.insider_trading.score}
          hint={insiderHint(data)}
        />
        <Metric
          title="Short Interest"
          value={shortValue(data)}
          score={data.short_interest.score}
          hint={shortHint(data)}
        />
      </div>

      <div className="mt-4 grid gap-3 text-xs text-muted lg:grid-cols-3">
        <SourceList title="Social Sources" rows={data.social_sentiment.providers.map((p) => `${p.source}: ${statusLabel(p.status)}${p.mentions ? ` · ${p.mentions} mentions` : ''}`)} />
        <SourceList
          title="Insider Trading"
          rows={[
            `סטטוס: ${statusLabel(data.insider_trading.status)}`,
            `עסקאות 90 יום: ${data.insider_trading.transactions_90d ?? '—'}`,
            `אחזקת insiders: ${data.insider_trading.held_percent_insiders === null ? '—' : fmtPct(data.insider_trading.held_percent_insiders, 2)}`,
          ]}
        />
        <SourceList
          title="Short Interest"
          rows={[
            `Short float: ${data.short_interest.short_percent_float === null ? '—' : fmtPct(data.short_interest.short_percent_float, 2)}`,
            `Short ratio: ${fmtNum(data.short_interest.short_ratio, 2)}`,
            `Shares short: ${fmtCompact(data.short_interest.shares_short)}`,
          ]}
        />
      </div>

      {data.notes.length > 0 && (
        <p className="mt-4 border-t border-border pt-3 text-xs text-muted">
          חסרים: {data.notes.join(' · ')}
        </p>
      )}
    </Card>
  );
}

function Metric({
  title,
  value,
  score,
  hint,
}: {
  title: string;
  value: string;
  score: number | null;
  hint: string;
}) {
  const status = scoreStatus(score);
  return (
    <div className="rounded-lg border border-border bg-panel2 p-4">
      <div className="flex items-center gap-2 text-xs text-muted">
        <StatusDot status={status} />
        <span>{title}</span>
      </div>
      <div className="ltr mt-2 text-xl font-semibold">{value}</div>
      <div className="mt-1 text-[11px] text-muted">{hint}</div>
      <div className="ltr mt-2 text-xs font-semibold">{score === null ? '—' : `${score.toFixed(1)} / 10`}</div>
    </div>
  );
}

function SourceList({ title, rows }: { title: string; rows: string[] }) {
  return (
    <div className="rounded-lg bg-panel2 p-3">
      <div className="mb-2 font-semibold text-text">{title}</div>
      <ul className="space-y-1">
        {rows.map((row) => (
          <li key={row}>{row}</li>
        ))}
      </ul>
    </div>
  );
}

function scoreStatus(score: number | null): Status {
  if (score === null) return 'neutral';
  if (score >= 6.5) return 'good';
  if (score <= 4.5) return 'bad';
  return 'neutral';
}

function scoreValue(score: number | null): string {
  return score === null ? '—' : score.toFixed(1);
}

function socialHint(data: BehaviorSentiment): string {
  const ok = data.social_sentiment.available_sources.join(', ') || 'אין מקורות זמינים';
  return `${data.social_sentiment.label} · ${ok}`;
}

function insiderHint(data: BehaviorSentiment): string {
  const net = data.insider_trading.net_shares_90d;
  if (net === null) return data.insider_trading.label;
  return `${data.insider_trading.label} · נטו ${fmtCompact(net)} מניות`;
}

function shortValue(data: BehaviorSentiment): string {
  const pct = data.short_interest.short_percent_float;
  return pct === null ? '—' : `${pct.toFixed(2)}%`;
}

function shortHint(data: BehaviorSentiment): string {
  return data.short_interest.notes.length > 0 ? data.short_interest.notes.join(' · ') : data.short_interest.label;
}

function statusLabel(status: string): string {
  if (status === 'ok') return 'מחובר';
  if (status === 'partial') return 'חלקי';
  if (status === 'not_configured') return 'דורש API';
  return 'לא זמין';
}
