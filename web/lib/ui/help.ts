// The data of the Help page (12-help, B7). The page is static text; the few catalogue values it shows come from two
// existing reads, exactly as the mockup selects them (design/mockups/12-help/notes.md): from the Strategy lab
// payload the strategy registry, the reference strategy and its go-live row (accuracy view, forward basis, all
// horizons, scope strategy: the your-cost go-live detail); from the Companies payload the market's default amount and
// the first active company by ticker with its N+1 agreement (the example). Pure; tested in tests/help.test.ts.
import type { Family } from "./constants.ts";
import type { BuySplit, GoLive, PageBase, StrategyMap } from "./types.ts";

export interface GoLiveDetail extends GoLive {
  best_baseline_net_pnl?: number | null;
  drawdown_limit?: number | null;
  drawdown_within_limit?: boolean | null;
  holds_in_calm_and_volatile?: boolean | null;
  cost_view?: string;
}

/** The fields of the Strategy lab payload (api/schemas/strategy-lab.yaml) Help reads. */
export interface LabForHelp extends PageBase {
  reference_strategy: string;
  go_live: GoLive;
  strategies: StrategyMap;
  rows: {
    strategy_id: string;
    scope: string;
    view: string;
    basis: string;
    horizon_days: number | "all" | null;
    pick_rule?: string | null;
    regime?: string | null;
    ticker?: string | null;
    go_live?: GoLiveDetail | null;
  }[];
}

/** The fields of the Companies payload (api/schemas/companies.yaml) Help reads. */
export interface CompaniesForHelp extends PageBase {
  default_amount: number | null;
  companies: { ticker: string; name: string; state: string; agreement_n1?: BuySplit | null }[];
}

/** The reference strategy's go-live detail: its accuracy, forward, all-horizons row of scope strategy. */
export function referenceGoLive(lab: LabForHelp): GoLiveDetail | null {
  const row = lab.rows.find(
    (r) =>
      r.strategy_id === lab.reference_strategy && r.scope === "strategy" && r.view === "accuracy" && r.basis === "forward" &&
      r.horizon_days === "all" && !r.pick_rule && !r.regime && !r.ticker && r.go_live,
  );
  return row?.go_live ?? null;
}

/** The five checks of the go-live bar (SPEC F7.2) from the detail: [passed (null = not decidable yet), key]. */
export function goLiveChecks(g: GoLiveDetail, goLiveMonths: number): { key: string; passed: boolean | null }[] {
  return [
    { key: "trades", passed: g.trades_needed === 0 },
    { key: "months", passed: g.months_forward >= goLiveMonths },
    { key: "baseline", passed: g.beats_best_baseline },
    { key: "drawdown", passed: g.drawdown_within_limit ?? null },
    { key: "regimes", passed: g.holds_in_calm_and_volatile ?? null },
  ];
}

/** The agreement example: the first active company by ticker that has an N+1 agreement count. */
export function agreementExample(companies: CompaniesForHelp): { ticker: string; name: string; agreement_n1: BuySplit } | null {
  const active = companies.companies
    .filter((c) => c.state === "active" && c.agreement_n1)
    .sort((a, b) => (a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : 0));
  const first = active[0];
  return first ? { ticker: first.ticker, name: first.name, agreement_n1: first.agreement_n1 as BuySplit } : null;
}

/** The horizons the AI traders predict (the union of their registry horizons). */
export function aiHorizons(strategies: StrategyMap): number[] {
  const all = Object.values(strategies).filter((s) => s.family === ("ai" as Family)).flatMap((s) => s.horizons ?? []);
  return [...new Set(all)].sort((a, b) => a - b);
}
