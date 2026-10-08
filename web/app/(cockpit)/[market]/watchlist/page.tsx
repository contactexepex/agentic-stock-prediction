// Page 02, Watchlist (design/mockups/02-watchlist/; B14): the server part keeps the metadata, the client part reads
// the endpoint.
import type { Metadata } from "next";
import type { Market } from "../../../../lib/data/constants.ts";
import { WatchlistPage } from "./_parts/watchlist-page.tsx";

export const metadata: Metadata = { title: "Watchlist" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  return <WatchlistPage market={(await params).market as Market} />;
}
