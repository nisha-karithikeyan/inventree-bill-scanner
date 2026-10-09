// Capture README screenshots from the running dev instance.
//   node dev/screenshots.mjs   (needs dev/server.sh and the Vite dev server on :5173)
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const require = createRequire(path.join(root, '.dev/inventree-frontend/package.json'));
const { chromium } = require('@playwright/test');

const BASE = process.env.UI_URL ?? 'http://localhost:5173';
const OUT = path.join(root, 'docs/screenshots');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });

await page.goto(`${BASE}/web/login`);
await page.getByRole('textbox', { name: 'login-username' }).fill(process.env.DEV_ADMIN_USER ?? 'admin');
await page.getByRole('textbox', { name: 'login-password' }).fill(process.env.DEV_ADMIN_PASSWORD ?? 'admin');
await page.getByRole('button', { name: 'Log in' }).click();
await page.waitForURL(/\/web\/home/, { timeout: 60000 });

await page.goto(`${BASE}/web/purchasing/index/`);
await page.getByText('Scanned Bills').first().click();
await page.getByRole('table', { name: 'Scanned bills' }).waitFor({ timeout: 60000 });
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/bill-list.png` });

await page.getByText('DES-2057').first().click();
await page.getByRole('table', { name: 'Bill lines' }).waitFor();
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/bill-review.png`, fullPage: true });

await page.getByText('DES-2041').first().click();
await page.getByText('View purchase order').waitFor();
await page.waitForTimeout(800);
await page.screenshot({ path: `${OUT}/bill-received.png`, fullPage: true });

await browser.close();
console.log('Screenshots written to', OUT);
