// Text contrast check of the UI harness (UX4): every visible element with its own text (HTML text and SVG <text>) is
// measured against the background it sits on, WCAG 2.x: 4.5:1 for normal text, 3:1 for large text (24 px, or 18.66 px
// bold). The background is the element's ancestors' background colours composed from the page down (with opacity);
// text over a background image or gradient cannot be measured this way and is counted as `unmeasured`, not failed.
// Disabled controls, screen-reader-only text and decorative punctuation hidden from screen readers are skipped (WCAG
// exempts inactive components and decoration). Runs in the page.

/** page.evaluate(contrastScan) -> {checked, unmeasured, failures: [{text, ratio, need, fg, bg, where}]} */
export function contrastScan() {
  const parse = (value) => {
    if (!value || value === "transparent" || value === "none") return [0, 0, 0, 0];
    let m = /^rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/.exec(value);
    if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : m[4].endsWith("%") ? parseFloat(m[4]) / 100 : +m[4]];
    m = /^color\(srgb\s+([\d.e-]+)\s+([\d.e-]+)\s+([\d.e-]+)(?:\s*\/\s*([\d.]+%?))?\s*\)$/.exec(value);
    if (m) return [m[1] * 255, m[2] * 255, m[3] * 255, m[4] === undefined ? 1 : m[4].endsWith("%") ? parseFloat(m[4]) / 100 : +m[4]];
    return null;
  };
  const over = (top, under) => {
    const a = top[3] + under[3] * (1 - top[3]);
    if (!a) return [0, 0, 0, 0];
    return [0, 1, 2].map((i) => (top[i] * top[3] + under[i] * under[3] * (1 - top[3])) / a).concat(a);
  };
  const lum = ([r, g, b]) => {
    const lin = (c) => ((c /= 255) <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  };
  const ratio = (a, b) => {
    const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  const hex = (c) => "#" + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
  const inClosedDetails = (el) => {
    for (let d = el.closest("details"); d; d = d.parentElement?.closest("details")) if (!d.open && !d.querySelector(":scope > summary")?.contains(el)) return true;
    return false;
  };
  // The page canvas: the root's background (or body's, propagated), white when neither sets one.
  const rootBg = (() => {
    for (const el of [document.documentElement, document.body]) {
      const c = parse(getComputedStyle(el).backgroundColor);
      if (c && c[3] > 0) return over(c, [255, 255, 255, 1]);
    }
    return [255, 255, 255, 1];
  })();
  /** The composed background under `el`, or null when an image or gradient is in the way. */
  const backgroundOf = (el) => {
    const layers = [];
    for (let a = el; a && a !== document.documentElement; a = a.parentElement) {
      if (a instanceof SVGElement && !(a instanceof SVGSVGElement)) continue;
      const cs = getComputedStyle(a);
      if (cs.backgroundImage && cs.backgroundImage !== "none") return null;
      const c = parse(cs.backgroundColor);
      if (c === null) return null;
      if (c[3] > 0) {
        layers.push(c);
        if (c[3] >= 1) break;
      }
    }
    let bg = rootBg;
    for (const layer of layers.reverse()) bg = over(layer, bg);
    return bg;
  };
  const opacityOf = (el) => {
    let o = 1;
    for (let a = el; a; a = a.parentElement) o *= parseFloat(getComputedStyle(a).opacity || "1");
    return o;
  };
  const failures = [];
  let checked = 0;
  let unmeasured = 0;
  for (const el of document.querySelectorAll("body *")) {
    if (["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "OPTION"].includes(el.tagName)) continue;
    const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim();
    if (!own) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none") continue;
    if (el.closest(".mb-sr, [hidden], :disabled, [aria-disabled='true'], #tip:not(.on)") || inClosedDetails(el)) continue;
    // A decorative separator (punctuation only, hidden from screen readers) is not text WCAG measures.
    if (!/[\p{L}\p{N}]/u.test(own) && el.closest("[aria-hidden='true']")) continue;
    // Hidden by an ancestor's display:none (getBoundingClientRect is then 0) is already skipped above.
    const isSvgText = el instanceof SVGElement;
    const fg = parse(isSvgText ? cs.fill : cs.color);
    let bg = backgroundOf(el);
    // An SVG label drawn on its own chip: the filled shape before it in the same group, under the text's centre.
    if (isSvgText && bg) {
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      for (let s = el.previousElementSibling; s; s = s.previousElementSibling) {
        if (!["rect", "path", "circle"].includes(s.tagName)) continue;
        const sr = s.getBoundingClientRect();
        if (cx < sr.left || cx > sr.right || cy < sr.top || cy > sr.bottom) continue;
        const scs = getComputedStyle(s);
        const fill = parse(scs.fill);
        if (fill) bg = over([fill[0], fill[1], fill[2], fill[3] * parseFloat(scs.fillOpacity || "1") * parseFloat(scs.opacity || "1")], bg);
        break;
      }
    }
    if (!fg || !bg) {
      unmeasured++;
      continue;
    }
    const o = opacityOf(el);
    const text = over([fg[0], fg[1], fg[2], fg[3] * o], bg);
    const size = parseFloat(cs.fontSize);
    const bold = parseInt(cs.fontWeight, 10) >= 700;
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    const got = ratio(text, bg);
    checked++;
    if (got + 0.005 < need) {
      const cls = typeof el.className === "string" ? el.className : el.className?.baseVal ?? "";
      const parent = el.parentElement;
      const pcls = parent ? (typeof parent.className === "string" ? parent.className : parent.className?.baseVal ?? "") : "";
      failures.push({ text: own.slice(0, 40), ratio: Math.round(got * 100) / 100, need, fg: hex(text), bg: hex(bg), where: `${parent?.tagName.toLowerCase()}.${pcls.split(/\s+/)[0] ?? ""} > ${el.tagName.toLowerCase()}${cls ? "." + cls.split(/\s+/).slice(0, 2).join(".") : ""}` });
    }
  }
  return { checked, unmeasured, failures };
}

/** The harness's findings for one page: one line per distinct failing colour pair and place (the first texts named). */
export async function contrastProblems(page) {
  const { checked, failures } = await page.evaluate(contrastScan);
  const grouped = new Map();
  for (const f of failures) {
    const key = `${f.where} ${f.fg} on ${f.bg}`;
    const g = grouped.get(key) ?? { ...f, texts: [] };
    if (g.texts.length < 3) g.texts.push(f.text);
    grouped.set(key, g);
  }
  const problems = [...grouped.values()].map((g) => `low contrast ${g.ratio}:1 (needs ${g.need}) ${g.fg} on ${g.bg} at ${g.where}: "${g.texts.join('" | "')}"`);
  if (!checked) problems.push("contrast: no text measured");
  return problems;
}
