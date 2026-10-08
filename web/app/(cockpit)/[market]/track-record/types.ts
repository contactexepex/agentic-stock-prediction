// The Track record payload as the page reads it (api/schemas/track-record.yaml TrackRecordPage; B13's rm.track_record).
// Only the fields the page uses; the route serves more.

export interface Scores {
  n: number;
  brier: number | null;
  log_loss: number | null;
  brier_skill: number | null;
}

export interface ReliabilityBand {
  bin: string;
  lo: number;
  hi: number;
  n: number;
  mean_conf: number | null;
  hit_rate: number | null;
  wilson_lo: number | null;
  wilson_hi: number | null;
}

export interface CallBlock {
  n: number;
  hits: number;
  share: number | null;
  wilson_lo: number | null;
  wilson_hi: number | null;
  always_up: number | null;
  edge: number | null;
  mean_confidence: number | null;
  scores: Scores;
  reliability: ReliabilityBand[];
  h?: number;
  horizon_label?: string;
  name?: string;
}

export interface CallBasisBlock {
  basis: string;
  key: string;
  label: string;
  all: CallBlock;
  by_horizon: Record<string, CallBlock>;
}

export interface ShareInterval {
  share: number | null;
  wilson_lo: number | null;
  wilson_hi: number | null;
}

export interface RangeBlock {
  key?: string;
  name?: string;
  n: number;
  hit50?: ShareInterval | null;
  hit80?: ShareInterval | null;
}

export interface BacktestScore {
  key: string;
  n: number;
  dates: number;
  brier: number;
  brier_base_rate: number;
  brier_skill: number;
  auc: number;
  auc95: [number, number];
  skill: boolean;
}

export interface BacktestStrategyRow {
  key: string;
  threshold: string | number;
  positions: number;
  baseline: string;
  dates: number;
  mean_pct: number | null;
  ci95_pct: [number, number] | null;
  verdict: string;
}

export interface BacktestView {
  computed_at: string;
  verdict: string;
  json: string;
  data: {
    panel_rows: number;
    first_bar: string;
    first_panel_date: string;
    last_panel_date: string;
    tickers: number;
    round_trip_cost_pct_at_100: number;
  };
  scores: BacktestScore[];
  strategy: BacktestStrategyRow[];
  reliability: Record<string, unknown> | unknown[] | null;
}

export interface SkillStatus {
  state: string;
  label: string;
  why: string;
  rule: string;
  review: { id: string; computed_at: string } | null;
}

export interface WeeklyCallBlock {
  week: string;
  n: number;
  hits: number;
  share: number | null;
  wilson_lo: number | null;
  wilson_hi: number | null;
  brier: number | null;
  log_loss: number | null;
}

export interface WeeklyCallSeries {
  basis: string;
  key: string;
  label: string;
  weeks: WeeklyCallBlock[];
}

export interface TrackRecordPayload {
  market: string;
  name: string;
  currency: string;
  as_of: string | null;
  track: {
    market: string;
    as_of: string | null;
    skill: SkillStatus;
    calls: CallBasisBlock[];
    ranges: RangeBlock[];
    replay: unknown;
    min_sample: number;
    backtest: BacktestView | null;
    example_parts: string[];
  };
  weekly?: WeeklyCallSeries[];
}
