"use client";
// The theme the page shows now ("light" | "dark"), updated when the reader presses the theme button or the device
// switches scheme; charts that copy token colours into a canvas (components/charts/candles.tsx) redraw on it.
import { useEffect, useState } from "react";
import { THEME_EVENT, shownTheme } from "./theme.ts";

export function useShownTheme(): "light" | "dark" {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  useEffect(() => {
    const update = () => setTheme(shownTheme());
    update();
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    query.addEventListener("change", update);
    window.addEventListener(THEME_EVENT, update);
    return () => {
      query.removeEventListener("change", update);
      window.removeEventListener(THEME_EVENT, update);
    };
  }, []);
  return theme;
}
