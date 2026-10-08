// Page 12, Help (design/mockups/12-help/), owned by B7: how to read the cockpit.
import type { Metadata } from "next";
import type { Market } from "../../../../lib/data/constants.ts";
import { HelpPage } from "./_parts/help-page.tsx";

export const metadata: Metadata = { title: "Help" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  return <HelpPage market={(await params).market as Market} />;
}
