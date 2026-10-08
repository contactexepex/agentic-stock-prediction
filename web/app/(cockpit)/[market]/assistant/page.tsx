// Assistant (design/mockups/11-assistant/): owned by B8, who replaces this placeholder.
import type { Metadata } from "next";
import { PagePending } from "../../../../components/shell/page-pending.tsx";
import type { Market } from "../../../../lib/data/constants.ts";

export const metadata: Metadata = { title: "Assistant" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  const market = (await params).market as Market;
  return <PagePending market={market} pageKey="assistant" />;
}
