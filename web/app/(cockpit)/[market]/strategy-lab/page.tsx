// Page 05, Strategy lab (design/mockups/05-strategy-lab/), owned by B16: the server component sets the title and
// renders the client page, which reads GET /api/v1/markets/{market}/strategies.
import type { Metadata } from "next";
import type { Market } from "../../../../lib/data/constants.ts";
import { StrategyLabPage } from "./_parts/strategy-lab-page.tsx";

export const metadata: Metadata = { title: "Strategy lab" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  return <StrategyLabPage market={(await params).market as Market} />;
}
