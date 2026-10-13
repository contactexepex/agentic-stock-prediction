"use client";
// The top bar's theme button (UX4): one press moves System -> Light -> Dark -> System; the label and tooltip name the
// current choice and the next one. lib/ui/theme.ts holds the storage and the attribute.
import { useEffect, useState } from "react";
import { THEME_ICON, THEME_LABEL, applyTheme, nextTheme, readTheme, saveTheme, type Theme } from "../../lib/ui/theme.ts";
import { Icon } from "../ui/icon.tsx";

export function ThemeToggle() {
  // The server renders "system"; the saved choice is read after mount (the boot script already applied it).
  const [theme, setTheme] = useState<Theme>("system");
  useEffect(() => setTheme(readTheme()), []);
  const next = nextTheme(theme);
  const tip = `Theme: ${THEME_LABEL[theme]}${theme === "system" ? " (follows your device)" : ""}. Press for ${THEME_LABEL[next]}.`;
  return (
    <button
      className="md-icon-btn mb-theme-btn"
      type="button"
      aria-label={`Theme: ${THEME_LABEL[theme]}. Switch to ${THEME_LABEL[next]}`}
      data-tip={tip}
      data-theme-choice={theme}
      onClick={() => {
        saveTheme(next);
        applyTheme(next);
        setTheme(next);
      }}
    >
      <Icon name={THEME_ICON[theme]} />
    </button>
  );
}
