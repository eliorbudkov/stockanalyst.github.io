'use client';

import { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import type { Candle, PatternSignal } from '@/lib/types';
import { Card } from './Card';
import { fmtNum, fmtPct } from '@/lib/format';

type Props = {
  candles: Candle[];
  signal: PatternSignal;
  height?: number;
};

export function CupHandleChart({ candles, signal, height = 360 }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const g = signal.geometry;

  useEffect(() => {
    if (!ref.current || !g) return;

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

    // Markers on the structural points (cup outline + handle)
    const markers: Parameters<typeof candleSeries.setMarkers>[0] = [
      {
        time: g.left_rim.time as UTCTimestamp,
        position: 'aboveBar',
        color: '#ffb454',
        shape: 'arrowDown',
        text: 'רים שמאלי',
      },
      {
        time: g.bottom.time as UTCTimestamp,
        position: 'belowBar',
        color: '#6ea8ff',
        shape: 'arrowUp',
        text: 'תחתית הגביע',
      },
      {
        time: g.right_rim.time as UTCTimestamp,
        position: 'aboveBar',
        color: '#ffb454',
        shape: 'arrowDown',
        text: 'רים ימני',
      },
    ];
    if (g.handle_low) {
      markers.push({
        time: g.handle_low.time as UTCTimestamp,
        position: 'belowBar',
        color: '#b88cff',
        shape: 'circle',
        text: 'תחתית הידית',
      });
    }
    candleSeries.setMarkers(markers);

    // Cup outline as a 3-point line series (left rim → bottom → right rim)
    const cupLine = chart.addLineSeries({
      color: '#6ea8ff',
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    cupLine.setData([
      { time: g.left_rim.time as UTCTimestamp, value: g.left_rim.price },
      { time: g.bottom.time as UTCTimestamp, value: g.bottom.price },
      { time: g.right_rim.time as UTCTimestamp, value: g.right_rim.price },
    ]);

    // Handle line — from right rim to handle low
    if (g.handle_low) {
      const handleLine = chart.addLineSeries({
        color: '#b88cff',
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      handleLine.setData([
        { time: g.right_rim.time as UTCTimestamp, value: g.right_rim.price },
        { time: g.handle_low.time as UTCTimestamp, value: g.handle_low.price },
      ]);
    }

    // Horizontal lines: breakout / target / stop
    if (signal.level !== null) {
      candleSeries.createPriceLine({
        price: signal.level,
        color: '#ffb454',
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'פריצה',
      });
    }
    if (signal.target !== null) {
      candleSeries.createPriceLine({
        price: signal.target,
        color: '#3ddc97',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: 'יעד',
      });
    }
    if (signal.stop !== null) {
      candleSeries.createPriceLine({
        price: signal.stop,
        color: '#ff6b81',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: 'סטופ',
      });
    }

    // Focus the viewport on the pattern: from a bit before left_rim to a bit after the last bar.
    const lastBar = candles[candles.length - 1]?.time;
    if (lastBar) {
      const pad = (g.right_rim.time - g.left_rim.time) * 0.15;
      const from = (g.left_rim.time - pad) as UTCTimestamp;
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

  if (!g) return null;

  return (
    <Card
      title="גרף Cup & Handle ייעודי"
      hint={`עומק גביע ${g.cup_depth_pct.toFixed(1)}% · רוחב ${g.cup_width_days} ימים · רימים תוך ${g.rim_diff_pct.toFixed(1)}%`}
    >
      <div ref={ref} style={{ width: '100%', height }} />
      <div className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <Stat label="רים שמאלי" value={fmtNum(g.left_rim.price)} color="#ffb454" />
        <Stat label="תחתית" value={fmtNum(g.bottom.price)} color="#6ea8ff" />
        <Stat label="רים ימני (פריצה)" value={fmtNum(g.right_rim.price)} color="#ffb454" />
        <Stat
          label="ידית"
          value={g.handle_low ? fmtNum(g.handle_low.price) : 'בהתהוות'}
          color="#b88cff"
        />
      </div>
      <p className="mt-4 text-xs leading-relaxed text-muted">
        {g.broke_out
          ? 'התבנית פעילה — המחיר חצה את הרים הימני. מעקב אחר אישור עם נפח גבוה.'
          : 'התבנית עדיין במצב המתנה — אישור הכניסה הוא פריצה מעל הרים הימני ('}
        {!g.broke_out && (
          <>
            <span className="ltr">{fmtNum(g.right_rim.price)}</span>).
          </>
        )}
        {signal.target !== null && signal.level !== null && (
          <>
            {' יעד מדוד מבוסס "measured move": '}
            <span className="ltr">{fmtNum(signal.target)}</span>
            {' (פוטנציאל '}
            <span className="ltr">{fmtPct(((signal.target - signal.level) / signal.level) * 100)}</span>
            {' מקו הפריצה).'}
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
