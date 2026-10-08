// The company pages' payload fields this UI reads (api/schemas/company.yaml: CompanyPage, StockStrategiesPage). Stored
// measures may be null (a missing bar, a trade not entered), so numbers are nullable where the schema says so.
export type Family = "rule" | "baseline" | "ai";

export interface Bar { date: string; open: number; high: number; low: number; close: number; volume: number | null; adjusted?: boolean }

export interface Prediction {
  id: string; strategy_id: string; family: Family; ticker: string; made_at: string; as_of_date: string;
  session_date: string; exit_date: string; horizon_days: number; direction: "up" | "down"; prob_up: number | null;
  qualifies: boolean; base_close?: number | null; target_price: number | null; lo50: number | null; hi50: number | null;
  lo80: number | null; hi80: number | null; range_widen?: number | null; threshold?: number | null;
  model_prob?: number | null; agent_adjustment?: number | null; adjustment_reason?: string | null; reason?: string | null;
}

export interface OpenTrade {
  trade_id: string; view: string; prediction_id: string; strategy_id: string; family: Family; horizon_days: number;
  entry_date: string; exit_date: string; entry_price: number | null; target_price: number | null;
  lo80: number | null; lo50: number | null; hi50: number | null; hi80: number | null;
  last_price: number | null; last_price_date: string | null; unrealised_pnl: number | null;
  unrealised_pct: number | null; to_target_pct: number | null;
}

export interface TradeCheck {
  trade_id: string; check_at: string; session_number: number | null; last_price: number | null;
  ret_since_entry_pct: number | null; band: string | null; flags: string[]; flagged: boolean;
  high_since_entry_pct: number | null; low_since_entry_pct: number | null; target_reached: boolean | null;
  target_reached_session: number | null;
}

export interface SettledTrade {
  id: string; trade_id: string; strategy_id: string; family: Family; view: string; pick_rule: string | null;
  horizon_days: number; entry_date: string; exit_date: string; exit_date_actual: string | null; status: string;
  flags: string[]; amount: number | null; entry_price: number | null; exit_price: number | null; quantity: number | null;
  gross_pnl: number | null; costs: number | null; net_pnl: number | null; return_pct: number | null;
  prob_up: number | null; target_price: number | null; range_hit: boolean | null; target_reached: boolean | null;
  target_reached_session: number | null; max_favourable_pct: number | null; max_adverse_pct: number | null;
  move_pct: number | null; market_pct: number | null; sector_pct: number | null; news_pct: number | null;
  company_pct: number | null; reason_code: string | null; reason_codes: string[];
}

export interface CalendarEvent {
  date: string; type: string; name: string; ticker: string | null; timing: string | null;
  reaction_sessions: string[] | null; major: boolean | null; provisional: boolean | null; release?: string | null;
}

export interface AgreementRow {
  buy: number; of: number; by_family: Record<Family, { buy: number; of: number }>; avg_prob_up: number | null;
  label?: string;
}

export interface ScoreRow {
  strategy_id: string; horizon_days: number | "all"; trades: number; net_pnl: number; mean_return_pct?: number | null;
  win_rate?: number | null; avg_target_error_pct?: number | null; sample_badge?: string | null;
}
