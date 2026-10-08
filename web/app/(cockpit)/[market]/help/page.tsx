// Help (design/mockups/12-help/): owned by B7, who replaces this placeholder.
import type { Metadata } from "next";
import { PagePending } from "../../../../components/shell/page-pending.tsx";
import type { Market } from "../../../../lib/data/constants.ts";

export const metadata: Metadata = { title: "Help" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  const market = (await params).market as Market;
  return <PagePending market={market} pageKey="help" />;
}
