import type { PatternSignal, Patterns } from '@/lib/types';
import { fmtNum } from '@/lib/format';
import { Card } from './Card';
import { StatusDot, type Status } from './StatusDot';

const ORDER: Array<keyof Patterns> = [
  'cup_and_handle',
  'head_and_shoulders',
  'double_top',
  'double_bottom',
  'flag',
  'triangle',
];

export function PatternsPanel({ patterns }: { patterns: Patterns }) {
  const detected = ORDER.map((key) => patterns[key]).filter((pattern) => pattern.detected);
  const signals = detected.length > 0 ? detected : ORDER.map((key) => patterns[key]);

  return (
    <Card title="איתור תבניות" hint="Cup & Handle / Head & Shoulders / Double Top-Bottom / Flags / Triangles">
      <div className="grid gap-3 lg:grid-cols-2">
        {signals.map((pattern) => (
          <PatternCard key={pattern.name} pattern={pattern} />
        ))}
      </div>
    </Card>
  );
}

function PatternCard({ pattern }: { pattern: PatternSignal }) {
  const status = patternStatus(pattern);
  return (
    <div className="rounded-lg border border-border bg-panel2 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <StatusDot status={status} />
            <h3 className="text-sm font-semibold">{pattern.name}</h3>
          </div>
          <p className="mt-1 text-xs text-muted">{directionLabel(pattern)}</p>
        </div>
        <div className="ltr rounded bg-panel px-2 py-1 text-xs font-semibold">
          {pattern.confidence}%
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-3 gap-3 text-xs">
        <Metric label="רמת אישור" value={fmtNum(pattern.level)} />
        <Metric label="יעד" value={fmtNum(pattern.target)} />
        <Metric label="סטופ" value={fmtNum(pattern.stop)} />
      </dl>

      <p className="mt-3 text-xs leading-5 text-muted">{pattern.explanation}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] text-muted">{label}</dt>
      <dd className="ltr font-semibold">{value}</dd>
    </div>
  );
}

function patternStatus(pattern: PatternSignal): Status {
  if (!pattern.detected) return 'neutral';
  return pattern.direction === 'bullish' ? 'good' : pattern.direction === 'bearish' ? 'bad' : 'neutral';
}

function directionLabel(pattern: PatternSignal): string {
  if (!pattern.detected) return 'לא זוהתה תבנית פעילה';
  if (pattern.direction === 'bullish') return 'תבנית שורית';
  if (pattern.direction === 'bearish') return 'תבנית דובית';
  return 'תבנית ניטרלית עד לפריצה';
}
