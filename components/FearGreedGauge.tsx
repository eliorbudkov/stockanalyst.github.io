'use client';

import { useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { FearGreed } from '@/lib/types';
import { Card } from './Card';

const REFRESH_MS = 5 * 60 * 1000; // 5 minutes — index updates daily, but feel "live"

function colorFor(score: number): string {
  if (score <= 24) return '#ff4d4d';   // extreme fear
  if (score <= 44) return '#ff8c42';   // fear
  if (score <= 55) return '#ffd166';   // neutral
  if (score <= 74) return '#7ed957';   // greed
  return '#3ddc97';                    // extreme greed
}

function timeAgo(unixSec: number): string {
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - unixSec));
  if (diff < 60) return `לפני ${diff} שניות`;
  if (diff < 3600) return `לפני ${Math.floor(diff / 60)} דקות`;
  if (diff < 86400) return `לפני ${Math.floor(diff / 3600)} שעות`;
  return `לפני ${Math.floor(diff / 86400)} ימים`;
}

export function FearGreedGauge() {
  const [data, setData] = useState<FearGreed | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0); // forces re-render for the "time ago" label
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  async function load(force = false) {
    try {
      setError(null);
      if (!data) setLoading(true);
      const fg = await api.fearGreed(force);
      setData(fg);
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

  // tick reference to satisfy lint (used purely to re-render time-ago)
  void tick;

  return (
    <Card
      title="מדד הפחד והחמדנות (CNN)"
      hint={data ? timeAgo(data.fetched_at) : ''}
    >
      {error && !data && (
        <div className="text-sm text-bad">לא הצלחנו לקבל את המדד: {error}</div>
      )}
      {loading && !data && (
        <div className="grid h-44 place-items-center text-sm text-muted">טוען…</div>
      )}
      {data && (
        <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center">
          <Gauge score={data.score} />
          <div className="flex-1 space-y-2">
            <div>
              <div className="text-xs text-muted">מצב נוכחי</div>
              <div
                className="text-2xl font-bold"
                style={{ color: colorFor(data.score) }}
              >
                {data.label}
              </div>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
              <CompareRow label="סגירה קודמת" current={data.score} other={data.previous_close} />
              <CompareRow label="לפני שבוע" current={data.score} other={data.previous_week} />
              <CompareRow label="לפני חודש" current={data.score} other={data.previous_month} />
              <CompareRow label="לפני שנה" current={data.score} other={data.previous_year} />
            </dl>
            <button
              onClick={() => load(true)}
              className="mt-2 text-xs text-accent hover:underline"
            >
              רענן עכשיו
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}

function CompareRow({
  label, current, other,
}: { label: string; current: number; other: number | null }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="ltr font-semibold">
        {other === null ? '—' : (
          <span>
            {other.toFixed(0)}
            <span
              className="ms-2 text-[10px]"
              style={{ color: current >= other ? '#3ddc97' : '#ff6b81' }}
            >
              {current >= other ? '▲' : '▼'} {Math.abs(current - other).toFixed(0)}
            </span>
          </span>
        )}
      </dd>
    </>
  );
}

function Gauge({ score }: { score: number }) {
  const s = Math.max(0, Math.min(100, score));
  // Semicircle: angle from 180° (left, score 0) to 0° (right, score 100)
  const angle = 180 - (s / 100) * 180;
  const cx = 110;
  const cy = 110;
  const r = 90;
  const rad = (angle * Math.PI) / 180;
  const needleX = cx + r * 0.85 * Math.cos(rad);
  const needleY = cy - r * 0.85 * Math.sin(rad);

  const arcPath = (start: number, end: number) => {
    const sx = cx + r * Math.cos((start * Math.PI) / 180);
    const sy = cy - r * Math.sin((start * Math.PI) / 180);
    const ex = cx + r * Math.cos((end * Math.PI) / 180);
    const ey = cy - r * Math.sin((end * Math.PI) / 180);
    const largeArc = Math.abs(end - start) > 180 ? 1 : 0;
    return `M ${sx} ${sy} A ${r} ${r} 0 ${largeArc} 0 ${ex} ${ey}`;
  };

  // 5 colored segments matching the thresholds
  const segments = [
    { from: 180, to: 144, color: '#ff4d4d' }, // 0-20 extreme fear
    { from: 144, to: 108, color: '#ff8c42' }, // 20-40 fear
    { from: 108, to: 72,  color: '#ffd166' }, // 40-60 neutral
    { from: 72,  to: 36,  color: '#7ed957' }, // 60-80 greed
    { from: 36,  to: 0,   color: '#3ddc97' }, // 80-100 extreme greed
  ];

  return (
    <svg viewBox="0 0 220 140" className="h-auto w-full max-w-[220px]">
      {segments.map((seg, i) => (
        <path
          key={i}
          d={arcPath(seg.from, seg.to)}
          stroke={seg.color}
          strokeWidth="18"
          fill="none"
          strokeLinecap="butt"
          opacity="0.85"
        />
      ))}
      {/* Needle */}
      <line
        x1={cx}
        y1={cy}
        x2={needleX}
        y2={needleY}
        stroke="#e7ecff"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <circle cx={cx} cy={cy} r="6" fill="#e7ecff" />
      {/* Score in center */}
      <text
        x={cx}
        y={cy + 32}
        textAnchor="middle"
        fontSize="28"
        fontWeight="bold"
        fill={colorFor(s)}
      >
        {s.toFixed(0)}
      </text>
      <text x={cx} y={cy + 50} textAnchor="middle" fontSize="10" fill="#8c97c2">
        / 100
      </text>
    </svg>
  );
}
