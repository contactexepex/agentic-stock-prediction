// Stock strategies (design/mockups/04-stock-strategies/): B15. The server component keeps the metadata; the page is
// the client component reading GET /api/v1/markets/{market}/stocks/{ticker}/strategies.
import type { Metadata } from "next";
import type { Market } from "../../../../../../lib/data/constants.ts";
import { StockStrategiesPage } from "./_parts/strategies-page.tsx";

export async function generateMetadata({ params }: { params: Promise<{ ticker: string }> }): Promise<Metadata> {
  return { title: `${decodeURIComponent((await params).ticker)} · Stock strategies` };
}

export default async function Page({ params }: { params: Promise<{ market: string; ticker: string }> }) {
  const { market, ticker } = await params;
  return <StockStrategiesPage market={market as Market} ticker={decodeURIComponent(ticker)} />;
}
