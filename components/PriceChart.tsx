'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
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
  avp: '#6ea8ff',
  avpValueArea: 'rgba(110, 168, 255, 0.42)',
  avpOutside: 'rgba(140, 151, 194, 0.22)',
  avpPoc: '#ffb454',
} as const;

export function PriceChart({ candles, indicators, levels, risk, height = 460 }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const profileCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [manualAnchorInput, setManualAnchorInput] = useState('');

  const automaticAnchor = useMemo(
    () => findAutomaticAnchor(candles, levels?.support?.price ?? null),
    [candles, levels?.support?.price],
  );
  const manualAnchor = Number(manualAnchorInput);
  const hasManualAnchor = manualAnchorInput.trim() !== '' && Number.isFinite(manualAnchor) && manualAnchor > 0;
  const anchorPrice = hasManualAnchor ? manualAnchor : automaticAnchor.price;
  const anchorIndex = useMemo(
    () => findAnchorCandleIndex(candles, anchorPrice),
    [candles, anchorPrice],
  );
  const volumeProfile = useMemo(
    () => buildAnchoredVolumeProfile(candles, anchorIndex),
    [candles, anchorIndex],
  );

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

    if (anchorPrice) {
      candleSeries.createPriceLine({
        price: anchorPrice,
        color: OVERLAY_COLORS.avp,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'AVP Anchor',
      });
    }
    if (volumeProfile) {
      candleSeries.createPriceLine({
        price: volumeProfile.poc,
        color: OVERLAY_COLORS.avpPoc,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'AVP POC',
      });
      candleSeries.createPriceLine({
        price: volumeProfile.valueAreaHigh,
        color: OVERLAY_COLORS.avp,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: 'VAH',
      });
      candleSeries.createPriceLine({
        price: volumeProfile.valueAreaLow,
        color: OVERLAY_COLORS.avp,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: 'VAL',
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

    const drawVolumeProfile = () => {
      const canvas = profileCanvasRef.current;
      const host = ref.current;
      if (!canvas || !host || !volumeProfile) return;

      const width = host.clientWidth;
      const displayHeight = height;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(displayHeight * ratio);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${displayHeight}px`;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, width, displayHeight);

      const maxVolume = Math.max(...volumeProfile.bins.map((bin) => bin.volume), 1);
      const maxBarWidth = Math.min(width * 0.3, 250);
      const rightOffset = 72;

      for (const bin of volumeProfile.bins) {
        const top = candleSeries.priceToCoordinate(bin.high);
        const bottom = candleSeries.priceToCoordinate(bin.low);
        if (top === null || bottom === null) continue;

        const y = Math.min(top, bottom);
        const barHeight = Math.max(2, Math.abs(bottom - top) - 1);
        const barWidth = Math.max(1, (bin.volume / maxVolume) * maxBarWidth);
        const inValueArea =
          bin.mid >= volumeProfile.valueAreaLow && bin.mid <= volumeProfile.valueAreaHigh;
        const isPoc = bin.index === volumeProfile.pocIndex;

        ctx.fillStyle = isPoc
          ? OVERLAY_COLORS.avpPoc
          : inValueArea
            ? OVERLAY_COLORS.avpValueArea
            : OVERLAY_COLORS.avpOutside;
        ctx.fillRect(width - rightOffset - barWidth, y, barWidth, barHeight);
      }
    };

    requestAnimationFrame(drawVolumeProfile);

    const ro = new ResizeObserver(() => {
      if (ref.current) {
        chart.applyOptions({ width: ref.current.clientWidth });
        requestAnimationFrame(drawVolumeProfile);
      }
    });
    ro.observe(ref.current);
    chart.timeScale().subscribeVisibleLogicalRangeChange(drawVolumeProfile);

    return () => {
      window.removeEventListener('stock-analyst:risk-plan', onRiskPlan);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(drawVolumeProfile);
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, indicators, levels, risk, height, anchorPrice, volumeProfile]);

  return (
    <div>
      <div className="relative" style={{ height }}>
        <div ref={ref} style={{ width: '100%', height }} />
        <canvas
          ref={profileCanvasRef}
          className="pointer-events-none absolute inset-0 z-10"
          aria-hidden="true"
        />
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-3 rounded-md border border-border bg-panel2/60 p-3">
        <div className="min-w-[180px]">
          <div className="text-[11px] text-muted">מחיר עיגון AVP אוטומטי</div>
          <div className="ltr mt-0.5 font-semibold text-accent">
            ${automaticAnchor.price?.toFixed(2) ?? '—'}
          </div>
          <div className="text-[10px] text-muted">{automaticAnchor.reason}</div>
        </div>
        <label className="min-w-[170px] flex-1">
          <span className="mb-1 block text-[11px] text-muted">מחיר עיגון ידני (Override)</span>
          <input
            type="number"
            min="0"
            step="0.01"
            inputMode="decimal"
            value={manualAnchorInput}
            onChange={(event) => setManualAnchorInput(event.target.value)}
            placeholder={automaticAnchor.price?.toFixed(2) ?? 'הזן מחיר'}
            className="ltr h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-text outline-none transition focus:border-accent"
          />
        </label>
        <button
          type="button"
          onClick={() => setManualAnchorInput('')}
          disabled={!hasManualAnchor}
          className="h-9 rounded-md border border-border bg-bg px-3 text-xs font-semibold text-muted transition hover:border-accent hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
        >
          חזרה לאוטומטי
        </button>
        {volumeProfile && (
          <div className="ltr flex gap-3 text-[10px] text-muted">
            <span>POC <strong className="text-warn">${volumeProfile.poc.toFixed(2)}</strong></span>
            <span>VAH <strong className="text-accent">${volumeProfile.valueAreaHigh.toFixed(2)}</strong></span>
            <span>VAL <strong className="text-accent">${volumeProfile.valueAreaLow.toFixed(2)}</strong></span>
          </div>
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted">
        <Legend color={MA_COLORS.ma20} label="MA 20" />
        <Legend color={MA_COLORS.ma50} label="MA 50" />
        <Legend color={MA_COLORS.ma150} label="MA 150" />
        <Legend color={MA_COLORS.ma200} label="MA 200" />
        <Legend color={OVERLAY_COLORS.bb} label="Bollinger" />
        <Legend color={OVERLAY_COLORS.vwap} label="VWAP 20" />
        <Legend color={OVERLAY_COLORS.avpValueArea} label="AVP Value Area" />
        <Legend color={OVERLAY_COLORS.avpPoc} label="AVP POC" />
      </div>
    </div>
  );
}

type AutomaticAnchor = {
  price: number | null;
  reason: string;
};

type VolumeProfileBin = {
  index: number;
  low: number;
  high: number;
  mid: number;
  volume: number;
};

type AnchoredVolumeProfile = {
  bins: VolumeProfileBin[];
  poc: number;
  pocIndex: number;
  valueAreaHigh: number;
  valueAreaLow: number;
};

function findAutomaticAnchor(candles: Candle[], supportPrice: number | null): AutomaticAnchor {
  if (supportPrice && Number.isFinite(supportPrice) && supportPrice > 0) {
    return { price: supportPrice, reason: 'מבוסס על אזור התמיכה המרכזי' };
  }
  if (candles.length === 0) return { price: null, reason: 'אין מספיק נתוני מחיר' };

  const start = Math.max(2, candles.length - 90);
  for (let index = candles.length - 3; index >= start; index -= 1) {
    const candle = candles[index];
    if (
      candle.low <= candles[index - 1].low &&
      candle.low <= candles[index - 2].low &&
      candle.low <= candles[index + 1].low &&
      candle.low <= candles[index + 2].low
    ) {
      return { price: candle.low, reason: 'מבוסס על שפל Swing אחרון' };
    }
  }

  const recent = candles.slice(-60);
  const lowest = recent.reduce((best, candle) => (candle.low < best.low ? candle : best));
  return { price: lowest.low, reason: 'מבוסס על השפל הנמוך ב־60 הנרות האחרונים' };
}

function findAnchorCandleIndex(candles: Candle[], anchorPrice: number | null): number {
  if (candles.length === 0 || !anchorPrice) return 0;
  const start = Math.max(0, candles.length - 180);

  for (let index = candles.length - 1; index >= start; index -= 1) {
    const candle = candles[index];
    if (anchorPrice >= candle.low && anchorPrice <= candle.high) return index;
  }

  let closestIndex = start;
  let closestDistance = Number.POSITIVE_INFINITY;
  for (let index = start; index < candles.length; index += 1) {
    const candle = candles[index];
    const typicalPrice = (candle.high + candle.low + candle.close) / 3;
    const distance = Math.abs(typicalPrice - anchorPrice);
    if (distance < closestDistance) {
      closestDistance = distance;
      closestIndex = index;
    }
  }
  return closestIndex;
}

function buildAnchoredVolumeProfile(
  candles: Candle[],
  anchorIndex: number,
  binCount = 28,
): AnchoredVolumeProfile | null {
  const source = candles.slice(Math.max(0, anchorIndex));
  if (source.length === 0) return null;

  const minPrice = Math.min(...source.map((candle) => candle.low));
  const maxPrice = Math.max(...source.map((candle) => candle.high));
  const range = maxPrice - minPrice;
  if (!Number.isFinite(range) || range <= 0) return null;

  const binSize = range / binCount;
  const volumes = Array.from({ length: binCount }, () => 0);

  for (const candle of source) {
    const firstBin = Math.max(0, Math.floor((candle.low - minPrice) / binSize));
    const lastBin = Math.min(binCount - 1, Math.floor((candle.high - minPrice) / binSize));
    const touchedBins = Math.max(1, lastBin - firstBin + 1);
    const allocatedVolume = candle.volume / touchedBins;
    for (let bin = firstBin; bin <= lastBin; bin += 1) volumes[bin] += allocatedVolume;
  }

  const bins = volumes.map((volume, index) => {
    const low = minPrice + index * binSize;
    const high = index === binCount - 1 ? maxPrice : low + binSize;
    return { index, low, high, mid: (low + high) / 2, volume };
  });
  const pocIndex = volumes.reduce(
    (best, volume, index) => (volume > volumes[best] ? index : best),
    0,
  );

  const targetVolume = volumes.reduce((sum, volume) => sum + volume, 0) * 0.7;
  let includedVolume = volumes[pocIndex];
  let lowIndex = pocIndex;
  let highIndex = pocIndex;
  while (includedVolume < targetVolume && (lowIndex > 0 || highIndex < binCount - 1)) {
    const lowerVolume = lowIndex > 0 ? volumes[lowIndex - 1] : -1;
    const upperVolume = highIndex < binCount - 1 ? volumes[highIndex + 1] : -1;
    if (upperVolume >= lowerVolume && highIndex < binCount - 1) {
      highIndex += 1;
      includedVolume += volumes[highIndex];
    } else if (lowIndex > 0) {
      lowIndex -= 1;
      includedVolume += volumes[lowIndex];
    }
  }

  return {
    bins,
    poc: bins[pocIndex].mid,
    pocIndex,
    valueAreaHigh: bins[highIndex].high,
    valueAreaLow: bins[lowIndex].low,
  };
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-block h-2 w-4 rounded" style={{ background: color }} />
      <span>{label}</span>
    </span>
  );
}
