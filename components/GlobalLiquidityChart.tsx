'use client';

import { useEffect, useRef, useState } from 'react';
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import { api } from '@/lib/api';
import type { GlobalLiquidity } from '@/lib/types';
import { Card } from './Card';

const HEIGHT = 260;

function trendColor(score: number): string {
  if (score >= 8) return '#3ddc97';
  if (score >= 6) return '#7ed957';
  if (score >= 4) return '#ffb454';
  return '#ff6b81';
}

function fmtPct(n: number | null): string {
  if (n === null) return '—';
  const s = n >= 0 ? '+' : '';
  return `${s}${n.toFixed(2)}%`;
}

function timeAgo(unixSec: number): string {
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - unixSec));
  if (diff < 3600) return `לפני ${Math.floor(diff / 60) || 1} דקות`;
  if (diff < 86400) return `לפני ${Math.floor(diff / 3600)} שעות`;
  return `לפני ${Math.floor(diff / 86400)} ימים`;
}

export function GlobalLiquidityChart() {
  const [data, setData] = useState<GlobalLiquidity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    api
      .globalLiquidity()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'שגיאה'));
  }, []);

  useEffect(() => {
    if (!wrapRef.current || !data) return;
    const chart = createChart(wrapRef.current, {
      width: wrapRef.current.clientWidth,
      height: HEIGHT,
      layout: {
        background: { type: ColorType.Solid, color: '#121831' },
        textColor: '#8c97c2',
        fontFamily: 'inherit',
      },
      grid: {
        vertLines: { color: '#1a2244' },
        horzLines: { color: '#1a2244' },
      },
      rightPriceScale: { borderColor: '#26305a' },
      timeScale: { borderColor: '#26305a', timeVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    });
    chartRef.current = chart;

    const line = chart.addAreaSeries({
      lineColor: trendColor(data.score),
      topColor: `${trendColor(data.score)}55`,
      bottomColor: `${trendColor(data.score)}05`,
      lineWidth: 2,
    });
    line.setData(
      data.series.map((p) => ({
        time: Math.floor(new Date(p.date).getTime() / 1000) as UTCTimestamp,
        value: p.value_b,
      })),
    );

    // Reference line at the latest value
    line.createPriceLine({
      price: data.latest_value_b,
      color: trendColor(data.score),
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: 'Latest',
    });

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (wrapRef.current) chart.applyOptions({ width: wrapRef.current.clientWidth });
    });
    ro.observe(wrapRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [data]);

  return (
    <Card
      title="מדד הנזילות הגלובלי"
      hint={data ? `${data.indicator} · ${timeAgo(data.fetched_at)}` : ''}
    >
      {error && !data && (
        <div className="text-sm text-bad">
          לא הצלחנו לטעון מ-FRED: {error}
        </div>
      )}
      {!data && !error && (
        <div className="grid h-40 place-items-center text-sm text-muted">טוען…</div>
      )}
      {data && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat
              label="ערך אחרון"
              value={`$${data.latest_value_b.toFixed(0)}B`}
              accent={trendColor(data.score)}
            />
            <Stat
              label="שינוי 4W"
              value={fmtPct(data.change_4w_pct)}
              accent={
                data.change_4w_pct !== null && data.change_4w_pct >= 0 ? '#3ddc97' : '#ff6b81'
              }
            />
            <Stat
              label="שינוי 13W"
              value={fmtPct(data.change_13w_pct)}
              accent={
                data.change_13w_pct !== null && data.change_13w_pct >= 0 ? '#3ddc97' : '#ff6b81'
              }
            />
            <Stat
              label="שינוי 52W"
              value={fmtPct(data.change_52w_pct)}
              accent={
                data.change_52w_pct !== null && data.change_52w_pct >= 0 ? '#3ddc97' : '#ff6b81'
              }
            />
          </div>

          <div
            ref={wrapRef}
            className="rounded-lg border border-border"
            style={{ width: '100%', height: HEIGHT }}
          />

          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-xs">
            <div>
              <span className="text-muted">מגמה:</span>{' '}
              <span style={{ color: trendColor(data.score) }}>{data.trend_label}</span>
            </div>
            <div>
              <span className="text-muted">ציון מאקרו (משקל 5% במטריצות):</span>{' '}
              <span className="ltr font-bold" style={{ color: trendColor(data.score) }}>
                {data.score.toFixed(1)}/10
              </span>
            </div>
            <div className="text-[10px] text-muted">{data.source}</div>
          </div>
        </>
      )}
    </Card>
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
