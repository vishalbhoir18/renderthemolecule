// Capture the Mol* 3D preview for experiment E8 (preview against render).
//
//   node paper/benchmark/capture_previews.js http://localhost:7861 paper/benchmark/preview
//
// For each entry: the preset view, then a view turned by dragging. Saves the
// viewer canvas as PNG and the camera Mol* reports (Preview.camera(), the same
// object the page sends with "Render this view") to cameras.json.
const { chromium } = require('playwright');
const fs = require('fs');
const [, , SITE, OUT] = process.argv;
const ENTRIES = ['1EMA', '4HHB', '1BNA', '1AON'];
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1 })).newPage();
  await page.goto(SITE, { waitUntil: 'networkidle' });
  const cameras = {};
  for (const id of ENTRIES) {
    await page.click('#tab-preview');
    await page.fill('#pdb_id', id);
    await page.press('#pdb_id', 'Tab');
    await page.waitForFunction((code) => Preview.shownId === code.toLowerCase() && !Preview.busy, id, { timeout: 180000 });
    await page.click('#reset-view').catch(() => {});
    await page.waitForTimeout(2500);
    const canvas = page.locator('#viewer canvas').first();
    await canvas.screenshot({ path: `${OUT}/${id}_preset.png` });
    cameras[`${id}_preset`] = await page.evaluate(() => Preview.camera());
    const box = await canvas.boundingBox();
    const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
    await page.mouse.move(cx, cy); await page.mouse.down();
    await page.mouse.move(cx + 140, cy - 70, { steps: 14 }); await page.mouse.up();
    await page.waitForTimeout(2000);
    await canvas.screenshot({ path: `${OUT}/${id}_moved.png` });
    cameras[`${id}_moved`] = await page.evaluate(() => Preview.camera());
    console.log(id, JSON.stringify(cameras[`${id}_moved`]), 'use_view', await page.isChecked('#use_view'));
  }
  fs.writeFileSync(`${OUT}/cameras.json`, JSON.stringify(cameras, null, 1));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
