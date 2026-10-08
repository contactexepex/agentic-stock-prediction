// The market layout (B7): every page lives under /{market}/... inside the app shell. An unknown market is a 404.
// `chat` is the parallel route @chat (owned by B8): the F11 chat panel, rendered into the shell's slot.
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { AppShell } from "../../../components/shell/app-shell.tsx";
import { MARKETS } from "../../../lib/data/constants.ts";
import { isMarket } from "../../../lib/ui/routes.ts";

export function generateStaticParams() {
  return MARKETS.map((market) => ({ market }));
}

export const dynamicParams = false;

export default async function MarketLayout({ children, chat, params }: { children: ReactNode; chat: ReactNode; params: Promise<{ market: string }> }) {
  const { market } = await params;
  if (!isMarket(market)) notFound();
  return (
    <AppShell market={market} chat={chat}>
      {children}
    </AppShell>
  );
}
