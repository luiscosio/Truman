// Offline document renderer for video assets. Never visits a live website.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const browser = await chromium.launch({headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1360, height: 1000},
      deviceScaleFactor: 1, javaScriptEnabled: false, serviceWorkers: 'block'});
    for (const item of manifest.pages) {
      const page = await context.newPage();
      const denied = new Set();
      await page.route('**/*', async route => {
        const url = route.request().url();
        const pathname = new URL(url).pathname;
        const name = pathname.split('/').pop();
        if (item.resources[url]) {
          await route.fulfill({path:item.resources[url].path,
            contentType:item.resources[url].contentType || undefined});
        } else if (/^[a-f0-9]{64}$/.test(name) && item.assets[name]) {
          await route.fulfill({path: item.assets[name]});
        } else {
          denied.add(url);
          await route.abort();
        }
      });
      await page.setContent(fs.readFileSync(item.html, 'utf8'), {waitUntil: 'load'});
      // Viewport positioning only; do not rewrite or hide page content.
      if (item.selector) {
        const anchor = page.locator(item.selector).first();
        if (await anchor.count()) await anchor.scrollIntoViewIfNeeded();
      }
      await page.screenshot({path: item.output, animations: 'disabled'});
      // Capture an additional detail crop chosen explicitly by the operator.
      if (item.detailSelector) {
        const detail = page.locator(item.detailSelector).first();
        if (!await detail.count()) throw new Error('Missing detail selector: '+item.detailSelector);
        await detail.screenshot({path: item.detailOutput, animations: 'disabled'});
      }
      item.blockedExternalResources = [...denied];
      await page.close();
    }
    await context.close();
  } finally { await browser.close(); }
  fs.writeFileSync(process.argv[2], JSON.stringify(manifest, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
