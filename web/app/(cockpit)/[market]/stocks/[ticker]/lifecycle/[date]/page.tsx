// A company's call history for one session (B15; no mockup, built from 03-company's parts): the server component
// keeps the metadata; the page is the client component reading GET .../stocks/{ticker}/lifecycle/{date}.
import type { Metadata } from "next";
import type { Market } from "../../../../../../../lib/data/constants.ts";
import { LifecyclePage } from "./_parts/lifecycle-page.tsx";

export async function generateMetadata({ params }: { params: Promise<{ ticker: string; date: string }> }): Promise<Metadata> {
  const { ticker, date } = await params;
  return { title: `${decodeURIComponent(ticker)} · calls for ${decodeURIComponent(date)}` };
}

export default async function Page({ params }: { params: Promise<{ market: string; ticker: string; date: string }> }) {
  const { market, ticker, date } = await params;
  return <LifecyclePage market={market as Market} ticker={decodeURIComponent(ticker)} date={decodeURIComponent(date)} />;
}
