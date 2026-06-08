'use client';

import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { ScanItem, ScanResult } from '@/lib/types';
import { Card } from './Card';
import { fmtPct } from '@/lib/format';

function timeAgo(unixSec: number): string {
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - unixSec));
  if (diff < 60) return `לפני ${diff} שניות`;
  if (diff < 3600) return `לפני ${Math.floor(diff / 60)} דקות`;
  if (diff < 86400) return `לפני ${Math.floor(diff / 3600)} שעות`;
  return `לפני ${Math.floor(diff / 86400)} ימים`;
}

function scoreColor(score: number): string {
  if (score >= 9) return '#3ddc97';
  if (score >= 8) return '#7ed957';
  if (score >= 5) return '#ffb454';
  return '#ff6b81';
}

function scoreBg(score: number): string {
  const c = scoreColor(score);
  return c;
}

function strategyAccent(strategy?: string): string {
  if (strategy === 'swing') return '#6ea8ff';
  if (strategy === 'investment') return '#b88cff';
  if (strategy === 'etf') return '#3ddc97';
  return '#8c97c2';
}

export function DailyScanner() {
  const [data, setData] = useState<ScanResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, setTick] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const initialLoadStartedRef = useRef(false);
  // Stale-while-revalidate: a cold server serves cached/seed data instantly and
  // refreshes in the background (~90s). These let us poll a few times to pick up
  // the fresh result without the user having to hit "rescan".
  const staleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const staleRetryRef = useRef(0);

  async function load(force = false) {
    try {
      setError(null);
      if (force) setScanning(true);
      else if (!data) setLoading(true);
      const res = await api.scan(force);
      setData(res);

      // If the server handed back stale cached/seed data (cold start), it is
      // refreshing in the background — poll a few times to swap in fresh numbers.
      if (staleTimerRef.current) {
        clearTimeout(staleTimerRef.current);
        staleTimerRef.current = null;
      }
      const ageSec = Date.now() / 1000 - res.fetched_at;
      if (!force && ageSec > 600 && staleRetryRef.current < 3) {
        staleRetryRef.current += 1;
        staleTimerRef.current = setTimeout(() => load(false), 90_000);
      } else if (ageSec <= 600) {
        staleRetryRef.current = 0;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'שגיאה');
    } finally {
      setLoading(false);
      setScanning(false);
    }
  }

  useEffect(() => {
    if (!initialLoadStartedRef.current) {
      initialLoadStartedRef.current = true;
      load(false);
    }
    timerRef.current = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (staleTimerRef.current) clearTimeout(staleTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card
      title="סריקה יומית — טופ 5 הזדמנויות"
      hint={
        data
          ? `${data.qualified_count}/${data.evaluated_count} מעל ${data.threshold}+ · ${timeAgo(data.fetched_at)}`
          : ''
      }
    >
      <ScannerHeader
        data={data}
        scanning={scanning}
        onRescan={() => load(true)}
      />

      {data && (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 rounded-md border border-border/60 bg-panel2/40 px-3 py-2 text-[11px] text-muted">
          <span>מדדים: <b className="ltr text-text">{data.index_universe_size}</b></span>
          <span>מומנטום: <b className="ltr text-warn">{data.momentum_universe_size}</b></span>
          <span>נוספו מחוץ למדדים: <b className="ltr text-good">{data.momentum_added_count}</b></span>
          <span>יקום דינמי: <b className="ltr text-text">{data.stock_universe_size}</b> מניות</span>
          <span>Tier 1 תקינים: <b className="ltr text-text">{data.tier1_valid_count}</b></span>
          <span>Tier 2: <b className="ltr text-accent">{data.tier2_candidate_count}</b></span>
          <span>קריאות info: <b className="ltr text-text">{data.tier2_info_calls}</b></span>
          <span>ETFs: <b className="ltr text-text">{data.etf_universe_size}</b></span>
          <span>משך: <b className="ltr text-text">{data.scan_duration_seconds.toFixed(1)}s</b></span>
          {data.scan_timings && (
            <>
              <span>
                Batch מניות:{' '}
                <b className="ltr text-warn">
                  {(data.scan_timings.stock_batch_download_seconds ?? 0).toFixed(1)}s
                </b>
              </span>
              <span>
                Batch ETF:{' '}
                <b className="ltr text-good">
                  {(data.scan_timings.etf_batch_download_seconds ?? 0).toFixed(1)}s
                </b>
              </span>
            </>
          )}
        </div>
      )}

      {error && !data && (
        <div className="mt-4 rounded-md border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          לא הצלחנו לטעון: {error}
        </div>
      )}

      {(loading || scanning) && !data && (
        <div className="mt-4 grid h-48 place-items-center text-sm text-muted">
          {scanning ? 'מבצע סריקה חיה של השוק…' : 'טוען…'}
        </div>
      )}

      {data && data.top.length === 0 && (
        <div className="mt-5 rounded-md border border-border bg-panel2/60 p-4 text-center text-sm text-muted">
          לא נמצאו מועמדים עם ציון סופי ≥ {data.threshold} בסריקה האחרונה.
          <br />
          השוק כנראה במצב מאתגר היום — בדוק שוב מאוחר יותר.
        </div>
      )}

      {data && (
        <div className="mt-6 space-y-6">
          <ScanSection
            title="מניות לטווח קצר — Swing Setup"
            subtitle={`${data.qualified_swing_count ?? 0}/${data.stocks_evaluated} מועמדים — ST ≥ ${(data.swing_threshold ?? 8).toFixed(1)} וגם Overall ≥ ${(data.swing_overall_threshold ?? 7).toFixed(1)}`}
            accent="#6ea8ff"
            items={data.top_swing_stocks || []}
          />
          <ScanSection
            title="מניות לטווח ארוך — Long-Term Investment"
            subtitle={`${data.qualified_invest_count ?? 0}/${data.stocks_evaluated} מועמדים — LT ≥ ${data.threshold.toFixed(1)} וגם Overall ≥ ${(data.long_term_overall_threshold ?? 7.5).toFixed(1)}`}
            accent="#b88cff"
            items={data.top_invest_stocks || []}
          />
          <ScanSection
            title="קרנות סל (ETFs)"
            subtitle={`${data.qualified_etfs_count}/${data.etfs_evaluated} מועמדים — סף ${(data.etf_threshold ?? 7).toFixed(1)} · טכני 35% · Heatmap 30% · Inflows 15% · D/E 15% · GLI 5%`}
            accent="#3ddc97"
            items={data.top_etfs || []}
          />
        </div>
      )}

    </Card>
  );
}

function ScannerHeader({
  data,
  scanning,
  onRescan,
}: {
  data: ScanResult | null;
  scanning: boolean;
  onRescan: () => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Stat label="מועמדים" value={data ? data.qualified_count.toString() : '—'} accent="#3ddc97" />
      <Stat label="נסרקו" value={data ? data.evaluated_count.toString() : '—'} accent="#6ea8ff" />
      <Stat label="סף ציון" value={data ? `≥ ${data.threshold}` : '—'} accent="#ffb454" />
      <button
        onClick={onRescan}
        disabled={scanning}
        className={
          'rounded-lg border p-3 text-center text-sm font-semibold transition ' +
          (scanning
            ? 'cursor-wait border-border bg-panel2/60 text-muted'
            : 'border-accent/40 bg-accent/10 text-accent hover:bg-accent/20')
        }
      >
        {scanning ? 'סורק…' : 'סרוק עכשיו'}
      </button>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div className="rounded-lg border border-border bg-panel2/60 p-3">
      <div className="flex items-center gap-2 text-[11px] text-muted">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: accent }} />
        <span>{label}</span>
      </div>
      <div className="ltr mt-1 text-lg font-bold" style={{ color: accent }}>
        {value}
      </div>
    </div>
  );
}

function ScanCard({ item, rank }: { item: ScanItem; rank: number }) {
  const sec = item.sector_status;
  const isRed = sec?.is_red;
  const isGreen = sec?.is_green;
  const isQualified = item.is_qualified !== false;
  // Display the strategy-specific score, never a combined max/avg.
  const displayScore = item.display_score ?? item.final_score;
  return (
    <li>
      <a
        href={`/stock/${encodeURIComponent(item.symbol)}`}
        className={
          'block rounded-lg border bg-panel2/60 p-2.5 transition hover:border-accent hover:bg-panel2 ' +
          (isQualified ? 'border-border' : 'border-border/40 opacity-75')
        }
      >
        <div className="flex items-start gap-3">
          {/* Rank + score badge (smaller) */}
          <div className="flex flex-col items-center gap-1.5">
            <div className="grid h-5 w-5 place-items-center rounded-full bg-bg/70 text-[10px] font-bold text-muted">
              #{rank}
            </div>
            <div
              className="grid h-12 w-12 place-items-center rounded-xl text-base font-extrabold"
              style={{
                backgroundColor: `${scoreBg(displayScore)}33`,
                color: scoreColor(displayScore),
                border: `1.5px solid ${scoreColor(displayScore)}`,
              }}
            >
              {displayScore.toFixed(1)}
            </div>
            {item.strategy_label && (
              <span
                className="rounded-md px-1 py-0.5 text-[8px] font-semibold"
                style={{
                  background: `${strategyAccent(item.strategy)}22`,
                  color: strategyAccent(item.strategy),
                  border: `1px solid ${strategyAccent(item.strategy)}55`,
                }}
              >
                {item.strategy_label}
              </span>
            )}
            {!isQualified && (
              <span className="rounded-md bg-muted/15 px-1 py-0.5 text-[8px] text-muted">
                מתחת לסף
              </span>
            )}
          </div>

          {/* Main info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2">
              <h3 className="ltr text-base font-bold">{item.symbol}</h3>
              <span className="truncate text-[11px] text-muted">— {item.name}</span>
            </div>

            <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
              <span className="ltr">${item.price.toFixed(2)}</span>
              {item.change_pct !== null && (
                <span
                  className="ltr font-semibold"
                  style={{ color: item.change_pct >= 0 ? '#3ddc97' : '#ff6b81' }}
                >
                  {fmtPct(item.change_pct)}
                </span>
              )}
              {sec && (
                <span
                  className="rounded-md px-1.5 py-0.5 text-[10px]"
                  style={{
                    background: isGreen
                      ? 'rgba(61, 220, 151, 0.15)'
                      : isRed
                      ? 'rgba(255, 107, 129, 0.15)'
                      : 'rgba(140, 151, 194, 0.15)',
                    color: isGreen ? '#3ddc97' : isRed ? '#ff6b81' : '#8c97c2',
                  }}
                >
                  {sec.sector_label}{' '}
                  <span className="ltr">
                    {sec.avg_change_pct > 0 ? '+' : ''}
                    {sec.avg_change_pct.toFixed(2)}%
                  </span>
                </span>
              )}
              {(item.short_term_blocker || item.etf_blocker) && (
                <span className="rounded-md bg-bad/15 px-1.5 py-0.5 text-[10px] text-bad">
                  חוסם פעיל
                </span>
              )}
            </div>

            <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
              {/* Only show the strategy-specific score — never both. */}
              {item.strategy === 'swing' && item.short_term_score !== undefined && (
                <ScoreChip label="ST" value={item.short_term_score} />
              )}
              {item.strategy === 'swing' && item.overall_score !== undefined && (
                <ScoreChip label="Overall" value={item.overall_score} />
              )}
              {item.strategy === 'investment' && item.long_term_score !== undefined && (
                <ScoreChip label="LT" value={item.long_term_score} />
              )}
              {item.strategy === 'investment' && item.overall_score !== undefined && (
                <ScoreChip label="Overall" value={item.overall_score} />
              )}
              {item.strategy === 'etf' && item.etf_score !== undefined && (
                <ScoreChip label="ETF" value={item.etf_score} />
              )}

              {/* Strategy-specific context chips */}
              {item.strategy === 'swing' && item.short_term_bonus !== undefined && item.short_term_bonus > 0 && (
                <Chip label="בונוס" value={`+${item.short_term_bonus.toFixed(1)}`} color="#b88cff" />
              )}
              {item.strategy === 'investment' && item.long_term_bonus !== undefined && item.long_term_bonus > 0 && (
                <Chip label="Timing Bonus" value={`+${item.long_term_bonus.toFixed(2)}`} color="#3ddc97" />
              )}
              {item.strategy === 'etf' && item.net_inflows && (
                <Chip
                  label="Inflows"
                  value={`${item.net_inflows.shares_change_pct_30d >= 0 ? '+' : ''}${item.net_inflows.shares_change_pct_30d.toFixed(1)}%`}
                  color={item.net_inflows.shares_change_pct_30d >= 0 ? '#3ddc97' : '#ff6b81'}
                />
              )}
              {item.strategy === 'etf' && item.weighted_debt_equity && (
                <Chip label="D/E" value={item.weighted_debt_equity.weighted_de.toFixed(2)} color="#ffb454" />
              )}

              {item.rvol !== null && (
                <Chip label="RVOL" value={`×${item.rvol.toFixed(2)}`} color="#6ea8ff" />
              )}
              {item.momentum_sources && item.momentum_sources.length > 0 && (
                <Chip
                  label="Hot"
                  value={item.momentum_sources.includes('day_gainers') ? 'Gainer' : 'Active'}
                  color="#ffb454"
                />
              )}
              {item.gap_pct !== null && Math.abs(item.gap_pct) >= 0.5 && (
                <Chip
                  label="Gap"
                  value={fmtPct(item.gap_pct)}
                  color={item.gap_pct >= 0 ? '#3ddc97' : '#ff6b81'}
                />
              )}
            </div>

            {(() => {
              const reasons = item.display_rationale ?? item.top_reasons ?? [];
              if (reasons.length === 0) return null;
              return (
                <ul className="mt-1.5 space-y-0 text-[10px] text-muted">
                  {reasons.slice(0, 2).map((r, i) => (
                    <li key={i} className="flex gap-1.5 truncate">
                      <span className="text-accent">•</span>
                      <span className="truncate">{r}</span>
                    </li>
                  ))}
                </ul>
              );
            })()}
          </div>
        </div>
      </a>
    </li>
  );
}

function ScoreChip({ label, value }: { label: string; value: number }) {
  return (
    <span
      className="flex items-center gap-1 rounded-md border px-2 py-0.5"
      style={{
        borderColor: `${scoreColor(value)}55`,
        background: `${scoreColor(value)}15`,
        color: scoreColor(value),
      }}
    >
      <span className="text-muted">{label}:</span>
      <span className="ltr font-bold">{value.toFixed(1)}</span>
    </span>
  );
}

function Chip({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <span
      className="flex items-center gap-1 rounded-md border px-2 py-0.5"
      style={{ borderColor: `${color}55`, color }}
    >
      <span className="text-muted">{label}:</span>
      <span className="ltr font-bold">{value}</span>
    </span>
  );
}

function ScanSection({
  title,
  subtitle,
  accent,
  items,
}: {
  title: string;
  subtitle: string;
  accent: string;
  items: ScanItem[];
}) {
  return (
    <div>
      <div className="mb-3 flex items-center gap-2 border-b border-border/60 pb-2">
        <span className="inline-block h-3 w-1.5 rounded-sm" style={{ background: accent }} />
        <div className="flex-1">
          <h3 className="text-sm font-semibold" style={{ color: accent }}>
            {title}
          </h3>
          <p className="mt-0.5 text-[11px] text-muted">{subtitle}</p>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="rounded-md border border-border bg-panel2/40 p-3 text-center text-xs text-muted">
          אין מועמדים בקטגוריה זו בסריקה הנוכחית
        </div>
      ) : (
        <ol className="space-y-3">
          {items.map((item, i) => (
            <ScanCard key={item.symbol} item={item} rank={i + 1} />
          ))}
        </ol>
      )}
    </div>
  );
}
