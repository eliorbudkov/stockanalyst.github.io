'use client';

import { useEffect, useMemo, useState } from 'react';
import type { EntryPrice, Quote, RiskManagement, StopLoss, TakeProfit, TimeframePlan } from '@/lib/types';
import { fmtNum, fmtPct } from '@/lib/format';
import { Card } from './Card';

type Direction = 'long' | 'short';

const METHOD_LABEL: Record<EntryPrice['method'], string> = {
  breakout: 'פריצה',
  vwap_pullback: 'VWAP Pullback',
  vwap_reclaim: 'VWAP Reclaim',
  sma20: 'SMA20',
  sma150: 'SMA150',
  sma200: 'SMA200',
  dcf: 'DCF',
  current: 'מחיר שוק',
  discount: 'הנחה',
  overvalued: 'Overvalued',
};

export function RiskManagementPanel({ quote, risk }: { quote: Quote; risk: RiskManagement }) {
  const swingEntry = risk.short_term_entry?.price ?? risk.entry_price ?? quote.price ?? 0;
  // When the long-term entry is blocked (DCF overvaluation), keep the
  // override-input fallback on the swing entry so the manual workflow
  // still functions, and hide the "Long-Term" quick-fill button below.
  const longEntryBlocked = risk.long_term_entry?.blocked === true;
  const longEntry = !longEntryBlocked
    ? (risk.long_term_entry?.price ?? swingEntry)
    : swingEntry;
  const [entryText, setEntryText] = useState('');
  const [direction, setDirection] = useState<Direction>('long');

  const hasOverride = entryText.trim() !== '';
  const parsedEntry = Number(entryText);
  const overrideIsValid = hasOverride && Number.isFinite(parsedEntry) && parsedEntry > 0;
  const entryPrice = overrideIsValid ? parsedEntry : swingEntry;
  const inputIsValid = !hasOverride || overrideIsValid;

  const plan = useMemo(
    () =>
      calculateRiskPlan({
        entryPrice,
        direction,
        atr14: risk.calculation_inputs.atr14,
        support: risk.calculation_inputs.support_price,
        resistance: risk.calculation_inputs.resistance_price,
      }),
    [direction, entryPrice, risk.calculation_inputs],
  );

  const stop = plan.stop!;
  const tp1 = plan.take_profit_1!;
  const tp2 = plan.take_profit_2!;

  useEffect(() => {
    window.dispatchEvent(new CustomEvent('stock-analyst:risk-plan', {
      detail: {
        entry: entryPrice,
        direction,
        stop: stop.price,
        tp1: tp1.price,
        tp2: tp2.price,
      },
    }));
  }, [direction, entryPrice, stop.price, tp1.price, tp2.price]);

  return (
    <Card title="ניהול סיכון" hint="כל החישובים מעוגנים למחיר הכניסה הקובע">
      <div className="grid gap-4 sm:grid-cols-2">
        <RecommendedEntryCard
          timeframe="טווח קצר / Swing"
          entry={risk.short_term_entry}
          fallbackPrice={swingEntry}
          active={!overrideIsValid}
        />
        <RecommendedEntryCard
          timeframe="טווח ארוך"
          entry={risk.long_term_entry}
          fallbackPrice={longEntry}
        />
      </div>

      <div className="mt-4 grid gap-4 border-b border-border pb-5 lg:grid-cols-[1fr_auto]">
        <div className="rounded-lg border border-border p-4">
          <label htmlFor="custom-entry" className="mb-1.5 block text-xs text-muted">
            מחיר כניסה ידני (Override)
          </label>
          <div className="flex gap-2">
            <input
              id="custom-entry"
              type="number"
              min="0.01"
              step="0.01"
              value={entryText}
              placeholder={swingEntry.toFixed(2)}
              onChange={(event) => setEntryText(event.target.value)}
              className="ltr min-w-0 flex-1 rounded-md border border-border bg-panel2 px-3 py-2 text-base font-semibold outline-none focus:border-accent"
              aria-invalid={!inputIsValid}
            />
            <PresetButton label="נקה" onClick={() => setEntryText('')} />
            {!longEntryBlocked && (
              <PresetButton label="Long-Term" onClick={() => setEntryText(String(longEntry))} />
            )}
          </div>
          {!inputIsValid && <p className="mt-1 text-xs text-bad">יש להזין מחיר חיובי.</p>}
          {overrideIsValid && <p className="mt-1 text-xs font-medium text-warn">Override ידני פעיל</p>}
          <p className="mt-1 text-xs text-muted">
            מחיר שוק נוכחי: <span className="ltr">{fmtNum(quote.price)}</span>. הוא מוצג להשוואה בלבד ואינו משמש בחישוב.
          </p>
        </div>

        <div>
          <div className="mb-1.5 text-xs text-muted">כיוון העסקה</div>
          <div className="flex rounded-md border border-border bg-panel2 p-1">
            <DirectionButton active={direction === 'long'} label="Long" onClick={() => setDirection('long')} />
            <DirectionButton active={direction === 'short'} label="Short" onClick={() => setDirection('short')} />
          </div>
        </div>
      </div>

      {/* Swing trades are intentionally discretionary — no auto stop/TP.
          Stop/TP appear only when the user opts in via the Override input
          (e.g. enters a custom entry price, or clicks Long-Term preset). */}
      {overrideIsValid ? (
        <>
          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric
              label="כניסה קובעת"
              value={entryPrice}
              color="text-accent"
              detail="Override ידני"
            />
            <Metric
              label="Stop Loss"
              value={stop.price}
              color="text-bad"
              detail={`${fmtPct(stop.distance_pct)} · סיכון $${stop.risk_per_share.toFixed(2)}`}
            />
            <Metric
              label="TP1"
              value={tp1.price}
              color="text-good"
              detail={`${fmtPct(tp1.distance_pct)} · R:R 1:${tp1.rr.toFixed(2)}`}
            />
            <Metric
              label="TP2"
              value={tp2.price}
              color="text-good"
              detail={`${fmtPct(tp2.distance_pct)} · R:R 1:${tp2.rr.toFixed(2)}`}
            />
          </div>
          <RiskLadder
            entry={entryPrice}
            direction={direction}
            stop={stop.price}
            tp1={tp1.price}
            tp2={tp2.price}
          />
        </>
      ) : (
        <div className="mt-5 rounded-lg border border-border bg-panel2/40 p-4">
          <div className="flex items-start gap-3">
            <div className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent/20 text-xs font-bold text-accent">
              ℹ
            </div>
            <div className="flex-1 text-sm leading-relaxed">
              <p className="font-semibold text-text">
                ניהול סיכון לסווינג — שיקול דעת
              </p>
              <p className="mt-1 text-xs text-muted">
                סווינג טריידינג אינו עובד עם stop ו-TP קבועים מראש. הזן מחיר
                כניסה ידני (Override) בשדה למעלה, או בחר ב-Long-Term, כדי לקבל
                stop/TP מחושב לפי המחיר שבחרת.
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="mt-5 rounded-md border border-border bg-panel2/60 p-3 text-xs text-muted">
        <p>{stop.reason}</p>
        <p className="mt-1">
          בדיקת תקינות: {direction === 'long' ? 'Stop < Entry < TP1 ≤ TP2' : 'Stop > Entry > TP1 ≥ TP2'}.
        </p>
        {plan.notes.map((note) => <p key={note} className="mt-1">{note}</p>)}
      </div>
    </Card>
  );
}

function RecommendedEntryCard({
  timeframe,
  entry,
  fallbackPrice,
  active = false,
}: {
  timeframe: string;
  entry: EntryPrice | null;
  fallbackPrice: number;
  active?: boolean;
}) {
  // DCF sanity-check block: the long-term entry was suppressed because the
  // market price is ≥ 20% above DCF fair value. Show a warning card instead
  // of any price — short-term card is unaffected and renders normally.
  if (entry?.blocked) {
    return (
      <div className="rounded-lg border border-bad/40 bg-bad/10 p-4">
        <div className="mb-2 flex items-center justify-between gap-3">
          <div className="text-xs font-semibold text-bad">{timeframe}</div>
          <span className="rounded border border-bad/40 bg-panel px-2 py-1 text-[11px] font-semibold text-bad">
            Overvalued
          </span>
        </div>
        <div className="text-base font-bold text-bad">
          תמחור יתר (Overvalued) – לא מתאים לאסטרטגיית ערך
        </div>
        {entry.reason && <p className="mt-2 text-xs leading-5 text-bad/80">{entry.reason}</p>}
        {entry.fair_value !== null && entry.fair_value !== undefined && (
          <div className="mt-3 rounded border border-bad/30 bg-bg/40 p-2 text-[11px] text-muted">
            <span className="text-bad/80">שווי הוגן (DCF, לפני מרווח ביטחון): </span>
            <span className="ltr font-bold text-bad">${entry.fair_value.toFixed(2)}</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`rounded-lg border p-4 ${active ? 'border-accent/40 bg-accent/10' : 'border-border bg-panel2/40'}`}>
      <div className="mb-3 text-xs font-semibold text-muted">{timeframe}</div>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs text-muted">מחיר כניסה מומלץ</div>
          <div className="ltr mt-1 text-2xl font-bold text-accent">{fmtNum(entry?.price ?? fallbackPrice)}</div>
        </div>
        <span className="rounded border border-accent/40 bg-panel px-2 py-1 text-[11px] text-accent">
          {entry ? METHOD_LABEL[entry.method] : 'אלגוריתם'}
        </span>
      </div>
      {entry?.reason && <p className="mt-2 text-xs leading-5 text-muted">{entry.reason}</p>}
      {active && <p className="mt-2 text-xs font-medium text-good">עוגן פעיל לחישוב</p>}
    </div>
  );
}

function calculateRiskPlan({
  entryPrice,
  direction,
  atr14,
  support,
  resistance,
}: {
  entryPrice: number;
  direction: Direction;
  atr14: number | null;
  support: number | null;
  resistance: number | null;
}): TimeframePlan {
  const atr = atr14 && atr14 > 0 ? atr14 : null;
  let stopPrice: number;
  let stopReason: string;
  let riskPerShare: number;
  let tp1Price: number;
  let tp2Price: number;

  if (direction === 'long') {
    const atrStop = atr ? entryPrice - 2 * atr : entryPrice * 0.95;
    const structuralStop = atr && support && support < entryPrice ? support - 0.5 * atr : null;
    const candidates = [atrStop, structuralStop].filter(
      (value): value is number => value !== null && value > 0 && value < entryPrice,
    );
    stopPrice = candidates.length ? Math.max(...candidates) : entryPrice * 0.95;
    stopReason = structuralStop !== null && stopPrice === structuralStop
      ? 'סטופ מבני מתחת לתמיכה עם מרווח חצי ATR'
      : 'סטופ תנודתיות 2×ATR מתחת למחיר הכניסה';
    if (stopPrice >= entryPrice) stopPrice = entryPrice * 0.95;
    riskPerShare = entryPrice - stopPrice;
    const target2R = entryPrice + 2 * riskPerShare;
    const target3R = entryPrice + 3 * riskPerShare;
    const validResistance = resistance && resistance > entryPrice ? resistance : null;
    tp1Price = validResistance ? Math.min(target2R, validResistance) : target2R;
    tp2Price = validResistance && validResistance > tp1Price * 1.005 ? validResistance : target3R;
  } else {
    const atrStop = atr ? entryPrice + 2 * atr : entryPrice * 1.05;
    const structuralStop = atr && resistance && resistance > entryPrice ? resistance + 0.5 * atr : null;
    const candidates = [atrStop, structuralStop].filter(
      (value): value is number => value !== null && value > entryPrice,
    );
    stopPrice = candidates.length ? Math.min(...candidates) : entryPrice * 1.05;
    stopReason = structuralStop !== null && stopPrice === structuralStop
      ? 'סטופ מבני מעל ההתנגדות עם מרווח חצי ATR'
      : 'סטופ תנודתיות 2×ATR מעל מחיר הכניסה';
    if (stopPrice <= entryPrice) stopPrice = entryPrice * 1.05;
    riskPerShare = stopPrice - entryPrice;
    const priceFloor = entryPrice * 0.01;
    const target2R = Math.max(entryPrice - 2 * riskPerShare, priceFloor);
    const target3R = Math.max(entryPrice - 3 * riskPerShare, priceFloor);
    const validSupport = support && support > 0 && support < entryPrice ? support : null;
    tp1Price = validSupport ? Math.max(target2R, validSupport) : target2R;
    tp2Price = validSupport && validSupport < tp1Price * 0.995 ? validSupport : target3R;
  }

  const distance = (level: number) => ((level - entryPrice) / entryPrice) * 100;
  const reward = (level: number) => direction === 'long' ? level - entryPrice : entryPrice - level;
  const stop: StopLoss = {
    price: round4(stopPrice),
    distance_pct: round2(distance(stopPrice)),
    risk_per_share: round4(riskPerShare),
    reason: stopReason,
  };
  const takeProfit1: TakeProfit = {
    price: round4(tp1Price),
    distance_pct: round2(distance(tp1Price)),
    rr: round2(reward(tp1Price) / riskPerShare),
    reason: 'יעד חלקי',
  };
  const takeProfit2: TakeProfit = {
    price: round4(tp2Price),
    distance_pct: round2(distance(tp2Price)),
    rr: round2(reward(tp2Price) / riskPerShare),
    reason: 'יעד מלא',
  };

  const valid = direction === 'long'
    ? stop.price < entryPrice && entryPrice < takeProfit1.price && takeProfit1.price <= takeProfit2.price
    : stop.price > entryPrice && entryPrice > takeProfit1.price && takeProfit1.price >= takeProfit2.price;
  if (!valid) throw new Error('Risk plan sanity check failed');

  return {
    entry_price: entryPrice,
    direction,
    stop,
    take_profit_1: takeProfit1,
    take_profit_2: takeProfit2,
    notes: [`כל הרמות חושבו מחדש מעוגן כניסה $${entryPrice.toFixed(2)}`],
  };
}

function Metric({ label, value, color, detail }: { label: string; value: number; color: string; detail: string }) {
  return (
    <div className="rounded-lg border border-border bg-panel2/60 p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={`ltr mt-1 text-2xl font-bold ${color}`}>{fmtNum(value)}</div>
      <div className="ltr mt-1 text-[11px] text-muted">{detail}</div>
    </div>
  );
}

function PresetButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="rounded-md border border-border px-3 text-xs text-muted hover:border-accent hover:text-accent">{label}</button>;
}

function DirectionButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`min-w-16 rounded px-3 py-1.5 text-xs font-semibold ${active ? 'bg-accent text-bg' : 'text-muted'}`}
    >
      {label}
    </button>
  );
}

function RiskLadder({ entry, direction, stop, tp1, tp2 }: { entry: number; direction: Direction; stop: number; tp1: number; tp2: number }) {
  const values = [stop, entry, tp1, tp2];
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const pos = (value: number) => `${((value - low) / span) * 100}%`;
  // On very narrow screens (<480px) the absolute-positioned markers collide.
  // We render a horizontal bar for sm+ screens and fall back to a stacked
  // list on mobile.
  return (
    <>
      {/* Mobile: stacked list of the four levels */}
      <ul className="mt-6 grid grid-cols-2 gap-2 sm:hidden">
        <RungRow color="#ff6b81" label="Stop" value={stop} />
        <RungRow color="#6ea8ff" label="Entry" value={entry} />
        <RungRow color="#7ed957" label="TP1" value={tp1} />
        <RungRow color="#3ddc97" label="TP2" value={tp2} />
      </ul>
      {/* Tablet/desktop: horizontal ladder */}
      <div className="mt-10 hidden px-6 pb-10 sm:block">
        <div className={`relative h-2 rounded-full ${direction === 'long' ? 'bg-gradient-to-r' : 'bg-gradient-to-l'} from-bad via-accent to-good`}>
          <Marker label="Stop" value={stop} position={pos(stop)} color="#ff6b81" />
          <Marker label="Entry" value={entry} position={pos(entry)} color="#6ea8ff" />
          <Marker label="TP1" value={tp1} position={pos(tp1)} color="#7ed957" />
          <Marker label="TP2" value={tp2} position={pos(tp2)} color="#3ddc97" />
        </div>
      </div>
    </>
  );
}

function RungRow({ color, label, value }: { color: string; label: string; value: number }) {
  return (
    <li className="rounded-md border border-border bg-panel2/60 p-2 text-center">
      <div className="text-[10px] text-muted" style={{ color }}>{label}</div>
      <div className="ltr mt-0.5 text-sm font-bold" style={{ color }}>{fmtNum(value)}</div>
    </li>
  );
}

function Marker({ label, value, position, color }: { label: string; value: number; position: string; color: string }) {
  return (
    <div className="absolute top-3 -translate-x-1/2 text-center" style={{ left: position }}>
      <div className="mx-auto h-3 w-0.5" style={{ background: color }} />
      <div className="ltr text-[11px] font-semibold" style={{ color }}>{fmtNum(value)}</div>
      <div className="text-[10px] text-muted">{label}</div>
    </div>
  );
}

const round2 = (value: number) => Math.round(value * 100) / 100;
const round4 = (value: number) => Math.round(value * 10_000) / 10_000;
