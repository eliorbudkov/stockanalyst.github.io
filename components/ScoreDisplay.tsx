import type { ScoreBreakdown, SectorStatus } from '@/lib/types';
import { Card } from './Card';

function scoreColor(score: number): string {
  if (score >= 8) return 'text-good';
  if (score >= 5) return 'text-warn';
  return 'text-bad';
}

function scoreLabel(score: number): string {
  if (score >= 9) return 'הזדמנות יוצאת דופן';
  if (score >= 7) return 'מומלץ - סיכון/סיכוי טוב';
  if (score >= 5) return 'מתון - דרושה זהירות';
  if (score >= 3) return 'חלש - להמתין';
  return 'מסוכן - להימנע';
}

export function ScoreDisplay({
  score,
  breakdown,
  rationale,
  sectorStatus,
}: {
  score: number;
  breakdown: ScoreBreakdown;
  rationale: string[];
  sectorStatus: SectorStatus | null;
}) {
  const rounded = Math.round(score * 10) / 10;

  return (
    <Card title="ציון כניסה" hint="0 = להימנע · 10 = הזדמנות מצוינת">
      <div className="flex flex-col items-stretch gap-4 sm:flex-row sm:items-start sm:gap-6">
        <div className="text-center">
          <div className={`ltr text-5xl font-extrabold sm:text-6xl ${scoreColor(rounded)}`}>{rounded}</div>
          <div className="mt-1 text-xs text-muted">מתוך 10</div>
          <div className={`mt-2 text-sm font-semibold ${scoreColor(rounded)}`}>{scoreLabel(rounded)}</div>
          <SectorHeatmapStatus sectorStatus={sectorStatus} />
        </div>

        <div className="flex-1 space-y-2">
          <Bar label="מגמה" value={breakdown.trend} weight="20%" />
          <Bar label="מומנטום (RSI)" value={breakdown.momentum} weight="13%" />
          <Bar label="MACD / Bollinger / VWAP" value={breakdown.advanced_technicals} weight="13%" />
          <Bar label="תנודתיות (ATR)" value={breakdown.volatility} weight="10%" />
          <Bar label="נפח מסחר" value={breakdown.volume} weight="10%" />
          <Bar label="פונדמנטלס" value={breakdown.fundamentals} weight="13%" />
          <Bar label="תבניות טכניות" value={breakdown.patterns} weight="8%" />
          <Bar label="Heatmap סקטוריאלי" value={breakdown.heatmap} weight="8%" />
          <Bar label="התנהגות — Insider / Short" value={breakdown.behavior_sentiment} weight="5%" />
        </div>
      </div>

      {rationale.length > 0 && (
        <ul className="mt-5 space-y-1.5 border-t border-border pt-4 text-sm text-muted">
          {rationale.map((r, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-accent">•</span>
              <span>{r}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SectorHeatmapStatus({ sectorStatus }: { sectorStatus: SectorStatus | null }) {
  if (!sectorStatus) {
    return (
      <div className="mt-3 border-t border-border pt-3 text-xs text-muted">
        סטטוס סקטור: לא זמין
      </div>
    );
  }

  const isPositive = sectorStatus.avg_change_pct >= 0;
  const statusColor = isPositive ? 'bg-good' : 'bg-bad';
  const textColor = isPositive ? 'text-good' : 'text-bad';

  return (
    <div className="mt-3 border-t border-border pt-3">
      <div className="flex items-center justify-center gap-2 text-xs">
        <span
          className={`h-2.5 w-2.5 shrink-0 rounded-full ${statusColor}`}
          aria-label={isPositive ? 'סקטור חיובי' : 'סקטור שלילי'}
          title={isPositive ? 'סקטור חיובי לפי מפת החום' : 'סקטור שלילי לפי מפת החום'}
        />
        <span className="text-muted">Heatmap:</span>
        <span className="font-semibold text-text">{sectorStatus.sector_label}</span>
        <span className={`ltr font-semibold ${textColor}`}>
          {sectorStatus.avg_change_pct > 0 ? '+' : ''}
          {sectorStatus.avg_change_pct.toFixed(2)}%
        </span>
      </div>
    </div>
  );
}

function Bar({ label, value, weight }: { label: string; value: number; weight: string }) {
  const safeValue = Number.isFinite(value) ? value : 0;
  const pct = Math.max(0, Math.min(10, safeValue)) * 10;
  return (
    <div>
      <div className="mb-1 flex justify-between gap-3 text-xs">
        <span className="text-muted">
          {label} <span className="ltr text-[10px] opacity-70">({weight})</span>
        </span>
        <span className="ltr font-semibold">{safeValue.toFixed(1)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-panel2">
        <div
          className="h-full rounded-full bg-gradient-to-l from-good via-warn to-bad"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
