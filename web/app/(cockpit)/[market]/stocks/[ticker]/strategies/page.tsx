// Stock strategies (design/mockups/04-stock-strategies/): owned by B15, who replaces this placeholder.
import type { Metadata } from "next";
import { PagePending } from "../../../../../../components/shell/page-pending.tsx";
import type { Market } from "../../../../../../lib/data/constants.ts";

export const metadata: Metadata = { title: "Stock strategies" };

export default async function Page({ params }: { params: Promise<{ market: string; ticker: string }> }) {
  const market = (await params).market as Market;
  const ticker = decodeURIComponent((await params).ticker);
  return <PagePending market={market} pageKey="strategies" ticker={ticker} />;
}
