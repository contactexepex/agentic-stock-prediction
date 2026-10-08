"use client";
// Every shared component drawn once with sample values (labelled "sample"; none of it is data), so the page sessions
// see them in place and the UI harness renders the charts, the table and the controls (tests/ui/cases/shell.mjs).
import { useState } from "react";
import { CostLabels, viableLine } from "../../../../../components/blocks/costs.tsx";
import { Candles, type Candle } from "../../../../../components/charts/candles.tsx";
import { LineChart } from "../../../../../components/charts/line-chart.tsx";
import { AgreementBar, HorizonBars, RangeBar } from "../../../../../components/charts/small.tsx";
import { HorizonTabs } from "../../../../../components/ui/controls.tsx";
import { FilterChips, Pager, SearchInput } from "../../../../../components/ui/filters.tsx";
import { Card, CardHead, Delta, FamilyLabel, Kpi, KpiRow, Label, MoneyDelta, Odds, PaperTag, Quiet, SentimentSquare, StatusBadge } from "../../../../../components/ui/primitives.tsx";
import { EmptyState, ErrorState, LoadingState } from "../../../../../components/ui/states.tsx";
import { DataTable } from "../../../../../components/ui/table.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import type { Pick } from "../../../../../lib/ui/costs.ts";
import { PAPER_LABEL } from "../../../../../lib/ui/constants.ts";
import { pageSlice } from "../../../../../lib/ui/costs.ts";
import { money } from "../../../../../lib/ui/format.ts";

const SAMPLE = "sample values, not data";
const CANDLES: Candle[] = Array.from({ length: 30 }, (_, i) => {
  const base = 100 + 6 * Math.sin(i / 4) + i * 0.3;
  return { time: `2026-09-${String(i + 1).padStart(2, "0")}`, open: base, high: base + 2, low: base - 2, close: base + (i % 3 === 0 ? -1 : 1) };
});
const LINES = [{ price: 112, title: "target (sample)" }, { price: 104, title: "80% low (sample)", tone: "muted" as const, dashed: true }];
const ROWS = [
  { id: "a", name: "Alpha", value: 2.5 },
  { id: "b", name: "Beta", value: -1.2 },
  { id: "c", name: "Gamma", value: null },
];
const PICK: Pick = { horizon_days: 3, prob_up: 0.58, move_pct: 2.4, loss_pct: 2.1, costs_pct: 0.4, expected_gain_pct: 0.11, amount: 100000, candidates: [{ horizon_days: 3, your_cost_pct: 0.9, expected_gain_your_pct: -0.39, cost_viable: false }] };

export function Gallery({ market }: { market: Market }) {
  const currency = market === "us" ? "USD" : "INR";
  const [horizon, setHorizon] = useState(1);
  const [chip, setChip] = useState<"all" | "up">("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const paged = pageSlice(Array.from({ length: 23 }, (_, i) => i), page, 10);
  return (
    <>
      <section className="phead">
        <div>
          <h1>Component gallery</h1>
          <div className="sub">The shared components with {SAMPLE} · not a page of the cockpit · research only</div>
        </div>
        <div className="chips">
          <PaperTag label={PAPER_LABEL} />
        </div>
      </section>
      <KpiRow label="Sample KPIs">
        <Kpi icon="trending_up" label="Sample KPI" value="12 of 15" sub={<Label tone="success">sample</Label>} tip="A sample KPI card." />
        <Kpi icon="account_balance_wallet" tone="paper" label="Unrealised (sample)" value={<MoneyDelta currency={currency} value={3024} />} sub="before costs" />
        <Kpi icon="warning" tone="warn" label="Alerts (sample)" value="1 flagged" />
        <Kpi icon="layers" tone="info" label="Odds (sample)" value={<Odds p={0.57} />} />
      </KpiRow>
      <div className="grid even">
        <Card label="Line chart">
          <CardHead title="LineChart (sample)" help="Area and line series with nice ticks and a focusable column per x." />
          <LineChart
            label="Sample cumulative profit"
            labels={["1 Oct", "2 Oct", "5 Oct", "6 Oct"]}
            series={[{ key: "r", name: "Rule", values: [0, -1200, -3400, -9309], area: true }, { key: "a", name: "AI", values: [0, 800, -2100, -9567], area: true }, { key: "b", name: "Baselines", values: [0, 300, 900, 574.89] }]}
            formatY={(v) => money(currency, v)}
          />
        </Card>
        <Card label="Candlesticks">
          <CardHead title="Candles (sample)" help="The vendored Lightweight Charts with price lines." />
          <Candles candles={CANDLES} lines={LINES} label="Sample candlesticks" summary={`30 sample sessions; ${SAMPLE}.`} height={240} />
        </Card>
      </div>
      <div className="grid even">
        <Card label="Small charts and labels">
          <CardHead title="Cells (sample)" end={<HorizonTabs horizons={[1, 2, 3, 4, 5]} value={horizon} onChange={setHorizon} />} />
          <p>
            <RangeBar currency={currency} bands={{ lo80: 96, lo50: 98.5, hi50: 102, hi80: 104, target_price: 101 }} last={100} entry={99} />{" "}
            <HorizonBars horizons={[1, 2, 3, 4, 5]} splits={[{ buy: 12, of: 15 }, { buy: 8, of: 15 }, null, { buy: 3, of: 11 }, { buy: 5, of: 15 }]} selected={horizon} />
          </p>
          <AgreementBar byFamily={{ rule: { buy: 6, of: 8 }, baseline: { buy: 2, of: 3 }, ai: { buy: 4, of: 4 } }} of={15} subject="the sample company" />
          <p>
            <Delta value={1.2} /> <Delta value={-0.4} /> <SentimentSquare value={0.6} /> <SentimentSquare value={-0.6} /> <StatusBadge status="confirmed_primary" /> <StatusBadge status="rumour" />{" "}
            <FamilyLabel family="rule">Rule</FamilyLabel> <FamilyLabel family="ai">AI</FamilyLabel>
          </p>
          <p className="mb-chips">
            <CostLabels currency={currency} pick={PICK} />
          </p>
          <div className="note">{viableLine([PICK])}</div>
        </Card>
        <Card label="Table and controls">
          <CardHead title="DataTable (sample)" />
          <div className="toolbar" role="search">
            <SearchInput label="Filter the sample rows" value={query} onChange={setQuery} />
            <FilterChips label="Sample filter" value={chip} onChange={setChip} options={[{ value: "all", label: "All" }, { value: "up", label: "Up only" }]} />
          </div>
          <DataTable
            label="Sample table"
            rowKey={(r) => r.id}
            rows={ROWS.filter((r) => (chip === "all" || (r.value ?? 0) > 0) && r.name.toLowerCase().includes(query.toLowerCase()))}
            empty="No sample row matches the filter."
            columns={[
              { key: "name", header: "Name", sortValue: (r) => r.name, render: (r) => r.name },
              { key: "value", header: "Move", numeric: true, tip: "A sample move.", sortValue: (r) => r.value, render: (r) => <Delta value={r.value} /> },
            ]}
          />
          <Pager page={paged.page} pages={paged.pages} onPage={setPage} summary={`Page ${paged.page} of ${paged.pages} · 23 sample items`} />
        </Card>
      </div>
      <div className="grid even">
        <Card label="States">
          <CardHead title="States (sample)" />
          <Quiet>No sample row today.</Quiet>
          <div style={{ marginTop: 12 }}>
            <EmptyState title="Nothing stored yet (sample)">What is missing and why, in plain words.</EmptyState>
          </div>
          <ErrorState problem={{ title: "Data service unavailable (sample)", status: 503, fallback_links: [] }} />
        </Card>
        <Card label="Loading">
          <CardHead title="LoadingState (sample)" />
          <LoadingState label="Sample loading" cards={1} />
        </Card>
      </div>
    </>
  );
}
