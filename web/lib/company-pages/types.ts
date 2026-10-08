// The company pages' payloads as this UI reads them (api/schemas/company.yaml: CompanyPage, StockStrategiesPage,
// LifecyclePage). The shared blocks come from lib/ui/types.ts (B7); the rest are the 03/04 mockups' fields. Stored
// measures may be null (a missing bar, a trade not entered), so numbers are nullable where the schema says so.
import type { Family } from "../ui/constants.ts";
import type { Pick, PickCandidate } from "../ui/costs.ts";
import type {
  AgreementMap, CompanyRecord, GoLive, IsoDate, IsoTime, OpenTrade, PageBase, StrategyMap, TradeCheck as SharedCheck,
} from "../ui/types.ts";

export type { Family };
export type { AgreementRow, OpenTrade } from "../ui/types.ts";

export interface Bar { date: IsoDate; open: number; high: number; low: number; close: number; volume: number | null; adjusted?: boolean }

export interface Prediction {
  id: string; strategy_id: string; family: Family; ticker: string; made_at: IsoTime; as_of_date: IsoDate;
  session_date: IsoDate; exit_date: IsoDate; horizon_days: number; direction: "up" | "down"; prob_up: number | null;
  qualifies: boolean; base_close?: number | null; target_price: number | null; lo50: number | null; hi50: number | null;
  lo80: number | null; hi80: number | null; range_widen?: number | null; threshold?: number | null; confidence?: number | null;
  model_prob?: number | null; agent_adjustment?: number | null; adjustment_reason?: string | null; reason?: string | null;
  evidence_ids?: string[] | null; regime?: string | null; quality?: string | null;
}

export interface TradeCheck extends SharedCheck {
  id?: string; check_id?: string; prediction_id?: string; strategy_id?: string; view?: string; horizon_days?: number;
  session_date?: IsoDate; entry_price?: number | null; target_price?: number | null; to_target_pct?: number | null;
  high_since_entry_pct?: number | null; low_since_entry_pct?: number | null; target_reached?: boolean | null;
  target_reached_session?: number | null; sessions_left?: number | null;
}

export interface SettledTrade {
  id: string; trade_id: string; prediction_id: string; strategy_id: string; family: Family; view: string;
  pick_rule: string | null; horizon_days: number; made_at?: IsoTime; entry_date: IsoDate; exit_date: IsoDate;
  exit_date_actual: IsoDate | null; status: string; flags: string[] | null; amount: number | null; currency?: string;
  entry_price: number | null; exit_price: number | null; quantity: number | null; gross_pnl: number | null;
  costs: number | null; net_pnl: number | null; return_pct: number | null; prob_up: number | null;
  target_price: number | null; range_hit: boolean | null; target_reached: boolean | null;
  target_reached_session: number | null; max_favourable_pct: number | null; max_adverse_pct: number | null;
  move_pct: number | null; market_pct: number | null; sector_pct: number | null; news_pct: number | null;
  company_pct: number | null; reason_code: string | null; reason_codes: string[] | null;
  reason_detail?: { benchmark?: string | null; benchmark_pct?: number | null; beta?: number | null; sector_source?: string | null; note?: string | null } | null;
  settled_at?: IsoTime;
}

export interface AiReason {
  id: string; trade_id: string | null; strategy_id: string | null; session_date: IsoDate; kind: string;
  rank: number | null; text: string; cited_ids: string[]; created_at?: IsoTime;
}

export interface NewsItem {
  id: string; title: string; source: string | null; url: string | null; published_at: IsoTime | null;
  first_seen_at: IsoTime; status: string | null; independent_origins: number | null; primary_ids: string[] | null;
  enrichment: { event_type?: string | null; materiality?: string | null; sentiment?: number | null; priced_in?: boolean | null } | null;
  headline_history: Array<{ title: string; seen_at: IsoTime }> | null;
}

export interface ResultsDigest {
  id: string; fiscal_label: string | null; release_date: IsoDate | null; release_timing: string | null;
  period_end: IsoDate | null; basis: string | null; currency: string | null; status: string; numbers_as_of: IsoTime | null;
  numbers: Record<string, number | null | undefined> & { derived?: unknown };
  consensus: { eps_estimate?: number | null; eps_reported?: number | null; surprise_pct?: number | null } | null;
  reaction: { from: IsoDate; to: IsoDate; stock_pct: number | null; benchmark_pct: number | null; excess_pct: number | null } | null;
  bullets: Array<{ topic?: string; text?: string; quote?: string }> | null;
  sources: Array<{ id: string; kind: string; doc?: string | null; url?: string | null }> | null;
}

export interface CalendarEvent {
  date: IsoDate; type: string; name: string; ticker: string | null; timing: string | null;
  reaction_sessions: IsoDate[] | null; major: boolean | null; provisional: boolean | null; release?: string | null;
}

export interface LifecycleEvent {
  id: string; event: string; effective_from: IsoTime; recorded_at: IsoTime; amount: number | null;
  reason: string | null; requested_by: string | null; channel: string; supersedes?: string | null;
}

export interface PickCandidateRow extends PickCandidate {
  prediction_id?: string | null; prob_up?: number | null; move_pct?: number | null; loss_pct?: number | null;
  costs_pct?: number | null; expected_gain_pct?: number | null; gain_per_session_pct?: number | null; eligible?: boolean | null;
}

export interface HeadToHeadPick extends Pick {
  id: string; family: Family; pick_rule: string; status: string; strategy_id: string | null;
  strongest_basis: string | null; prediction_id: string | null; session_date?: IsoDate;
  ranking?: Array<{ strategy_id: string; rank: number; basis?: string; settled_trades: number; net_pnl: number }>;
  candidates?: PickCandidateRow[];
}

export interface ScoreRow {
  strategy_id: string | null; horizon_days: number | "all"; trades: number; net_pnl: number | null; mean_return_pct?: number | null;
  win_rate?: number | null; avg_target_error_pct?: number | null; sample_badge?: string | null;
  luck_test?: {
    method: string; n: number; m?: number | null; low_pct: number | null; high_pct: number | null;
    corrected_low_pct?: number | null; corrected_high_pct?: number | null; corrected?: boolean | null;
  } | null;
}

export interface CompanyPayload extends PageBase {
  horizons: number[]; default_horizon: number | "all"; reference_strategy: string; go_live: GoLive | null;
  strategies: StrategyMap; companies: CompanyRecord[]; ticker: string; company: CompanyRecord;
  lifecycle: LifecycleEvent[]; agreement: AgreementMap; head_to_head: HeadToHeadPick[]; predictions: Prediction[];
  open_trades: OpenTrade[]; trade_checks: TradeCheck[]; settled: SettledTrade[]; reasons: AiReason[];
  news: NewsItem[]; results: ResultsDigest[]; events: CalendarEvent[]; bars: Bar[]; on_company: ScoreRow[];
}

export interface StockStrategiesPayload extends PageBase {
  horizons: number[]; default_horizon: number | "all"; ticker: string; company: CompanyRecord; agreement: AgreementMap;
  head_to_head: HeadToHeadPick[]; predictions: Prediction[]; on_company: ScoreRow[]; overall: ScoreRow[];
  go_live: GoLive | null; strategies: StrategyMap;
}

export interface LifecyclePayload {
  market: string; ticker: string; session_date: IsoDate; predictions: Prediction[]; head_to_head: HeadToHeadPick[];
  trade_checks: TradeCheck[]; settled: SettledTrade[]; reasons: AiReason[];
}
