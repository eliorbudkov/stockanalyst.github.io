'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { Heatmap, HeatmapStock } from '@/lib/types';
import { squarify, type TreemapResult } from '@/lib/treemap';
import { Card } from './Card';

const REFRESH_MS = 5 * 60 * 1000;

const SECTOR_ORDER = [
  'Technology',
  'Communication',
  'Consumer Discretionary',
  'Financials',
  'Healthcare',
  'Consumer Staples',
  'Energy',
  'Industrials',
  'Real Estate',
  'Utilities',
  'Materials',
];

const SECTOR_HE: Record<string, string> = {
  Technology: 'טכנולוגיה',
  Communication: 'תקשורת',
  'Consumer Discretionary': 'מוצרי צריכה - מותרות',
  'Consumer Staples': 'מוצרי צריכה - בסיסיים',
  Financials: 'פיננסים',
  Healthcare: 'בריאות',
  Energy: 'אנרגיה',
  Industrials: 'תעשייה',
  'Real Estate': 'נדל"ן',
  Utilities: 'תשתיות',
  Materials: 'חומרי גלם',
};

function tileColor(pct: number): { bg: string; fg: string } {
  // TradingView-like: deep red ↔ neutral gray ↔ deep green.
  // Saturation grows with |pct|, saturating at ±4%.
  const intensity = Math.min(Math.abs(pct), 4) / 4;
  if (Math.abs(pct) < 0.05) return { bg: '#2a3354', fg: '#e7ecff' };
  if (pct > 0) {
    // green: lerp from (42,71,58) → (61,220,151)
    const r = Math.round(42 + (61 - 42) * intensity);
    const g = Math.round(71 + (220 - 71) * intensity);
    const b = Math.round(58 + (151 - 58) * intensity);
    return { bg: `rgb(${r},${g},${b})`, fg: intensity > 0.4 ? '#0a1a10' : '#e7ecff' };
  }
  const r = Math.round(70 + (255 - 70) * intensity);
  const g = Math.round(42 + (107 - 42) * intensity);
  const b = Math.round(54 + (129 - 54) * intensity);
  return { bg: `rgb(${r},${g},${b})`, fg: intensity > 0.4 ? '#1a0610' : '#e7ecff' };
}

function timeAgo(unixSec: number): string {
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - unixSec));
  if (diff < 60) return `לפני ${diff} שניות`;
  if (diff < 3600) return `לפני ${Math.floor(diff / 60)} דקות`;
  if (diff < 86400) return `לפני ${Math.floor(diff / 3600)} שעות`;
  return `לפני ${Math.floor(diff / 86400)} ימים`;
}

type SectorBucket = {
  sector: string;
  label: string;
  weight: number;            // sum of market caps
  avgChange: number;
  stocks: HeatmapStock[];
};

export function MarketHeatmap() {
  const [data, setData] = useState<Heatmap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [, setTick] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  async function load(force = false) {
    try {
      setError(null);
      if (!data) setLoading(true);
      const res = await api.heatmap(force);
      setData(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'שגיאה');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    timer.current = setInterval(() => load(), REFRESH_MS);
    const tickTimer = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => {
      if (timer.current) clearInterval(timer.current);
      clearInterval(tickTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card
      title="מפת חום — S&P 500"
      hint={data ? `${data.summary.total} מניות · ${timeAgo(data.fetched_at)}` : ''}
    >
      {error && !data && <div className="text-sm text-bad">לא הצלחנו לטעון: {error}</div>}
      {loading && !data && (
        <div className="grid h-[640px] place-items-center text-sm text-muted">טוען…</div>
      )}
      {data && (
        <>
          <Summary data={data} />
          <Treemap data={data} />
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3 text-xs text-muted">
            <button onClick={() => load(true)} className="text-accent hover:underline">
              רענן עכשיו
            </button>
            <Legend />
            <span>גודל ריבוע ∝ שווי שוק · צבע = שינוי יומי</span>
          </div>
        </>
      )}
    </Card>
  );
}

function Treemap({ data }: { data: Heatmap }) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(1100);
  // Responsive height: 420px on phones, 540px on tablets, 640px on desktop.
  const [height, setHeight] = useState(640);

  useEffect(() => {
    if (!wrapRef.current) return;
    const el = wrapRef.current;
    const update = () => {
      const w = Math.max(320, el.clientWidth);
      setWidth(w);
      setHeight(w < 480 ? 420 : w < 768 ? 540 : 640);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const HEIGHT = height;

  const buckets = useMemo<SectorBucket[]>(() => {
    const m = new Map<string, SectorBucket>();
    for (const s of data.stocks) {
      const b = m.get(s.sector) ?? {
        sector: s.sector,
        label: SECTOR_HE[s.sector] ?? s.sector,
        weight: 0,
        avgChange: 0,
        stocks: [],
      };
      b.stocks.push(s);
      b.weight += s.market_cap_b;
      m.set(s.sector, b);
    }
    for (const b of m.values()) {
      b.avgChange = b.stocks.reduce((sum, s) => sum + s.change_pct, 0) / b.stocks.length;
      b.stocks.sort((a, z) => z.market_cap_b - a.market_cap_b);
    }
    return SECTOR_ORDER.map((k) => m.get(k)).filter((b): b is SectorBucket => !!b);
  }, [data]);

  const sectorRects = useMemo(
    () =>
      squarify(
        buckets.map((b) => ({ id: b.sector, value: b.weight, data: b })),
        { x: 0, y: 0, w: width, h: HEIGHT },
      ),
    [buckets, width],
  );

  return (
    <div
      ref={wrapRef}
      className="relative mt-4 overflow-hidden rounded-lg border border-border bg-bg"
      style={{ width: '100%', height: HEIGHT }}
    >
      {sectorRects.map((sr) => (
        <SectorBlock key={sr.item.id} rect={sr.rect} bucket={sr.item.data} />
      ))}
    </div>
  );
}

function SectorBlock({
  rect,
  bucket,
}: {
  rect: { x: number; y: number; w: number; h: number };
  bucket: SectorBucket;
}) {
  // Reserve a narrow header strip for the sector name (only if the block is tall enough).
  const HEADER_H = rect.h >= 80 && rect.w >= 90 ? 18 : 0;
  const stockBox = {
    x: rect.x + 1,
    y: rect.y + HEADER_H + 1,
    w: Math.max(0, rect.w - 2),
    h: Math.max(0, rect.h - HEADER_H - 2),
  };

  const tiles = useMemo(
    () =>
      squarify(
        bucket.stocks.map((s) => ({ id: s.symbol, value: s.market_cap_b, data: s })),
        stockBox,
      ),
    [bucket, stockBox.x, stockBox.y, stockBox.w, stockBox.h],
  );

  const avgColor =
    bucket.avgChange > 0 ? '#3ddc97' : bucket.avgChange < 0 ? '#ff6b81' : '#8c97c2';

  return (
    <>
      {HEADER_H > 0 && (
        <div
          className="pointer-events-none absolute flex items-center justify-between border-b border-border/60 bg-panel/80 px-2 backdrop-blur-sm"
          style={{
            left: rect.x,
            top: rect.y,
            width: rect.w,
            height: HEADER_H,
          }}
        >
          <span className="truncate text-[10px] font-semibold text-text">
            {bucket.label}
          </span>
          <span className="ltr text-[10px] font-semibold" style={{ color: avgColor }}>
            {bucket.avgChange > 0 ? '+' : ''}
            {bucket.avgChange.toFixed(2)}%
          </span>
        </div>
      )}
      {tiles.map((t) => (
        <StockTile key={t.item.id} rect={t.rect} stock={t.item.data} />
      ))}
    </>
  );
}

function StockTile({
  rect,
  stock,
}: {
  rect: { x: number; y: number; w: number; h: number };
  stock: HeatmapStock;
}) {
  const { bg, fg } = tileColor(stock.change_pct);
  const area = rect.w * rect.h;
  // Font size & visibility based on tile area.
  const symbolSize = Math.max(9, Math.min(28, Math.sqrt(area) / 5.5));
  const showChange = area > 700;
  const showName = area > 4500;

  const sign = stock.change_pct > 0 ? '+' : '';
  return (
    <a
      href={`/stock/${encodeURIComponent(stock.symbol)}`}
      title={`${stock.name} (${stock.symbol}) · $${stock.price} · ${sign}${stock.change_pct.toFixed(2)}%`}
      className="absolute flex flex-col items-center justify-center overflow-hidden border border-bg/60 text-center transition hover:z-10 hover:ring-2 hover:ring-accent"
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.w,
        height: rect.h,
        backgroundColor: bg,
        color: fg,
      }}
    >
      <span
        className="ltr font-bold leading-tight"
        style={{ fontSize: `${symbolSize}px` }}
      >
        {stock.symbol}
      </span>
      {showChange && (
        <span
          className="ltr font-semibold leading-tight"
          style={{ fontSize: `${symbolSize * 0.55}px` }}
        >
          {sign}
          {stock.change_pct.toFixed(2)}%
        </span>
      )}
      {showName && (
        <span
          className="truncate px-1 leading-tight opacity-80"
          style={{ fontSize: `${symbolSize * 0.45}px`, maxWidth: rect.w - 6 }}
        >
          {stock.name}
        </span>
      )}
    </a>
  );
}

function Summary({ data }: { data: Heatmap }) {
  const s = data.summary;
  const avg = s.avg_change_pct;
  const avgColor =
    avg === null ? 'text-muted' : avg > 0 ? 'text-good' : avg < 0 ? 'text-bad' : 'text-muted';
  return (
    <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
      <Stat label="מניות במעקב" value={s.total.toString()} />
      <Stat label="עולות" value={s.advancers.toString()} valueClass="text-good" />
      <Stat label="יורדות" value={s.decliners.toString()} valueClass="text-bad" />
      <Stat
        label="שינוי ממוצע"
        value={avg === null ? '—' : `${avg > 0 ? '+' : ''}${avg.toFixed(2)}%`}
        valueClass={avgColor}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-panel2/60 p-3">
      <div className="text-[11px] text-muted">{label}</div>
      <div className={`ltr text-lg font-bold ${valueClass ?? ''}`}>{value}</div>
    </div>
  );
}

function Legend() {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[11px]">−4%</span>
      <span
        className="h-3 w-32 rounded-sm"
        style={{
          background:
            'linear-gradient(to left, rgb(255,107,129), rgb(70,42,54), rgb(42,71,58), rgb(61,220,151))',
        }}
      />
      <span className="text-[11px]">+4%</span>
    </div>
  );
}
