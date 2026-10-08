// TypeScript shapes of the shared page blocks of contract 2.0 (api/openapi.yaml components: PageHeader,
// HorizonChoice, StatusBlock, GoLive, StrategyEntry, CompanyRecord, AgreementRow, OpenTrade, Problem; B4's
// warehouse/rm_common.py). Each page session types its own page payload as `PageBase & {...}`.
import type { Market } from "../data/constants.ts";
import type { Family } from "./constants.ts";

export type IsoDate = string;
export type IsoTime = string;

export interface Envelope<P> {
  market: Market | "_all";
  page_key: string;
  as_of: IsoDate | null;
  cutoff: IsoTime;
  built_at: IsoTime;
  schema_version: string;
  source_commit: string;
  payload_sha256: string;
  payload: P;
}

export interface Problem {
  type?: string;
  title: string;
  status: number;
  detail?: string;
  fallback_links?: string[];
}

export interface Freshness {
  state: "fresh" | "stale" | "unknown";
  built_at: IsoTime | null;
  age_minutes: number | null;
}

export interface SessionStatus {
  local_time: string;
  trading_day: boolean;
  session_date: IsoDate;
  previous_session: IsoDate;
  calendar_covered: boolean;
  session_open_utc: IsoTime;
  session_close_utc: IsoTime;
  in_session: boolean;
  late_run: boolean;
}

export interface LevelBlock {
  symbol: string;
  name: string;
  close: number | null;
  close_date: IsoDate;
  change_pct: number | null;
  change_5d_pct: number | null;
}

export interface RunMark {
  at: IsoTime | null;
  ok: boolean | null;
  next_at?: IsoTime | null;
  new_items?: number | null;
}

export interface Runs {
  pre_open: RunMark;
  intraday: RunMark[];
  post_close: RunMark;
  news: RunMark;
}

export interface StatusBlock {
  market: Market;
  name: string;
  currency: "INR" | "USD";
  as_of: IsoDate | null;
  session: SessionStatus;
  regime: string | null;
  benchmark: LevelBlock | null;
  vol_index: LevelBlock | null;
  runs: Runs;
  paper_label: string;
  freshness?: Freshness;
}

/** PageHeader + HorizonChoice + the status block: what every 2.0 page payload starts with. */
export interface PageBase {
  market: Market;
  name: string;
  currency: "INR" | "USD";
  as_of: IsoDate | null;
  cutoff?: IsoTime;
  built_at?: IsoTime;
  status: StatusBlock;
  horizons?: number[];
  default_horizon?: number | "all";
}

export interface GoLive {
  proven: boolean;
  months_forward: number;
  trades_needed: number;
  beats_best_baseline: boolean | null;
}

export interface StrategyEntry {
  id: string;
  family: Family;
  name: string;
  description?: string;
  compared_to?: string | null;
  differs_in?: string | null;
  parameters?: Record<string, unknown>;
  threshold?: number | null;
  horizons?: number[];
  live_from?: IsoDate | null;
  live?: boolean;
  settled_trades?: number;
}

export type StrategyMap = Record<string, StrategyEntry>;

export interface BuySplit {
  buy: number;
  of: number;
}

export interface CompanyRecord {
  market: Market;
  ticker: string;
  name: string;
  exchange?: string | null;
  sector?: string | null;
  state: "active" | "inactive";
  state_since?: IsoTime | null;
  added_at?: IsoTime | null;
  amount?: number | null;
  amount_overridden?: boolean;
  currency?: "INR" | "USD";
  yahoo?: string | null;
  nse_symbol?: string | null;
  cik?: string | null;
  last_close?: number | null;
  last_close_date?: IsoDate | null;
  change_pct?: number | null;
  agreement_n1?: BuySplit | null;
  open_trades?: number;
}

export interface AgreementRow {
  market: Market;
  as_of_date: IsoDate | null;
  session_date: IsoDate | null;
  rank: number;
  ticker: string;
  name: string;
  horizon_days: number;
  buy: number;
  of: number;
  by_family: Record<Family, BuySplit>;
  avg_prob_up: number | null;
  label: string;
  paper: true;
}

/** Horizon k as text ("1".."5") -> its rows by rank. */
export type AgreementMap = Record<string, AgreementRow[]>;

export interface OpenTrade {
  trade_id: string;
  view: "accuracy" | "head_to_head";
  prediction_id: string;
  strategy_id: string;
  family: Family;
  market: Market;
  ticker: string;
  horizon_days: number;
  entry_date: IsoDate;
  exit_date: IsoDate;
  entry_price: number;
  quantity: number;
  amount: number;
  currency: "INR" | "USD";
  target_price?: number | null;
  lo80?: number | null;
  lo50?: number | null;
  hi50?: number | null;
  hi80?: number | null;
  last_price: number;
  last_price_date: IsoDate;
  unrealised_pnl: number;
  unrealised_pct: number;
  to_target_pct?: number | null;
  paper: true;
}

/** The ranges a range bar draws (an open trade's or a prediction's). */
export interface RangeBands {
  lo80: number;
  lo50: number;
  hi50: number;
  hi80: number;
  target_price: number;
}

/** An intraday check of one open paper trade (catalogue entity Trade check, B9's trade_checks); the fields the
 *  shared open-trades table reads. */
export interface TradeCheck {
  trade_id: string;
  check_at: IsoTime;
  session_number?: number;
  last_price: number;
  ret_since_entry_pct: number | null;
  band: string;
  flags: string[];
  flagged: boolean;
}
