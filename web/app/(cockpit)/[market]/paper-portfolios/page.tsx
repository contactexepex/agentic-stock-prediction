// Page 07, Paper portfolios (design/mockups/07-paper-portfolios/), owned by B16: the server component sets the title
// and renders the client page, which reads GET /api/v1/markets/{market}/portfolios and posts the add-trade form to
// POST /api/v1/markets/{market}/paper-trades. A paper trade is a record, never an order.
import type { Metadata } from "next";
import type { Market } from "../../../../lib/data/constants.ts";
import { PaperPortfoliosPage } from "./_parts/paper-portfolios-page.tsx";

export const metadata: Metadata = { title: "Paper portfolios" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  return <PaperPortfoliosPage market={(await params).market as Market} />;
}
