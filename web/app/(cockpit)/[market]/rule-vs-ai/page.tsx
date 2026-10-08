// Page 06, Rule vs AI (design/mockups/06-rule-vs-ai/), owned by B16: the server component sets the title and renders
// the client page, which reads GET /api/v1/markets/{market}/compare and /review.
import type { Metadata } from "next";
import type { Market } from "../../../../lib/data/constants.ts";
import { RuleVsAiPage } from "./_parts/rule-vs-ai-page.tsx";

export const metadata: Metadata = { title: "Rule vs AI" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  return <RuleVsAiPage market={(await params).market as Market} />;
}
