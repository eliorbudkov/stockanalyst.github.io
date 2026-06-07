import type { Levels, Quote } from '@/lib/types';
import { fmtNum, fmtPct } from '@/lib/format';
import { Card } from './Card';

export function LevelsPanel({ quote, levels }: { quote: Quote; levels: Levels }) {
  const rr = levels.risk_reward;
  const rrStatus =
    rr === null ? 'neutral' : rr >= 2 ? 'good' : rr >= 1 ? 'neutral' : 'bad';
  const rrLabel =
    rr === null
      ? 'לא ניתן לחישוב'
      : rr >= 2
      ? 'יחס מצוין'
      : rr >= 1
      ? 'יחס סביר'
      : 'יחס חלש — סיכון גבוה מסיכוי';

  return (
    <Card title="תמיכה והתנגדות" hint="מבוסס pivots ב-126 ימי מסחר אחרונים">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <LevelTile
          label="התנגדות"
          dotColor="bg-bad shadow-[0_0_8px_rgba(255,107,129,0.6)]"
          price={levels.resistance?.price ?? null}
          distance={levels.resistance?.distance_pct ?? null}
          touches={levels.resistance?.touches ?? null}
          accent="text-bad"
        />
        <LevelTile
          label="מחיר נוכחי"
          dotColor="bg-accent shadow-[0_0_8px_rgba(110,168,255,0.6)]"
          price={quote.price ?? null}
          distance={0}
          touches={null}
          accent="text-accent"
          showDistance={false}
        />
        <LevelTile
          label="תמיכה"
          dotColor="bg-good shadow-[0_0_8px_rgba(61,220,151,0.6)]"
          price={levels.support?.price ?? null}
          distance={levels.support?.distance_pct ?? null}
          touches={levels.support?.touches ?? null}
          accent="text-good"
        />
      </div>

      <div className="mt-5 border-t border-border pt-4">
        <div className="flex items-baseline justify-between">
          <div className="flex items-center gap-2 text-sm text-muted">
            <StatusBadge status={rrStatus} />
            <span>יחס סיכון:סיכוי (R:R)</span>
          </div>
          <span className={`ltr text-2xl font-bold ${rrColor(rrStatus)}`}>
            {rr === null ? '—' : `1 : ${rr.toFixed(2)}`}
          </span>
        </div>
        <p className="mt-1 text-xs text-muted">{rrLabel}</p>
        <p className="mt-2 text-[11px] text-muted">
          R:R = (התנגדות − מחיר) ÷ (מחיר − תמיכה). ערכים ≥ 2 נחשבים אטרקטיביים.
        </p>
      </div>
    </Card>
  );
}

function LevelTile({
  label,
  dotColor,
  price,
  distance,
  touches,
  accent,
  showDistance = true,
}: {
  label: string;
  dotColor: string;
  price: number | null;
  distance: number | null;
  touches: number | null;
  accent: string;
  showDistance?: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-panel2/60 p-4">
      <div className="mb-2 flex items-center gap-2 text-xs text-muted">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${dotColor}`} aria-hidden />
        <span>{label}</span>
      </div>
      <div className={`ltr text-2xl font-bold ${accent}`}>
        {price === null ? '—' : fmtNum(price)}
      </div>
      <div className="mt-1 text-[11px] text-muted">
        {showDistance && distance !== null && price !== null && (
          <span className="ltr">{fmtPct(distance)} מהמחיר</span>
        )}
        {touches !== null && (
          <span className="mr-2">{touches} נגיעות</span>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: 'good' | 'bad' | 'neutral' }) {
  const cls =
    status === 'good' ? 'bg-good' : status === 'bad' ? 'bg-bad' : 'bg-muted/40';
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${cls}`} aria-hidden />;
}

function rrColor(status: 'good' | 'bad' | 'neutral'): string {
  if (status === 'good') return 'text-good';
  if (status === 'bad') return 'text-bad';
  return 'text-text';
}
