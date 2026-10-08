// The chat panel slot (parallel route @chat), owned by B8 (F11): the assistant's panel on every page of the market.
// Closed, the panel renders nothing, so the shell's slot stays empty and hidden (components/shell/chat-panel.tsx).
import type { Market } from "../../../../lib/data/constants.ts";
import { AssistantPanel } from "../assistant/_parts/chat-panel.tsx";

export default async function ChatSlot({ params }: { params: Promise<{ market: string }> }) {
  return <AssistantPanel market={(await params).market as Market} />;
}
