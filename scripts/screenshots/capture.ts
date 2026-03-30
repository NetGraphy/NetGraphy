/**
 * Playwright screenshot capture for README documentation.
 *
 * Captures key UI screens from a running NetGraphy instance.
 * Requires: npx playwright install chromium
 *
 * Usage:
 *   export NETGRAPHY_WEB_URL=https://web-staging-a5b7.up.railway.app
 *   export NETGRAPHY_USER=admin
 *   export NETGRAPHY_PASS=admin
 *   npx playwright test scripts/screenshots/capture.ts
 *
 * Or run directly:
 *   npx ts-node scripts/screenshots/capture.ts
 */

import { chromium, type Page, type Browser } from "playwright";
import * as path from "path";

const BASE_URL = process.env.NETGRAPHY_WEB_URL || "http://localhost:5173";
const USERNAME = process.env.NETGRAPHY_USER || "admin";
const PASSWORD = process.env.NETGRAPHY_PASS || "admin";
const OUTPUT_DIR = path.resolve(__dirname, "../../docs/assets/screenshots");

const VIEWPORT = { width: 1440, height: 900 };

async function login(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[name="username"], input[type="text"]', USERNAME);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL("**/", { timeout: 10000 });
  // Wait for dashboard to load
  await page.waitForTimeout(2000);
}

async function capture(page: Page, name: string, url?: string): Promise<void> {
  if (url) {
    await page.goto(`${BASE_URL}${url}`);
    await page.waitForTimeout(3000); // Let data load
  }
  const filepath = path.join(OUTPUT_DIR, `${name}.png`);
  await page.screenshot({ path: filepath, fullPage: false });
  console.log(`  Captured: ${filepath}`);
}

async function main(): Promise<void> {
  console.log(`Capturing screenshots from ${BASE_URL}`);
  console.log(`Output: ${OUTPUT_DIR}\n`);

  const browser: Browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: VIEWPORT });
  const page = await context.newPage();

  try {
    // Login
    console.log("Logging in...");
    await login(page);

    // Dashboard
    console.log("Capturing Dashboard...");
    await capture(page, "dashboard", "/");

    // Schema Explorer
    console.log("Capturing Schema Explorer...");
    await capture(page, "schema-explorer", "/schema");

    // Graph Explorer
    console.log("Capturing Graph Explorer...");
    await page.goto(`${BASE_URL}/graph`);
    await page.waitForTimeout(2000);
    // Try to trigger a graph load if possible
    await capture(page, "graph-explorer");

    // Query Workbench
    console.log("Capturing Query Workbench...");
    await page.goto(`${BASE_URL}/query`);
    await page.waitForTimeout(2000);
    await capture(page, "query-workbench");

    // Report Builder — select Device entity
    console.log("Capturing Report Builder...");
    await page.goto(`${BASE_URL}/reports`);
    await page.waitForTimeout(2000);
    // Select Device from entity dropdown
    const entitySelect = page.locator("select").first();
    await entitySelect.selectOption({ label: /Device/i }).catch(() => {});
    await page.waitForTimeout(2000);
    await capture(page, "report-builder");

    // AI Assistant — open chat panel
    console.log("Capturing AI Assistant...");
    await page.goto(`${BASE_URL}/`);
    await page.waitForTimeout(1000);
    // Click AI button in header
    const aiButton = page.locator("text=AI").first();
    await aiButton.click().catch(() => {});
    await page.waitForTimeout(1000);
    await capture(page, "ai-assistant");

    // Documentation
    console.log("Capturing Documentation...");
    await capture(page, "documentation", "/docs");

    // AI Configuration
    console.log("Capturing AI Configuration...");
    await capture(page, "ai-config", "/admin/ai");

    // Device List
    console.log("Capturing Device List...");
    await capture(page, "device-list", "/objects/Device");

    // Device Detail (first device)
    console.log("Capturing Device Detail...");
    await page.goto(`${BASE_URL}/objects/Device`);
    await page.waitForTimeout(2000);
    const firstLink = page.locator("a.font-medium").first();
    await firstLink.click().catch(() => {});
    await page.waitForTimeout(2000);
    await capture(page, "device-detail");

    console.log("\nDone! All screenshots saved to docs/assets/screenshots/");

  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error("Screenshot capture failed:", err);
  process.exit(1);
});
