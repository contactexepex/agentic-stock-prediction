// Playwright check of a built page with the pre-installed Chromium (no `playwright install`):
//   node design/system/check_page.js <page.html> <out-dir> <prefix> [hover-selector]
// At 1280 and 390 px: console errors/warnings, page errors, any non-file request, horizontal
// overflow and elements past the viewport edge; writes <prefix>-1280-full.png, <prefix>-390-full.png
// and <prefix>-390-viewport.png (and <prefix>-1280-hover.png when a hover selector is given).
const { chromium } = require('playwright');
const path = require('path');
const [,, file, outDir, prefix, hoverSel] = process.argv;
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' }).catch(() => chromium.launch());
  const errs = [];
  for (const [w, h, tag, mobile] of [[1280, 900, '1280', false], [390, 844, '390', true]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile });
    const page = await ctx.newPage();
    page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') errs.push(tag + ' console.' + m.type() + ': ' + m.text()); });
    page.on('pageerror', e => errs.push(tag + ' pageerror: ' + e.message));
    page.on('request', r => { if (!r.url().startsWith('file:') && !r.url().startsWith('data:')) errs.push('external request ' + r.url()); });
    await page.goto('file://' + path.resolve(file));
    await page.waitForTimeout(600);
    const sw = await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth));
    if (sw > w) errs.push(`${tag} horizontal overflow: ${sw} > ${w}`);
    const wide = await page.evaluate(vw => Array.from(document.querySelectorAll('body *')).filter(el => { const r = el.getBoundingClientRect(); return r.right > vw + 1 && r.width > 0 && getComputedStyle(el).position !== 'fixed' && !el.closest('.md-table-wrap, .tblwrap, .md-pre, pre, .tape') && el.id !== 'tip'; }).slice(0, 6).map(el => el.tagName + '.' + el.className + ' ' + Math.round(el.getBoundingClientRect().right)), w);
    if (wide.length) errs.push(`${tag} elements past the edge: ${wide.join(' | ')}`);
    await page.screenshot({ path: path.join(outDir, `${prefix}-${tag}-full.png`), fullPage: true });
    if (mobile) await page.screenshot({ path: path.join(outDir, `${prefix}-${tag}-viewport.png`), fullPage: false });
    if (!mobile && hoverSel) {
      const c = await page.$(hoverSel);
      if (c) { await c.scrollIntoViewIfNeeded(); await page.evaluate(() => window.scrollBy(0, -140)); await page.waitForTimeout(200);
        const b = await c.boundingBox(); await page.mouse.move(b.x + b.width * 0.55, b.y + b.height * 0.5); await page.waitForTimeout(250);
        await page.screenshot({ path: path.join(outDir, `${prefix}-1280-hover.png`), clip: { x: 0, y: Math.max(0, b.y - 130), width: 1280, height: Math.min(900 - Math.max(0, b.y - 130), b.height + 200) } }); }
    }
    await ctx.close();
  }
  await browser.close();
  console.log(errs.length ? errs.join('\n') : `${file}: no console errors, no overflow, no external requests`);
  process.exit(errs.length ? 1 : 0);
})();
