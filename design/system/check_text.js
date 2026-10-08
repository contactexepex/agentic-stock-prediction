// Playwright scan of a built page for clipped, overflowing and overlapping text at eight widths (390-1680 px) and both
// markets (#india, #us): node design/system/check_text.js <page.html>. Inline elements that wrap (a ticker before a
// multi-line headline) are reported as overlaps by their bounding boxes; read the list, it is not a pass/fail gate.
const { chromium } = require('playwright'); const path = require('path');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' }).catch(() => chromium.launch());
  const file = 'file://' + path.resolve(process.argv[2] || 'design/mockups/01-home/page.html');
  const out = [];
  for (const [w, mobile] of [[390, true], [600, false], [768, false], [1024, false], [1199, false], [1280, false], [1440, false], [1680, false]]) {
    for (const m of ['india', 'us']) {
      const ctx = await b.newContext({ viewport: { width: w, height: 900 }, isMobile: mobile, hasTouch: mobile });
      const p = await ctx.newPage(); await p.goto(file + '#' + m); await p.waitForTimeout(300);
      const probs = await p.evaluate(() => {
        const res = []; const seen = new Set();
        const desc = el => (el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0,2).join('.') : '')) + ' "' + (el.textContent || '').trim().slice(0, 40).replace(/\s+/g,' ') + '"';
        const inClosed = el => { let d = el.closest('details'); while (d) { if (!d.open && !d.contains(el.closest('summary')) ) return true; d = d.parentElement && d.parentElement.closest('details'); } return false; };
        const isFixed = el => { let a = el; while (a && a !== document.body) { if (getComputedStyle(a).position === 'fixed') return true; a = a.parentElement; } return false; };
        const all = Array.from(document.querySelectorAll('body *')).filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden' && !inClosed(el) && !isFixed(el) && !el.closest('.mb-sidebar'); });
        // 1. clipped: own text wider than the box when overflow is hidden/clip/auto (scrolling wrappers excluded)
        for (const el of all) {
          const cs = getComputedStyle(el);
          if (el.closest('.md-table-wrap') && el.classList.contains('md-table-wrap')) continue;
          if (['hidden','clip'].includes(cs.overflowX) && el.scrollWidth > el.clientWidth + 1 && el.textContent.trim() && cs.textOverflow !== 'ellipsis') res.push(`clipped ${desc(el)} (${el.scrollWidth}>${el.clientWidth})`);
          if (cs.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1 && !el.classList.contains('mb-topbar-title')) res.push(`ellipsis ${desc(el)}`);
        }
        // 2. text leaf past its nearest clipping ancestor or past a sized parent (visible overflow)
        const leaves = all.filter(el => el.childElementCount === 0 && el.textContent.trim() && !['svg','use','path','rect','circle','line','text','tspan','style','script'].includes(el.tagName.toLowerCase()));
        for (const el of leaves) {
          const r = el.getBoundingClientRect(); let a = el.parentElement;
          while (a && a !== document.body) { const ar = a.getBoundingClientRect(); const cs = getComputedStyle(a);
            if (a.classList.contains('md-table-wrap')) break;
            if (ar.width > 0 && (r.right > ar.right + 1.5 || r.left < ar.left - 1.5)) { const k = desc(el) + '>' + desc(a); if (!seen.has(k)) { seen.add(k); res.push(`overflow ${desc(el)} past ${desc(a)} by ${Math.round(Math.max(r.right - ar.right, ar.left - r.left))}px`); } break; }
            if (cs.overflowX !== 'visible') break; a = a.parentElement; }
        }
        // 3. overlapping text leaves (not ancestor/descendant), overlap area > 12px in both axes
        const rects = leaves.map(el => [el, el.getBoundingClientRect()]);
        for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
          const [a, ra] = rects[i], [c, rc] = rects[j]; if (a.contains(c) || c.contains(a)) continue;
          if (a.closest('.md-tooltip') || c.closest('.md-tooltip') || a.closest('.mb-sidebar') !== c.closest('.mb-sidebar')) continue;
          const ox = Math.min(ra.right, rc.right) - Math.max(ra.left, rc.left), oy = Math.min(ra.bottom, rc.bottom) - Math.max(ra.top, rc.top);
          if (ox > 4 && oy > 4) res.push(`overlap ${desc(a)} x ${desc(c)} (${Math.round(ox)}x${Math.round(oy)})`);
        }
        return res;
      });
      for (const x of probs) out.push(`${w} ${m}: ${x}`);
      await ctx.close();
    }
  }
  await b.close();
  const uniq = [...new Set(out)]; console.log(uniq.join('\n') || 'no clipped, overflowing or overlapping text'); console.log(`-- ${uniq.length} findings`);
})();
