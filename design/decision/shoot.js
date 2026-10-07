const { chromium } = require('playwright');
const S = __dirname;
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' }).catch(() => chromium.launch());
  const errs = [];
  for (const [w, h, tag, mobile] of [[1280, 900, '1280', false], [390, 844, '390', true]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile });
    const page = await ctx.newPage();
    page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') errs.push(tag + ' console.' + m.type() + ': ' + m.text()); });
    page.on('pageerror', e => errs.push(tag + ' pageerror: ' + e.message));
    page.on('request', r => { if (!r.url().startsWith('file:') && !r.url().startsWith('data:')) errs.push('external request ' + r.url()); });
    await page.goto('file://' + S + '/decision-HDFCBANK.html');
    await page.waitForTimeout(600);
    const sw = await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth));
    if (sw > w) errs.push(`${tag} horizontal overflow: ${sw} > ${w}`);
    const wide = await page.evaluate(vw => Array.from(document.querySelectorAll('body *')).filter(el => { const r = el.getBoundingClientRect(); return r.right > vw + 1 && r.width > 0 && getComputedStyle(el).position !== 'fixed' && !el.closest('.tblwrap') && el.id !== 'tip'; }).slice(0, 6).map(el => el.tagName + '.' + el.className + ' ' + Math.round(el.getBoundingClientRect().right)), w);
    if (wide.length) errs.push(`${tag} elements past the edge: ${wide.join(' | ')}`);
    await page.screenshot({ path: `${S}/shot-${tag}-full.png`, fullPage: true });
    if (mobile) await page.screenshot({ path: `${S}/shot-${tag}-viewport.png`, fullPage: false });
    if (!mobile) {
      // hover the chart to capture the tooltip
      const c = await page.$('#chart svg');
      await c.scrollIntoViewIfNeeded(); await page.evaluate(() => window.scrollBy(0, -140)); await page.waitForTimeout(200);
      const b = await c.boundingBox();
      await page.mouse.move(b.x + b.width * 0.55, b.y + b.height * 0.5);
      await page.waitForTimeout(200);
      await page.screenshot({ path: `${S}/shot-1280-chart-hover.png`, clip: { x: 0, y: Math.max(0, b.y - 130), width: 1280, height: Math.min(900 - Math.max(0, b.y - 130), b.height + 200) } });
      await page.click('.seg button[data-h="5"]');
      await page.waitForTimeout(300);
      await page.screenshot({ path: `${S}/shot-1280-chart-5d.png`, clip: { x: 0, y: Math.max(0, b.y - 130), width: 1280, height: Math.min(900 - Math.max(0, b.y - 130), b.height + 200) } });
      await page.click('.seg button[data-h="1"]');
    }
    await ctx.close();
  }
  await browser.close();
  console.log(errs.length ? errs.join('\n') : 'no console errors, no overflow, no external requests');
})();
