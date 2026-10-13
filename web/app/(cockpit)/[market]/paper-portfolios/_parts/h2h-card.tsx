"use client";
// The Rule vs AI scoreboard (B16's head-to-head portfolios, moved unchanged into its own file by UX3): per side and per
// pick rule, profit after the selected costs, won share, drawdown and the luck test. Paper only.
import { Avatar, Card, CardHead, GoLink, Label, MoneyDelta, PaperTag, Quiet } from "../../../../../components/ui/primitives.tsx";
import { FAMILY, MIN_TRADES_TO_RANK, PAPER_LABEL, PICK_RULE } from "../../../../../lib/ui/constants.ts";
import { noneFinishedYet, tooEarly } from "../../../../../lib/ui/empty.ts";
import { DASH, money, moneyDecimals, pct } from "../../../../../lib/ui/format.ts";
import { figure, tooFewToRank, type CostView } from "../../../../../lib/strategy-pages/scoreboard.ts";
import { familyH2hRow, pickRuleRow, type PaperPortfoliosPayload } from "../../../../../lib/strategy-pages/paper-portfolios.ts";
import { pagePath } from "../../../../../lib/ui/routes.ts";
import type { PageBase } from "../../../../../lib/ui/types.ts";
import { LuckBar } from "../../_b16/parts.tsx";

type Payload = PageBase & PaperPortfoliosPayload;
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function H2hCard({ p, cost }: { p: Payload; cost: CostView }) {
  const cur = p.currency, d = moneyDecimals(cur);
  return (
    <Card label="Rule vs AI scoreboard">
      <CardHead title={<>Rule vs AI scoreboard after fees <PaperTag label={p.status.paper_label || PAPER_LABEL} /></>} end={<GoLink href={pagePath(p.market, "compare")}>Rule vs AI</GoLink>}
        help="The portfolios of the daily rule-vs-AI picks: per side (the strongest rule strategy and the strongest AI trader) and per pick rule (best expected gain, highest probability). Each pick is one paper trade of the company’s amount. Profit after the selected costs; the luck test says whether a lead could be chance." />
      <div className="h2h">
        {(["rule", "ai"] as const).map((f) => {
          const fr = familyH2hRow(p.h2h_rows, f);
          return (
            <div key={f} className="fbox">
              <div className="fh"><Avatar icon={FAMILY[f][1]} tone={f === "ai" ? "info" : ""} size="sm" /><b>{FAMILY[f][0]}</b><small>{fr ? `· ${p.strategies[fr.strategy_id]?.name ?? fr.strategy_id}` : "· nothing settled yet"}</small></div>
              {!fr ? <Quiet>{noneFinishedYet([], p.status.runs.post_close?.next_at, p.market, p.status.session.local_time, "rule-vs-AI trade of this side")}</Quiet> : (
                <>
                  <div className="tot">
                    <span className="n"><MoneyDelta currency={cur} value={figure(fr, "net_pnl", cost)} decimals={d} /></span>
                    {tooFewToRank(fr) ? <Label tone="neutral" tip={`Fewer than ${MIN_TRADES_TO_RANK} finished trades: a handful of trades is mostly luck.`}>{tooEarly(fr.trades)}</Label> : null}
                    <small>{`after ${cost} cost on ${plural(fr.trades, "trade")} · ${pct(figure(fr, "win_rate", cost))} won · drawdown ${money(cur, figure(fr, "max_drawdown", cost), d, true)}`}</small>
                    <LuckBar row={fr} cost={cost} span={72} />
                  </div>
                  {(["best_expected_gain", "highest_probability"] as const).map((k) => {
                    const r = pickRuleRow(p.h2h_rows, f, k);
                    return (
                      <div key={k} className="pr">
                        <span className="l">{PICK_RULE[k]}</span>
                        {r ? (
                          <span className="st">
                            <span>{plural(r.trades, "trade")}</span><span>{`${pct(figure(r, "win_rate", cost))} won`}</span>
                            {tooFewToRank(r) ? <span className="mb-label neutral" style={{ fontSize: 10.5, padding: "0 5px" }}>{tooEarly(r.trades)}</span> : null}
                            <LuckBar row={r} cost={cost} span={72} />
                          </span>
                        ) : <span className="st muted">no trade yet</span>}
                        {r ? <b><MoneyDelta currency={cur} value={figure(r, "net_pnl", cost)} decimals={d} /></b> : <b className="muted">{DASH}</b>}
                      </div>
                    );
                  })}
                </>
              )}
            </div>
          );
        })}
      </div>
      <p className="note">{`Ranked after market fees; your fees also count your broker’s extra charges. ${p.status.paper_label || PAPER_LABEL}: a paper trade is a record, never an order.`}</p>
    </Card>
  );
}

