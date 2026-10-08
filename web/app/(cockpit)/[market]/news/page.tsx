// Page 09, News (design/mockups/09-news/; B14): the server part keeps the metadata, the client part reads the endpoint.
import type { Metadata } from "next";
import type { Market } from "../../../../lib/data/constants.ts";
import { NewsPage } from "./_parts/news-page.tsx";

export const metadata: Metadata = { title: "News" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  return <NewsPage market={(await params).market as Market} />;
}
