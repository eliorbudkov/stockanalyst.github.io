'use client';

import { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import type { Candle, Indicators, Levels, RiskManagement } from '@/lib/types';

type Props = {
  candles: Candle[];
  indicators: Indicators;
  levels?: Levels;
  risk?: RiskManagement;
  height?: number;
};

const MA_COLORS = {
  ma20: '#6ea8ff',
  ma50: '#ffb454',
  ma150: '#b88cff',
  ma200: '#ff6b81',
} as const;

const OVERLAY_COLORS = {
  bb: 'rgba(255, 255, 255, 0.45)',
  vwap: '#00d1ff',
} as const;

export function PriceChart({ candles, indicators, levels, risk, height = 460 }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!ref.current) return;
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
    chartRef.current = chart;

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

    const volSeries = chart.addHistogramSeries({
      color: '#26305a',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });
    volSeries.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    volSeries.setData(
      candles.map((c) => ({
        time: c.time as UTCTimestamp,
        value: c.volume,
        color: c.close >= c.open ? 'rgba(61,220,151,0.35)' : 'rgba(255,107,129,0.35)',
      })),
    );

    function addMA(series: (number | null)[] | undefined, color: string) {
      if (!series || series.length === 0) return;
      const line: ISeriesApi<'Line'> = chart.addLineSeries({
        color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      const data = candles
        .map((c, i) => ({ time: c.time as UTCTimestamp, value: series[i] }))
        .filter((p): p is { time: UTCTimestamp; value: number } => typeof p.value === 'number');
      line.setData(data);
    }
    addMA(indicators.ma20_series, MA_COLORS.ma20);
    addMA(indicators.ma50_series, MA_COLORS.ma50);
    addMA(indicators.ma150_series, MA_COLORS.ma150);
    addMA(indicators.ma200_series, MA_COLORS.ma200);

    function addOverlay(series: (number | null)[] | undefined, color: string, lineWidth: 1 | 2 = 1) {
      if (!series || series.length === 0) return;
      const line: ISeriesApi<'Line'> = chart.addLineSeries({
        color,
        lineWidth,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      const data = candles
        .map((c, i) => ({ time: c.time as UTCTimestamp, value: series[i] }))
        .filter((p): p is { time: UTCTimestamp; value: number } => typeof p.value === 'number');
      line.setData(data);
    }
    addOverlay(indicators.bb_upper_series, OVERLAY_COLORS.bb);
    addOverlay(indicators.bb_middle_series, 'rgba(255, 255, 255, 0.25)');
    addOverlay(indicators.bb_lower_series, OVERLAY_COLORS.bb);
    addOverlay(indicators.vwap_series, OVERLAY_COLORS.vwap, 2);

    if (levels?.resistance) {
      candleSeries.createPriceLine({
        price: levels.resistance.price,
        color: '#ff6b81',
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'Resistance',
      });
    }
    if (levels?.support) {
      candleSeries.createPriceLine({
        price: levels.support.price,
        color: '#3ddc97',
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'Support',
      });
    }

    let riskLines: ReturnType<typeof candleSeries.createPriceLine>[] = [];
    const renderRiskLines = (values: { entry: number; stop: number; tp1: number; tp2: number }) => {
      riskLines.forEach((line) => candleSeries.removePriceLine(line));
      riskLines = [
        candleSeries.createPriceLine({
          price: values.entry,
          color: '#6ea8ff',
          lineWidth: 2,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: 'Entry',
        }),
        candleSeries.createPriceLine({
          price: values.stop,
          color: '#ff4d4d',
          lineWidth: 2,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: 'Stop',
        }),
        candleSeries.createPriceLine({
          price: values.tp1,
          color: '#7ed957',
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: 'TP1',
        }),
        candleSeries.createPriceLine({
          price: values.tp2,
          color: '#3ddc97',
          lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: 'TP2',
        }),
      ];
    };

    if (risk?.entry_price && risk.stop_loss && risk.take_profit_1 && risk.take_profit_2) {
      renderRiskLines({
        entry: risk.entry_price,
        stop: risk.stop_loss.price,
        tp1: risk.take_profit_1.price,
        tp2: risk.take_profit_2.price,
      });
    }

    const onRiskPlan = (event: Event) => {
      const detail = (event as CustomEvent<{ entry: number; stop: number; tp1: number; tp2: number }>).detail;
      if (detail) renderRiskLines(detail);
    };
    window.addEventListener('stock-analyst:risk-plan', onRiskPlan);

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth });
    });
    ro.observe(ref.current);

    return () => {
      window.removeEventListener('stock-analyst:risk-plan', onRiskPlan);
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, indicators, levels, risk, height]);

  return (
    <div>
      <div ref={ref} style={{ width: '100%', height }} />
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted">
        <Legend color={MA_COLORS.ma20} label="MA 20" />
        <Legend color={MA_COLORS.ma50} label="MA 50" />
        <Legend color={MA_COLORS.ma150} label="MA 150" />
        <Legend color={MA_COLORS.ma200} label="MA 200" />
        <Legend color={OVERLAY_COLORS.bb} label="Bollinger" />
        <Legend color={OVERLAY_COLORS.vwap} label="VWAP 20" />
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-block h-2 w-4 rounded" style={{ background: color }} />
      <span>{label}</span>
    </span>
  );
}
