// The theme choice (UX4): the cycle, the attribute, the boot script and the wrapped storage.
import assert from "node:assert/strict";
import { test } from "node:test";
import { THEMES, THEME_BOOT_SCRIPT, THEME_ICON, THEME_KEY, isTheme, nextTheme, readTheme, saveTheme, themeAttribute } from "../theme.ts";

function withWindow(storage: Partial<Storage>, run: () => void) {
  const g = globalThis as unknown as { window?: unknown };
  const before = g.window;
  g.window = { localStorage: storage };
  try {
    run();
  } finally {
    g.window = before;
  }
}

test("the toggle cycles System, Light, Dark", () => {
  assert.deepEqual([...THEMES], ["system", "light", "dark"]);
  assert.equal(nextTheme("system"), "light");
  assert.equal(nextTheme("light"), "dark");
  assert.equal(nextTheme("dark"), "system");
  for (const t of THEMES) assert.ok(THEME_ICON[t]);
});

test("System removes data-theme, Light and Dark set it", () => {
  assert.equal(themeAttribute("system"), null);
  assert.equal(themeAttribute("light"), "light");
  assert.equal(themeAttribute("dark"), "dark");
  assert.ok(isTheme("dark") && !isTheme("blue") && !isTheme(null));
});

test("a saved choice is read back; anything else or a throwing storage reads System", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v), removeItem: (k: string) => void store.delete(k) };
  withWindow(storage, () => {
    saveTheme("dark");
    assert.equal(store.get(THEME_KEY), "dark");
    assert.equal(readTheme(), "dark");
    saveTheme("system");
    assert.equal(store.has(THEME_KEY), false);
    store.set(THEME_KEY, "blue");
    assert.equal(readTheme(), "system");
  });
  const throwing = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }, removeItem: () => { throw new Error("blocked"); } };
  withWindow(throwing, () => {
    assert.equal(readTheme(), "system");
    assert.doesNotThrow(() => saveTheme("light"));
  });
});

test("the boot script reads the same key, sets only light or dark, and swallows storage errors", () => {
  assert.ok(THEME_BOOT_SCRIPT.includes(JSON.stringify(THEME_KEY)));
  assert.ok(THEME_BOOT_SCRIPT.includes("try{") && THEME_BOOT_SCRIPT.includes("catch(e){}"));
  const attrs: Record<string, string> = {};
  const run = (saved: string | null, fail = false) => {
    for (const k of Object.keys(attrs)) delete attrs[k];
    const localStorage = { getItem: () => { if (fail) throw new Error("blocked"); return saved; } };
    const document = { documentElement: { setAttribute: (k: string, v: string) => (attrs[k] = v) } };
    new Function("localStorage", "document", THEME_BOOT_SCRIPT)(localStorage, document);
    return attrs["data-theme"];
  };
  assert.equal(run("dark"), "dark");
  assert.equal(run("light"), "light");
  assert.equal(run("system"), undefined);
  assert.equal(run("<script>"), undefined);
  assert.equal(run(null, true), undefined);
});
