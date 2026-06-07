import type { Matrices, MatrixScore } from '@/lib/types';
import { Card } from './Card';
import { fmtPct } from '@/lib/format';

function scoreColor(score: number): string {
  if (score >= 8) return 'text-good';
  if (score >= 5) return 'text-warn';
  return 'text-bad';
}

function scoreLabel(score: number): string {
  if (score >= 8.5) return 'הזדמנות חזקה';
  if (score >= 7) return 'מומלץ';
  if (score >= 5) return 'מתון';
  if (score >= 3) return 'חלש';
  return 'להימנע';
}

export function DualMatrixPanel({ matrices }: { matrices: Matrices }) {
  const sector = matrices.sector_status;
  return (
    <Card
      title="מטריצות ניתוח כפולות — קצר וארוך"
      hint="כל מטריצה מציגה ציון 1-10 עצמאי לפי קריטריונים שונים"
    >
      <ContextRow matrices={matrices} />

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <MatrixBlock
          title="טווח קצר — סווינג"
          subtitle="RVOL · גאפים · VWAP · RSI · תבניות פריצה · רוח גבית סקטוריאלית"
          matrix={matrices.short_term}
          accent="#6ea8ff"
        />
        <MatrixBlock
          title="טווח ארוך — השקעות"
          subtitle="DCF · חוסן מאזני · רוטציה סקטוריאלית · פאניקת מאקרו · אינסיידרים"
          matrix={matrices.long_term}
          accent="#3ddc97"
        />
      </div>

      {sector && (
        <div className="mt-5 rounded-lg border border-border bg-panel2/60 p-3 text-xs">
          <strong className="text-text">מצב סקטור ({sector.sector_label}):</strong>{' '}
          <span
            className={
              sector.is_green ? 'text-good' : sector.is_red ? 'text-bad' : 'text-muted'
            }
          >
            {sector.avg_change_pct > 0 ? '+' : ''}
            {sector.avg_change_pct.toFixed(2)}%
          </span>{' '}
          <span className="text-muted">
            · {sector.advancers} עולות, {sector.decliners} יורדות מתוך {sector.members} במפת החום
          </span>
        </div>
      )}
    </Card>
  );
}

function ContextRow({ matrices }: { matrices: Matrices }) {
  const rvol = matrices.rvol;
  const gap = matrices.gap_pct;
  const sector = matrices.sector_status;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Pill
        label="RVOL"
        value={rvol === null ? '—' : `×${rvol.toFixed(2)}`}
        hint={
          rvol === null
            ? 'לא זמין'
            : rvol >= 2
            ? 'גבוה מאוד'
            : rvol >= 1.1
            ? 'מעל הממוצע'
            : 'רגיל'
        }
        color={rvol !== null && rvol >= 1.5 ? '#3ddc97' : '#8c97c2'}
      />
      <Pill
        label="Gap"
        value={gap === null ? '—' : fmtPct(gap)}
        hint={
          gap === null
            ? 'לא זמין'
            : gap >= 2
            ? 'Gap up משמעותי'
            : gap <= -2
            ? 'Gap down משמעותי'
            : 'תנועה רגילה'
        }
        color={
          gap !== null && gap >= 2 ? '#3ddc97' : gap !== null && gap <= -2 ? '#ff6b81' : '#8c97c2'
        }
      />
      <Pill
        label="סקטור"
        value={sector ? sector.sector_label : '—'}
        hint={
          sector
            ? `${sector.avg_change_pct > 0 ? '+' : ''}${sector.avg_change_pct.toFixed(2)}% ממוצע`
            : 'לא זמין'
        }
        color={sector?.is_green ? '#3ddc97' : sector?.is_red ? '#ff6b81' : '#8c97c2'}
      />
      <Pill
        label="חוסם אלגוריתמי"
        value={matrices.short_term.blocker_applied ? 'פעיל −1' : 'לא פעיל'}
        hint={
          matrices.short_term.blocker_applied
            ? 'סקטור אדום — הופחתה נקודה מציון הסווינג'
            : 'הסקטור אינו במצב אדום'
        }
        color={matrices.short_term.blocker_applied ? '#ff6b81' : '#8c97c2'}
      />
    </div>
  );
}

function Pill({
  label,
  value,
  hint,
  color,
}: {
  label: string;
  value: string;
  hint: string;
  color: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-panel2/60 p-3">
      <div className="flex items-center gap-2 text-[11px] text-muted">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />
        <span>{label}</span>
      </div>
      <div className="ltr mt-1 text-base font-bold" style={{ color }}>
        {value}
      </div>
      <div className="mt-0.5 text-[10px] text-muted">{hint}</div>
    </div>
  );
}

function MatrixBlock({
  title,
  subtitle,
  matrix,
  accent,
}: {
  title: string;
  subtitle: string;
  matrix: MatrixScore;
  accent: string;
}) {
  const rounded = Math.round(matrix.score * 10) / 10;
  return (
    <div className="rounded-xl border border-border bg-panel2/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold" style={{ color: accent }}>
            {title}
          </h3>
          <p className="mt-1 text-[11px] leading-relaxed text-muted">{subtitle}</p>
        </div>
        <div className="text-center">
          <div className={`ltr text-4xl font-extrabold ${scoreColor(rounded)}`}>{rounded}</div>
          <div className="text-[10px] text-muted">מתוך 10</div>
          <div className={`mt-0.5 text-[11px] font-semibold ${scoreColor(rounded)}`}>
            {scoreLabel(rounded)}
          </div>
        </div>
      </div>

      {matrix.blocker_applied && matrix.blocker_reason && (
        <div className="mt-3 rounded-md border border-bad/40 bg-bad/10 p-2 text-[11px] leading-relaxed text-bad">
          {matrix.blocker_reason}
          <div className="mt-1 text-bad/70">
            ציון לפני החוסם: <span className="ltr">{matrix.raw_score.toFixed(2)}</span>
          </div>
        </div>
      )}

      {matrix.bonus !== undefined && matrix.bonus > 0 && (
        <div className="mt-3 rounded-md border border-good/40 bg-good/10 p-2 text-[11px] leading-relaxed text-good">
          Timing Bonus: <span className="ltr font-semibold">+{matrix.bonus.toFixed(2)}</span>
          <div className="mt-1 text-good/70">
            ציון ליבה פנדמנטלי: <span className="ltr">{matrix.raw_score.toFixed(2)}</span>
          </div>
        </div>
      )}

      <div className="mt-4 space-y-2">
        {matrix.categories.map((c) => (
          <CategoryBar key={c.name} category={c} accent={accent} />
        ))}
      </div>

      {matrix.position_size_pct !== null && (
        <div className="mt-4 rounded-md border border-border bg-bg/50 p-2 text-[11px]">
          <span className="text-muted">הקצאה מקסימלית מומלצת:</span>{' '}
          <span className="ltr font-semibold" style={{ color: accent }}>
            עד {matrix.position_size_pct.toFixed(0)}% מהתיק
          </span>
        </div>
      )}

      <ul className="mt-3 space-y-1 text-[11px] leading-relaxed text-muted">
        {matrix.rationale.slice(0, 8).map((r, i) => (
          <li key={i} className="flex gap-2">
            <span style={{ color: accent }}>•</span>
            <span>{r}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CategoryBar({
  category,
  accent,
}: {
  category: { name: string; score: number; weight: number; skipped?: boolean };
  accent: string;
}) {
  const pct = Math.max(0, Math.min(10, category.score)) * 10;
  const isSkipped = category.skipped === true;
  return (
    <div className={isSkipped ? 'opacity-50' : ''}>
      <div className="mb-1 flex justify-between text-[11px]">
        <span className="text-muted">
          {category.name}{' '}
          <span className="ltr text-[10px] opacity-70">
            ({(category.weight * 100).toFixed(0)}%)
          </span>
          {isSkipped && (
            <span className="ms-2 rounded-md border border-muted/40 bg-muted/10 px-1.5 py-0.5 text-[9px] text-muted">
              לא נכלל בממוצע
            </span>
          )}
        </span>
        <span className="ltr font-semibold">
          {isSkipped ? '—' : category.score.toFixed(1)}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-bg/70">
        <div
          className="h-full rounded-full"
          style={{
            width: `${pct}%`,
            background: accent,
            opacity: isSkipped ? 0.3 : 0.85,
          }}
        />
      </div>
    </div>
  );
}
