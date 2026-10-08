"use client";
// The one tooltip of the app (the mockups' behaviour): any element with data-tip shows its text on hover, on keyboard
// focus and on tap (tap again or elsewhere closes it; Escape closes it). Elements with data-tip that cannot take focus
// get tabindex=0, so every explanation is reachable by keyboard. The text is set as text, never as HTML.
import { useEffect, useRef } from "react";

const FOCUSABLE = "a[href], button, input, select, textarea, [tabindex]";

export function TooltipLayer() {
  const tipRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const tip = tipRef.current;
    if (!tip) return;
    let pinned: Element | null = null;
    const show = (target: Element) => {
      const text = target.getAttribute("data-tip");
      if (!text) return;
      tip.textContent = text;
      tip.classList.add("on");
      const r = target.getBoundingClientRect();
      let left = r.left + r.width / 2 - tip.offsetWidth / 2;
      let top = r.top - tip.offsetHeight - 10;
      left = Math.max(8, Math.min(window.innerWidth - tip.offsetWidth - 8, left));
      if (top < 8) top = r.bottom + 12;
      tip.style.left = `${left}px`;
      tip.style.top = `${top}px`;
    };
    const hide = () => {
      if (!pinned) tip.classList.remove("on");
    };
    const tipTarget = (e: Event) => (e.target instanceof Element ? e.target.closest("[data-tip]") : null);
    const onOver = (e: Event) => {
      const t = tipTarget(e);
      if (t && !pinned) show(t);
    };
    const onOut = (e: Event) => {
      if (tipTarget(e)) hide();
    };
    const onFocusIn = (e: Event) => {
      const t = tipTarget(e);
      if (t) show(t);
    };
    const onFocusOut = (e: Event) => {
      if (tipTarget(e)) {
        pinned = null;
        hide();
      }
    };
    const onClick = (e: MouseEvent) => {
      const t = tipTarget(e);
      // Links, buttons, tabs, filter chips and table heads act on click; their tooltip shows on hover and focus only.
      const acts = t && (t.closest("a, button, .md-segmented, .md-chip.filter, th") !== null);
      if (t && !acts) {
        if (pinned === t) {
          pinned = null;
          hide();
        } else {
          pinned = t;
          show(t);
        }
      } else if (pinned) {
        pinned = null;
        hide();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        pinned = null;
        tip.classList.remove("on");
      }
    };
    const makeFocusable = (root: ParentNode) => {
      for (const n of root.querySelectorAll("[data-tip]")) if (!n.matches(FOCUSABLE)) n.setAttribute("tabindex", "0");
    };
    makeFocusable(document);
    const observer = new MutationObserver((records) => {
      for (const r of records) {
        for (const n of r.addedNodes) if (n instanceof Element) {
          if (n.matches("[data-tip]") && !n.matches(FOCUSABLE)) n.setAttribute("tabindex", "0");
          makeFocusable(n);
        }
        if (r.type === "attributes" && r.target instanceof Element && r.target.matches("[data-tip]") && !r.target.matches(FOCUSABLE)) r.target.setAttribute("tabindex", "0");
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-tip"] });
    document.addEventListener("pointerover", onOver);
    document.addEventListener("pointerout", onOut);
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      observer.disconnect();
      document.removeEventListener("pointerover", onOver);
      document.removeEventListener("pointerout", onOut);
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  return <div ref={tipRef} id="tip" className="md-tooltip" role="tooltip" />;
}
