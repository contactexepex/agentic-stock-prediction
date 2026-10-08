"use client";
// The chat panel slot (F11, built by B8). The market layout renders the parallel route `@chat`
// (web/app/(cockpit)/[market]/@chat/, owned by B8) into the shell's slot; B8's panel calls useRegisterChatPanel() so
// the top bar's Ask button opens it instead of going to the Assistant page, and reads useChatPanel() for its state.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export interface ChatPanelState {
  /** A panel is mounted in the slot. */
  available: boolean;
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
  register: () => () => void;
}

const ChatPanelContext = createContext<ChatPanelState | null>(null);

export function ChatPanelProvider({ children }: { children: ReactNode }) {
  const [panels, setPanels] = useState(0);
  const [open, setOpen] = useState(false);
  const register = useCallback(() => {
    setPanels((n) => n + 1);
    return () => setPanels((n) => n - 1);
  }, []);
  const toggle = useCallback(() => setOpen((o) => !o), []);
  const value = useMemo(() => ({ available: panels > 0, open: panels > 0 && open, setOpen, toggle, register }), [panels, open, toggle, register]);
  return <ChatPanelContext.Provider value={value}>{children}</ChatPanelContext.Provider>;
}

/** The panel's state (open, available) and its controls. */
export function useChatPanel(): ChatPanelState {
  const state = useContext(ChatPanelContext);
  if (!state) throw new Error("useChatPanel outside the app shell");
  return state;
}

/** Called once by the chat panel component: marks the slot as filled while it is mounted. */
export function useRegisterChatPanel(): ChatPanelState {
  const state = useChatPanel();
  const { register } = state;
  useEffect(() => register(), [register]);
  return state;
}
