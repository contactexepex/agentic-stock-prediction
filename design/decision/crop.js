const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true })).newPage();
  await page.goto('file://' + __dirname + '/decision-HDFCBANK.html'); await page.waitForTimeout(600);
  for (const id of ['timeline','changes','drivers-card','coming']) { const e = await page.$('#'+id); await e.screenshot({ path: `${__dirname}/crop-390-${id}.png` }); }
  const e = await page.$('#decision'); await e.screenshot({ path: `${__dirname}/crop-390-decision.png` });
  await browser.close();
})();
