"use client";
// The shell's status bar (the sidebar's foot, the mockups' sideFoot): the market's Paper label, its data date and the
// freshness of its status page, read from GET /api/v1/markets/{market}/status. A failed read says so; the pages keep
// working, since each page carries its own status block.
import type { Market } from "../../lib/data/constants.ts";
import { MARKET_LABEL, PAPER_LABEL } from "../../lib/ui/constants.ts";
import { fmtDate } from "../../lib/ui/format.ts";
import type { StatusBlock } from "../../lib/ui/types.ts";
import { usePage } from "../../lib/ui/use-api.ts";

export function StatusBar({ market }: { market: Market }) {
  const res = usePage<StatusBlock>(market, "status");
  const status = res.state === "ready" ? res.envelope.payload : null;
  const fr = status?.freshness;
  return (
    <div className="mb-sidebar-foot" id="side-foot" role="status" aria-live="polite">
      <b>{status?.paper_label || PAPER_LABEL}</b>
      <br />
      {MARKET_LABEL[market]}
      {" · "}
      {res.state === "loading" ? "reading the status…" : res.state === "error" ? "status not available" : `data as of ${fmtDate(status?.as_of, false)}`}
      {fr && fr.state !== "fresh" ? <span className="mb-foot-stale"> · {fr.state}</span> : null}
    </div>
  );
}
