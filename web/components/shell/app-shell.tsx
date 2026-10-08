"use client";
// The app shell of every page (the mockups' shell, design/system/README.md "How a page uses it"): the dark sidebar
// with the pages (labels from 1200 px, icons from 600 px, a drawer with a scrim below), the top bar (menu button, page
// title, company search, the India / US market switch, Ask), the content area, the chat panel slot (B8) and the phone
// bar. The sidebar's foot is the status bar: the market's Paper label, data date and freshness from /status.
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { MARKETS, type Market } from "../../lib/data/constants.ts";
import { MARKET_LABEL } from "../../lib/ui/constants.ts";
import { PAGES, PHONE_BAR, pageByKey, pageOfPath, pagePath, switchMarketPath, type PageRoute } from "../../lib/ui/routes.ts";
import { Icon } from "../ui/icon.tsx";
import { ChatPanelProvider, useChatPanel } from "./chat-panel.tsx";
import { StatusBar } from "./status-bar.tsx";
import { TooltipLayer } from "./tooltip-layer.tsx";

function NavItem({ page, market, current, onNavigate }: { page: PageRoute; market: Market; current: boolean; onNavigate?: () => void }) {
  return (
    <Link className="mb-nav-item" href={pagePath(market, page.key)} aria-current={current ? "page" : undefined} onClick={onNavigate}>
      <span className="mb-nav-ind">
        <Icon name={page.icon} />
      </span>
      <span className="mb-nav-label">{page.label}</span>
    </Link>
  );
}

function MarketSwitch({ market }: { market: Market }) {
  const pathname = usePathname() ?? `/${market}`;
  const router = useRouter();
  const page = pageOfPath(pathname);
  return (
    <div className="md-segmented dense light" role="group" aria-label="Market">
      {MARKETS.map((m) => (
        <button
          key={m}
          type="button"
          aria-pressed={m === market}
          data-tip={page.key === "company" || page.key === "strategies" ? `Switch to the ${MARKET_LABEL[m]} watchlist (a company belongs to one market)` : `Switch to the ${MARKET_LABEL[m]} ${page.label} page`}
          onClick={() => m !== market && router.push(switchMarketPath(pathname, m))}
        >
          {MARKET_LABEL[m]}
        </button>
      ))}
    </div>
  );
}

function AskButton({ market }: { market: Market }) {
  const chat = useChatPanel();
  const tip = "Ask the assistant: answers cite ids and as-of times, read-only.";
  if (chat.available) {
    return (
      <button className="md-btn filled" type="button" data-tip={tip} aria-label="Ask the assistant" aria-expanded={chat.open} aria-controls="mb-chat-slot" onClick={chat.toggle}>
        <Icon name="bolt" />
        <span className="ask-l">Ask</span>
      </button>
    );
  }
  return (
    <Link className="md-btn filled" href={pagePath(market, "assistant")} data-tip={tip} aria-label="Ask the assistant">
      <Icon name="bolt" />
      <span className="ask-l">Ask</span>
    </Link>
  );
}

function Shell({ market, children, chat }: { market: Market; children: ReactNode; chat?: ReactNode }) {
  const pathname = usePathname() ?? `/${market}`;
  const current = pageOfPath(pathname);
  const [menuOpen, setMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const chatState = useChatPanel();
  useEffect(() => setMenuOpen(false), [pathname]);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    window.addEventListener("scroll", onScroll, { passive: true });
    document.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", onScroll);
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  // The sidebar marks the page a per-stock page belongs to (the company pages hang off the Watchlist).
  const navKey = current.nav ? current.key : "watchlist";
  return (
    <div className={`mb-app${chatState.open ? " chat-open" : ""}`}>
      <a className="mb-skip" href="#mb-main">
        Skip to the page
      </a>
      <TooltipLayer />
      <nav className={`mb-sidebar${menuOpen ? " open" : ""}`} aria-label="Pages" id="sidebar">
        <div className="mb-sidebar-brand">
          <span className="mb-brand-mark" aria-hidden="true">
            MB
          </span>
          <span>
            Market brief<small>research cockpit</small>
          </span>
        </div>
        <div className="mb-sidebar-section">Pages</div>
        {PAGES.filter((p) => p.nav).map((p) => (
          <NavItem key={p.key} page={p} market={market} current={p.key === navKey} onNavigate={() => setMenuOpen(false)} />
        ))}
        <StatusBar market={market} />
      </nav>
      <div className="mb-scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />
      <header className={`mb-topbar${scrolled ? " scrolled" : ""}`} id="topbar">
        <button className="md-icon-btn mb-menu-btn" type="button" aria-label="Open the menu" aria-controls="sidebar" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>
          <Icon name="menu" />
        </button>
        <div className="mb-topbar-title">{current.label}</div>
        <div className="mb-topbar-actions">
          <Link className="mb-search" href={pagePath(market, "watchlist")} data-tip="Search a company: opens the watchlist with its filter.">
            <Icon name="search" />
            <span>Search a company…</span>
          </Link>
          <MarketSwitch market={market} />
          <AskButton market={market} />
        </div>
      </header>
      <main className="mb-content" id="mb-main" tabIndex={-1}>
        <div className="mb-content-inner">{children}</div>
      </main>
      <div className="mb-chat-slot" id="mb-chat-slot">
        {chat}
      </div>
      <nav className="mb-navbar" aria-label="Pages">
        {PHONE_BAR.map((key) => (
          <NavItem key={key} page={pageByKey(key)} market={market} current={key === navKey} />
        ))}
        <button className="mb-nav-item" type="button" aria-controls="sidebar" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>
          <span className="mb-nav-ind">
            <Icon name="menu" />
          </span>
          <span className="mb-nav-label">More</span>
        </button>
      </nav>
    </div>
  );
}

/** <AppShell market="india" chat={chatSlot}>{page}</AppShell>, rendered by web/app/(cockpit)/[market]/layout.tsx. */
export function AppShell({ market, children, chat }: { market: Market; children: ReactNode; chat?: ReactNode }) {
  return (
    <ChatPanelProvider>
      <Shell market={market} chat={chat}>
        {children}
      </Shell>
    </ChatPanelProvider>
  );
}
