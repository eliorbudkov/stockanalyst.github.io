'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { api } from '@/lib/api';
import type { AnalysisResult } from '@/lib/types';
import { QuoteHeader } from '@/components/QuoteHeader';
import { PriceChart } from '@/components/PriceChart';
import { IndicatorPanel } from '@/components/IndicatorPanel';
import { TechnicalExtensionsPanel } from '@/components/TechnicalExtensionsPanel';
import { FundamentalsPanel } from '@/components/FundamentalsPanel';
import { LevelsPanel } from '@/components/LevelsPanel';
import { RiskManagementPanel } from '@/components/RiskManagementPanel';
import { PatternsPanel } from '@/components/PatternsPanel';
import { CupHandleChart } from '@/components/CupHandleChart';
import { DoubleTopBottomChart } from '@/components/DoubleTopBottomChart';
import { DualMatrixPanel } from '@/components/DualMatrixPanel';
import { CompanyDescriptionPanel } from '@/components/CompanyDescriptionPanel';
import { BehaviorSentimentPanel } from '@/components/BehaviorSentimentPanel';
import { ScoreDisplay } from '@/components/ScoreDisplay';
import { Card } from '@/components/Card';

// Client-rendered so the shared password (held only in the browser) can be sent
// straight to the backend. A server render would have to hold the secret itself,
// which the security model forbids.
export default function StockPage() {
  const params = useParams<{ symbol: string }>();
  const raw = Array.isArray(params.symbol) ? params.symbol[0] : params.symbol;
  const sym = decodeURIComponent(raw ?? '').toUpperCase();

  const [data, setData] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);

    (async () => {
      try {
        const res = await api.analyze(sym, '2y');
        // Integrity gate: if the server response is for a *different* symbol
        // (cache mismatch, race, manual override, etc.), refuse to render rather
        // than show fundamentals of one ticker next to technicals of another.
        const returnedSymbol = res?.symbol?.toUpperCase();
        const quoteSymbol = res?.quote?.symbol?.toUpperCase();
        if (returnedSymbol !== sym || quoteSymbol !== sym) {
          if (!cancelled) {
            setError(
              `סתירת סימולים: ביקשנו ${sym} אך השרת החזיר ${returnedSymbol ?? '?'} / ${quoteSymbol ?? '?'}`,
            );
          }
          return;
        }
        if (!cancelled) setData(res);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'שגיאה בלתי ידועה');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [sym]);

  if (loading) {
    return (
      <Card title={`טוען ניתוח — ${sym}`}>
        <div className="grid h-44 place-items-center text-sm text-muted">טוען…</div>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card title={`שגיאה — ${sym}`}>
        <p className="mb-3 text-sm text-bad">לא הצלחנו לטעון את הניתוח עבור הסימול הזה.</p>
        <pre className="ltr overflow-x-auto rounded-lg bg-panel2 p-3 text-xs text-muted">
          {error}
        </pre>
        <div className="mt-3 text-xs text-muted">
          ודא שה-backend של Python רץ ב-{process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}
          {' '}ושהסימול תקין (לדוגמה AAPL, NVDA, SPY).
        </div>
      </Card>
    );
  }

  // State-leak fix: a single key tied to the active ticker forces React to
  // unmount the entire subtree on ticker change. Without this, components
  // that hold internal state (lightweight-charts refs in PriceChart /
  // CupHandleChart / DoubleTopBottomChart, useState in
  // CompanyDescriptionPanel, etc.) get re-used across symbols and can show
  // stale data — exactly the "short-term stuck on previous ticker" symptom.
  //
  // The data itself is consistent (single fetch, single object), so the
  // bug was purely on the React reconciliation side. `key={sym}` is the
  // structural guarantee that no client-side state leaks across tickers.
  return (
    <div key={sym} data-symbol={sym} className="space-y-4 sm:space-y-6">
      <QuoteHeader key={`hdr-${sym}`} quote={data.quote} />

      <CompanyDescriptionPanel key={`about-${sym}`} quote={data.quote} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="גרף מחיר" hint="נרות יומיים · תמיכה/התנגדות מקווקו · סטופ ויעדים מנוקדים">
            <PriceChart
              key={`chart-${sym}`}
              candles={data.candles}
              indicators={data.indicators}
              levels={data.levels}
              risk={data.risk_management}
            />
          </Card>
        </div>
        <div>
          <ScoreDisplay
            key={`score-${sym}`}
            score={data.score}
            breakdown={data.score_breakdown}
            rationale={data.rationale}
            sectorStatus={data.matrices.sector_status}
          />
        </div>
      </div>

      <DualMatrixPanel key={`matrices-${sym}`} matrices={data.matrices} />

      <LevelsPanel key={`levels-${sym}`} quote={data.quote} levels={data.levels} />

      <RiskManagementPanel key={`risk-${sym}`} quote={data.quote} risk={data.risk_management} />

      <BehaviorSentimentPanel key={`behavior-${sym}`} data={data.behavior_sentiment} />

      <PatternsPanel key={`patterns-${sym}`} patterns={data.patterns} />

      {data.patterns.cup_and_handle.detected && data.patterns.cup_and_handle.geometry && (
        <CupHandleChart
          key={`cup-${sym}`}
          candles={data.candles}
          signal={data.patterns.cup_and_handle}
        />
      )}

      {data.patterns.double_top.detected && data.patterns.double_top.geometry && (
        <DoubleTopBottomChart
          key={`dt-${sym}`}
          candles={data.candles}
          signal={data.patterns.double_top}
        />
      )}

      {data.patterns.double_bottom.detected && data.patterns.double_bottom.geometry && (
        <DoubleTopBottomChart
          key={`db-${sym}`}
          candles={data.candles}
          signal={data.patterns.double_bottom}
        />
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <IndicatorPanel key={`ind-${sym}`} quote={data.quote} indicators={data.indicators} />
        <TechnicalExtensionsPanel
          key={`techext-${sym}`}
          quote={data.quote}
          indicators={data.indicators}
        />
        <FundamentalsPanel key={`fund-${sym}`} quote={data.quote} />
      </div>
    </div>
  );
}
