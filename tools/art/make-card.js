// Renders tools/art/wu-card.html (1200 x 630) to a PNG with Playwright's Chromium:
//   node tools/art/make-card.js <out.png>
// then convert it to stream/www-files/art/wu-card.webp (for example with Pillow, quality 86), and copy it to
// gmconsole/server/static/art/ with the rest of the art.
const path = require('path');
const { chromium } = require('playwright');
(async () => {
  const out = process.argv[2] || 'wu-card.png';
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1200, height: 630 } });
  await p.goto('file://' + path.join(__dirname, 'wu-card.html'));
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(300);
  await p.screenshot({ path: out, clip: { x: 0, y: 0, width: 1200, height: 630 } });
  await b.close();
  console.log('wrote', out);
})();
