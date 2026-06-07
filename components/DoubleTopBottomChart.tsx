'use client';

import { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type UTCTimestamp,
} from 'lightweight-charts';
import type { Candle, DoubleTopBottomGeometry, PatternSignal } from '@/lib/types';
import { Card } from './Card';
import { fmtNum, fmtPct } from '@/lib/format';

type Props = {
  candles: Candle[];
  signal: PatternSignal;
  height?: number;
};

function isDoubleGeometry(
  g: PatternSignal['geometry'],
): g is DoubleTopBottomGeometry {
  return !!g && (g as DoubleTopBottomGeometry).kind === 'double_top'
    || !!g && (g as DoubleTopBottomGeometry).kind === 'double_bottom';
}

export function DoubleTopBottomChart({ candles, signal, height = 340 }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const g = signal.geometry as DoubleTopBottomGeometry | undefined;

  useEffect(() => {
    if (!ref.current || !g || !isDoubleGeometry(g)) return;

    const isTop = g.kind === 'double_top';
    const accent = isTop ? '#ff6b81' : '#3ddc97';
    const pointLabel = isTop ? 'שיא' : 'שפל';
    const pointShape = isTop ? 'arrowDown' : 'arrowUp';
    const pointPosition = isTop ? 'aboveBar' : 'belowBar';

    const chart = createChart(ref.current, {
      width: ref.current.clientWidth,
      height,
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
      timeScale: { borderColor: '#26305a', timeVisible: true },
      crosshair: { mode: CrosshairMode.Normal },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#3ddc97',
      downColor: '#ff6b81',
      borderUpColor: '#3ddc97',
      borderDownColor: '#ff6b81',
      wickUpColor: '#3ddc97',
      wickDownColor: '#ff6b81',
    });
    candleSeries.setData(
      candles.map((c) => ({
        time: c.time as UTCTimestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );

    // Markers on the two extremes + neckline.
    // lightweight-charts requires markers sorted ascending by time — the
    // neckline sits between the two tops/bottoms, so we sort explicitly.
    const markers: Parameters<typeof candleSeries.setMarkers>[0] = [
      {
        time: g.first.time as UTCTimestamp,
        position: pointPosition,
        color: accent,
        shape: pointShape,
        text: `${pointLabel} 1`,
      },
      {
        time: g.neckline.time as UTCTimestamp,
        position: isTop ? 'belowBar' : 'aboveBar',
        color: '#ffb454',
        shape: 'circle',
        text: 'neckline',
      },
      {
        time: g.second.time as UTCTimestamp,
        position: pointPosition,
        color: accent,
        shape: pointShape,
        text: `${pointLabel} 2`,
      },
    ].sort((a, b) => (a.time as number) - (b.time as number));
    candleSeries.setMarkers(markers);

    // Outline: first → neckline → second
    const outline = chart.addLineSeries({
      color: accent,
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    outline.setData([
      { time: g.first.time as UTCTimestamp, value: g.first.price },
      { time: g.neckline.time as UTCTimestamp, value: g.neckline.price },
      { time: g.second.time as UTCTimestamp, value: g.second.price },
    ]);

    // Horizontal level lines: neckline (breakout), target, stop
    if (signal.level !== null) {
      candleSeries.createPriceLine({
        price: signal.level,
        color: '#ffb454',
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: isTop ? 'Neckline / Break' : 'Neckline / Break',
      });
    }
    if (signal.target !== null) {
      candleSeries.createPriceLine({
        price: signal.target,
        color: isTop ? '#ff6b81' : '#3ddc97',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: 'יעד',
      });
    }
    if (signal.stop !== null) {
      candleSeries.createPriceLine({
        price: signal.stop,
        color: '#ff4d4d',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: 'סטופ',
      });
    }

    // Focus the viewport on the pattern window.
    const lastBar = candles[candles.length - 1]?.time;
    if (lastBar) {
      const span = g.second.time - g.first.time;
      const pad = Math.max(span * 0.25, 60 * 60 * 24 * 10); // ≥ 10 days
      const from = Math.max(candles[0]?.time ?? 0, g.first.time - pad) as UTCTimestamp;
      const to = lastBar as UTCTimestamp;
      try {
        chart.timeScale().setVisibleRange({ from, to });
      } catch {
        chart.timeScale().fitContent();
      }
    } else {
      chart.timeScale().fitContent();
    }

    const ro = new ResizeObserver(() => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth });
    });
    ro.observe(ref.current);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [candles, g, signal.level, signal.target, signal.stop, height]);

  if (!g || !isDoubleGeometry(g)) return null;
  const isTop = g.kind === 'double_top';
  const title = isTop ? 'גרף Double Top ייעודי' : 'גרף Double Bottom ייעודי';
  const pointLabel = isTop ? 'שיא' : 'שפל';
  const direction = isTop ? 'דובי — שבירת neckline מתחת מאשרת תנועה' : 'שורי — פריצת neckline מעל מאשרת תנועה';

  return (
    <Card
      title={title}
      hint={`גובה ${g.height_pct.toFixed(1)}% · דמיון בין הקצוות ${g.similarity_pct.toFixed(2)}% · ${g.broke ? 'נשבר' : 'לא נשבר'}`}
    >
      <div ref={ref} style={{ width: '100%', height }} />
      <div className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <Stat label={`${pointLabel} ראשון`} value={fmtNum(g.first.price)} color={isTop ? '#ff6b81' : '#3ddc97'} />
        <Stat label={`${pointLabel} שני`} value={fmtNum(g.second.price)} color={isTop ? '#ff6b81' : '#3ddc97'} />
        <Stat label="Neckline (פריצה)" value={fmtNum(g.neckline.price)} color="#ffb454" />
        <Stat
          label="יעד מדוד"
          value={signal.target !== null ? fmtNum(signal.target) : '—'}
          color={isTop ? '#ff6b81' : '#3ddc97'}
        />
      </div>
      <p className="mt-4 text-xs leading-relaxed text-muted">
        {direction}.
        {signal.target !== null && signal.level !== null && (
          <>
            {' יעד מדוד: '}
            <span className="ltr">{fmtNum(signal.target)}</span>
            {' (פוטנציאל '}
            <span className="ltr">
              {fmtPct(((signal.target - signal.level) / signal.level) * 100)}
            </span>
            {' מקו ה-neckline).'}
          </>
        )}
      </p>
    </Card>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="rounded-lg border border-border bg-panel2 p-3">
      <div className="flex items-center gap-2 text-[11px] text-muted">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />
        <span>{label}</span>
      </div>
      <div className="ltr mt-1 text-base font-semibold">{value}</div>
    </div>
  );
}
