// Page 11, Assistant (design/mockups/11-assistant/; SPEC F11), owned by B8.
import type { Metadata } from "next";
import type { Market } from "../../../../lib/data/constants.ts";
import { AssistantPage } from "./_parts/assistant-page.tsx";

export const metadata: Metadata = { title: "Assistant" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  return <AssistantPage market={(await params).market as Market} />;
}
