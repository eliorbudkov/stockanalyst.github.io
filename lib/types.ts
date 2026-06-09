export type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type Quote = {
  symbol: string;
  name: string | null;
  currency: string | null;
  price: number | null;
  prev_close: number | null;
  change_pct: number | null;
  market_cap: number | null;
  pe: number | null;
  pb: number | null;
  dividend_yield: number | null;
  beta: number | null;
  sector: string | null;
  industry: string | null;
  description?: string | null;
  description_he?: string | null;
  website?: string | null;
  country?: string | null;
  employees?: number | null;
};

export type Indicators = {
  ma20: number | null;
  ma50: number | null;
  ma150: number | null;
  ma200: number | null;
  rsi14: number | null;
  atr14: number | null;
  atr_pct: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  bb_upper: number | null;
  bb_middle: number | null;
  bb_lower: number | null;
  bb_width_pct: number | null;
  vwap: number | null;
  ma20_series: (number | null)[];
  ma50_series: (number | null)[];
  ma150_series: (number | null)[];
  ma200_series: (number | null)[];
  rsi_series: (number | null)[];
  macd_series: (number | null)[];
  macd_signal_series: (number | null)[];
  macd_histogram_series: (number | null)[];
  bb_upper_series: (number | null)[];
  bb_middle_series: (number | null)[];
  bb_lower_series: (number | null)[];
  vwap_series: (number | null)[];
};

export type ScoreBreakdown = {
  trend: number;
  momentum: number;
  advanced_technicals: number;
  volatility: number;
  volume: number;
  fundamentals: number;
  patterns: number;
  heatmap: number;
  behavior_sentiment: number;
};

export type Level = {
  price: number;
  touches: number;
  distance_pct: number;
};

export type Levels = {
  support: Level | null;
  resistance: Level | null;
  risk_reward: number | null;
};

export type StopLoss = {
  price: number;
  distance_pct: number;     // negative
  risk_per_share: number;
  reason: string;
};

export type TakeProfit = {
  price: number;
  distance_pct: number;     // positive
  rr: number;               // reward/risk
  reason: string;
};

export type EntryPrice = {
  price: number;
  distance_pct: number;     // pos = above current, neg = below
  method:
    | 'breakout'
    | 'vwap_pullback'
    | 'vwap_reclaim'
    | 'sma20'
    | 'sma150'
    | 'sma200'
    | 'dcf'
    | 'current'
    | 'discount'
    | 'overvalued';
  reason: string;
  blocked?: boolean;
  fair_value?: number | null;
};

export type TimeframePlan = {
  entry_price: number;
  direction: 'long' | 'short';
  stop: StopLoss | null;
  take_profit_1: TakeProfit | null;
  take_profit_2: TakeProfit | null;
  notes: string[];
};

export type RiskManagement = {
  entry_price: number;
  direction: 'long' | 'short';
  stop_loss: StopLoss | null;
  take_profit_1: TakeProfit | null;
  take_profit_2: TakeProfit | null;
  notes: string[];
  short_term_entry: EntryPrice | null;
  long_term_entry: EntryPrice | null;
  long_term_plan: TimeframePlan | null;
  calculation_inputs: {
    atr14: number | null;
    support_price: number | null;
    resistance_price: number | null;
  };
};

export type CupHandleAnchor = {
  time: number;     // unix seconds
  price: number;
};

export type CupHandleGeometry = {
  kind?: 'cup_and_handle';
  left_rim: CupHandleAnchor;
  bottom: CupHandleAnchor;
  right_rim: CupHandleAnchor;
  handle_low: CupHandleAnchor | null;
  cup_depth_pct: number;
  rim_diff_pct: number;
  cup_width_days: number;
  broke_out: boolean;
};

export type DoubleTopBottomGeometry = {
  kind: 'double_top' | 'double_bottom';
  first: CupHandleAnchor;
  second: CupHandleAnchor;
  neckline: CupHandleAnchor;
  broke: boolean;
  height_pct: number;
  similarity_pct: number;
};

export type PatternGeometry = CupHandleGeometry | DoubleTopBottomGeometry;

export type PatternSignal = {
  name: string;
  detected: boolean;
  direction: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  level: number | null;
  target: number | null;
  stop: number | null;
  explanation: string;
  geometry?: PatternGeometry;
};

export type Patterns = {
  cup_and_handle: PatternSignal;
  head_and_shoulders: PatternSignal;
  double_top: PatternSignal;
  double_bottom: PatternSignal;
  flag: PatternSignal;
  triangle: PatternSignal;
};

export type SectorStatus = {
  sector: string;
  sector_label: string;
  avg_change_pct: number;
  is_red: boolean;
  is_green: boolean;
  advancers: number;
  decliners: number;
  members: number;
};

export type MatrixCategory = {
  name: string;
  score: number;        // 0..10
  weight: number;       // 0..1
  notes: string[];
  skipped?: boolean;    // true when input data was unavailable
};

export type MatrixScore = {
  score: number;                  // 0..10 (final, after blocker)
  raw_score: number;              // pre-blocker
  blocker_applied: boolean;
  blocker_reason: string | null;
  categories: MatrixCategory[];
  rationale: string[];
  position_size_pct: number | null;
  bonus?: number;
  bonus_reasons?: string[];
};

export type GlobalLiquidity = {
  series: { date: string; value_b: number }[];
  latest_value_b: number;
  latest_date: string;
  change_4w_pct: number | null;
  change_13w_pct: number | null;
  change_52w_pct: number | null;
  trend_label: string;
  score: number;
  fetched_at: number;
  indicator: string;
  source: string;
};

export type TrumpHolding = {
  symbol: string;
  name: string;
  sector?: string;
  category: 'primary' | 'reported' | 'reported_sale';
  bonus_eligible?: boolean;
  note: string;
};

export type TrumpHoldings = {
  holdings: TrumpHolding[];
  last_filing: string;
  source: string;
  source_url: string;
  bonus_active: boolean;
  source_fresh: boolean;
  source_age_days: number;
  bonus_suspended_after: string;
  disclaimer: string;
};

export type Matrices = {
  short_term: MatrixScore;
  long_term: MatrixScore;
  rvol: number | null;
  gap_pct: number | null;
  sector_status: SectorStatus | null;
  global_liquidity: GlobalLiquidity | null;
};

export type AnalysisResult = {
  symbol: string;
  quote: Quote;
  candles: Candle[];
  indicators: Indicators;
  levels: Levels;
  risk_management: RiskManagement;
  patterns: Patterns;
  fear_greed: FearGreed | null;
  behavior_sentiment: BehaviorSentiment | null;
  matrices: Matrices;
  score: number;
  score_breakdown: ScoreBreakdown;
  rationale: string[];
};

export type WatchlistItem = {
  symbol: string;
  added_at: number;
};

export type HeatmapStock = {
  symbol: string;
  name: string;
  sector: string;
  sector_label: string;
  price: number;
  prev_close: number;
  change_pct: number;
  market_cap_b: number;
};

export type HeatmapSummary = {
  total: number;
  advancers: number;
  decliners: number;
  unchanged: number;
  avg_change_pct: number | null;
};

export type Heatmap = {
  stocks: HeatmapStock[];
  summary: HeatmapSummary;
  fetched_at: number;
};

export type ScanItem = {
  kind: 'stock' | 'etf';
  is_qualified?: boolean;
  strategy?: 'swing' | 'investment' | 'etf' | 'etf_swing' | 'etf_investment';
  strategy_label?: string;
  display_score?: number;
  display_rationale?: string[];
  symbol: string;
  name: string;
  sector: string;
  sector_status: SectorStatus | null;
  price: number;
  change_pct: number | null;
  rvol: number | null;
  gap_pct: number | null;
  momentum_sources?: Array<'day_gainers' | 'most_actives'>;
  // Stock-only fields
  short_term_score?: number;
  short_term_blocker?: boolean;
  short_term_raw?: number;
  short_term_bonus?: number;
  short_term_bonus_reasons?: string[];
  long_term_score?: number;
  overall_score?: number;
  overall_score_breakdown?: ScoreBreakdown;
  long_term_raw?: number;
  long_term_bonus?: number;
  long_term_bonus_reasons?: string[];
  swing_setup?: {
    qualified: boolean;
    checks: {
      cup_handle_stage: boolean;
      rising_structure: boolean;
      elevated_rvol: boolean;
      risk_reward: boolean;
      success_rate: boolean;
    };
    breakout_price: number | null;
    stop_price: number | null;
    target_price: number | null;
    risk_reward: number | null;
    success_rate: number;
    rvol: number | null;
    reasons: string[];
  };
  // ETF-only fields
  etf_score?: number;
  etf_matrix_score?: number;
  etf_matrix_rationale?: string[];
  etf_blocker?: boolean;
  net_inflows?: {
    shares_change_pct_30d: number;
    score: number;
    label: string;
  } | null;
  weighted_debt_equity?: {
    weighted_de: number;
    constituents: number;
    score: number;
    label: string;
  } | null;
  // Shared
  final_score: number;
  top_reasons: string[];
};

export type ScanResult = {
  top: ScanItem[];
  top_swing_stocks: ScanItem[];
  top_invest_stocks: ScanItem[];
  top_stocks: ScanItem[]; // legacy alias for top_swing_stocks
  top_etfs: ScanItem[];
  top_short_term_etfs: ScanItem[];
  top_long_term_etfs: ScanItem[];
  qualified_count: number;
  qualified_swing_count: number;
  qualified_invest_count: number;
  qualified_stocks_count: number;
  qualified_etfs_count: number;
  qualified_short_term_etfs_count: number;
  qualified_long_term_etfs_count: number;
  evaluated_count: number;
  stocks_evaluated: number;
  etfs_evaluated: number;
  universe_size: number;
  stock_universe_size: number;
  index_universe_size: number;
  momentum_universe_size: number;
  momentum_added_count: number;
  momentum_overlap_count: number;
  etf_universe_size: number;
  tier1_valid_count: number;
  swing_tier1_candidate_count?: number;
  long_term_tier1_candidate_count?: number;
  tier2_overlap_count?: number;
  tier2_candidate_count: number;
  tier2_info_calls: number;
  tier1_primary_rvol: number;
  tier1_floor_rvol: number;
  scan_duration_seconds: number;
  universe_sources: {
    sp500: number;
    nasdaq100_only: number;
    russell2000: number;
    day_gainers: number;
    most_actives: number;
  };
  threshold: number;
  swing_threshold?: number;
  swing_overall_threshold?: number;
  swing_min_rvol?: number;
  swing_min_risk_reward?: number;
  swing_min_success_rate?: number;
  long_term_overall_threshold?: number;
  minimum_final_score?: number;
  etf_threshold?: number;
  etf_short_term_threshold?: number;
  etf_short_term_overall_threshold?: number;
  etf_long_term_threshold?: number;
  etf_long_term_overall_threshold?: number;
  scan_timings?: Record<string, number>;
  etf_diagnostics?: Array<{
    symbol: string;
    score: number;
    qualified: boolean;
    blocker_applied: boolean;
    net_inflows_available: boolean;
    weighted_de_available: boolean;
    top_reasons: string[];
  }>;
  stock_diagnostics?: Array<{
    symbol: string;
    scan_paths: string[];
    rvol: number | null;
    long_term_prefilter_score: number | null;
    short_term_score: number;
    long_term_score: number;
    overall_score: number;
    swing_qualified: boolean;
    long_term_qualified: boolean;
  }>;
  swing_tier1_diagnostics?: Array<{
    symbol: string;
    rvol: number;
    qualified: boolean;
    checks: Record<string, boolean>;
    risk_reward: number | null;
    success_rate: number | null;
    breakout_price: number | null;
  }>;
  fetched_at: number;
};

export type FearGreed = {
  score: number;            // 0..100
  rating: 'extreme fear' | 'fear' | 'neutral' | 'greed' | 'extreme greed';
  label: string;            // Hebrew
  previous_close: number | null;
  previous_week: number | null;
  previous_month: number | null;
  previous_year: number | null;
  updated_at: string | null;
  fetched_at: number;       // unix seconds
};

export type BehaviorMetric = {
  value?: number | null;
  score: number | null;
  rating?: string | null;
  label?: string | null;
  source?: string;
  status: 'ok' | 'partial' | 'unavailable' | 'not_configured';
  updated_at?: string | null;
  error?: string;
};

export type SocialProvider = {
  source: string;
  status: 'ok' | 'partial' | 'unavailable' | 'not_configured';
  score: number | null;
  label: string;
  mentions: number;
  positive_terms?: number;
  negative_terms?: number;
  error?: string;
};

export type SocialSentiment = {
  score: number | null;
  label: string;
  providers: SocialProvider[];
  available_sources: string[];
  unavailable_sources: string[];
};

export type InsiderTrading = {
  score: number | null;
  label: string;
  net_shares_90d: number | null;
  net_value_90d: number | null;
  transactions_90d: number | null;
  held_percent_insiders: number | null;
  source: string;
  status: 'ok' | 'partial' | 'unavailable' | 'not_configured';
  error?: string;
};

export type ShortInterest = {
  score: number | null;
  label: string;
  short_percent_float: number | null;
  short_ratio: number | null;
  shares_short: number | null;
  shares_short_prior_month: number | null;
  notes: string[];
  source: string;
  status: 'ok' | 'partial' | 'unavailable' | 'not_configured';
};

export type BehaviorSentiment = {
  put_call_ratio: BehaviorMetric;
  vix: BehaviorMetric;
  social_sentiment: SocialSentiment;
  insider_trading: InsiderTrading;
  short_interest: ShortInterest;
  composite_score: number | null;
  label: string;
  notes: string[];
  fetched_at: number;
};
