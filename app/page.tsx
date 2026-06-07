import { StockSearch } from '@/components/StockSearch';
import { Watchlist } from '@/components/Watchlist';
import { FearGreedGauge } from '@/components/FearGreedGauge';
import { MarketHeatmap } from '@/components/MarketHeatmap';
import { DailyScanner } from '@/components/DailyScanner';
import { GlobalLiquidityChart } from '@/components/GlobalLiquidityChart';
import { TrumpHoldingsWidget } from '@/components/TrumpHoldingsWidget';

export default function HomePage() {
  return (
    <div className="space-y-4 sm:space-y-6">
      <StockSearch />

      <DailyScanner />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <FearGreedGauge />
        </div>
        <div>
          <Watchlist />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <GlobalLiquidityChart />
        </div>
        <div>
          <TrumpHoldingsWidget />
        </div>
      </div>

      <MarketHeatmap />
    </div>
  );
}
