/**
 * Playwright screenshot capture for README documentation.
 *
 * Usage:
 *   export NETGRAPHY_WEB_URL=https://web-staging-a5b7.up.railway.app
 *   export NETGRAPHY_USER=admin
 *   export NETGRAPHY_PASS=admin
 *   node scripts/screenshots/capture.mjs
 */

import { chromium } from "playwright";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const BASE_URL = process.env.NETGRAPHY_WEB_URL || "http://localhost:5173";
const USERNAME = process.env.NETGRAPHY_USER || "admin";
const PASSWORD = process.env.NETGRAPHY_PASS || "admin";
const OUTPUT_DIR = path.resolve(__dirname, "../../docs/assets/screenshots");

const VIEWPORT = { width: 1440, height: 900 };

async function screenshot(page, name) {
  const filepath = path.join(OUTPUT_DIR, `${name}.png`);
  await page.screenshot({ path: filepath, fullPage: false });
  console.log(`  Captured: ${name}.png`);
}

async function clickLink(page, text) {
  // Click a sidebar or navigation link by text, then wait for content
  try {
    await page.locator(`a:has-text("${text}")`).first().click();
    await page.waitForTimeout(3000);
  } catch (e) {
    console.log(`  Could not click "${text}": ${e.message}`);
  }
}

async function main() {
  console.log(`Capturing screenshots from ${BASE_URL}`);
  console.log(`Output: ${OUTPUT_DIR}\n`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: VIEWPORT });
  const page = await context.newPage();

  try {
    // Login via UI
    console.log("Logging in...");
    await page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1000);
    await page.fill("#username", USERNAME);
    await page.fill("#password", PASSWORD);
    await page.click('button[type="submit"]');
    // Wait for navigation away from login
    await page.waitForTimeout(6000);
    console.log(`  URL after login: ${page.url()}`);

    if (page.url().includes("/login")) {
      console.log("ERROR: Login failed. Check credentials.");
      await browser.close();
      process.exit(1);
    }

    // Dashboard (we should already be here)
    console.log("Capturing Dashboard...");
    await page.waitForTimeout(2000);
    await screenshot(page, "dashboard");

    // Schema Explorer — click sidebar link
    console.log("Capturing Schema Explorer...");
    await clickLink(page, "Schema");
    // If no Schema link in sidebar, try direct nav via address bar eval
    if (!page.url().includes("/schema")) {
      await page.evaluate(() => window.location.hash = "");
      await page.locator('a[href="/schema"]').first().click().catch(() => {});
      await page.waitForTimeout(3000);
    }
    await screenshot(page, "schema-explorer");

    // Device List
    console.log("Capturing Device List...");
    await clickLink(page, "Device");
    await screenshot(page, "device-list");

    // Device Detail — click first device link
    console.log("Capturing Device Detail...");
    try {
      await page.locator("a.font-medium").first().click();
      await page.waitForTimeout(3000);
    } catch (e) { /* ignore */ }
    await screenshot(page, "device-detail");

    // Report Builder
    console.log("Capturing Report Builder...");
    await clickLink(page, "Report Builder");
    await page.waitForTimeout(2000);
    // Select Device entity
    try {
      const sel = page.locator("select").first();
      await sel.selectOption({ label: "Device (Infrastructure)" });
      await page.waitForTimeout(2000);
      // Click some column buttons
      for (const col of ["Hostname", "Status", "Role"]) {
        await page.locator(`button:has-text("${col}")`).first().click().catch(() => {});
        await page.waitForTimeout(300);
      }
    } catch (e) { /* ignore */ }
    await screenshot(page, "report-builder");

    // Graph Explorer
    console.log("Capturing Graph Explorer...");
    await clickLink(page, "Graph Explorer");
    await screenshot(page, "graph-explorer");

    // Query Workbench
    console.log("Capturing Query Workbench...");
    await clickLink(page, "Query Workbench");
    await screenshot(page, "query-workbench");

    // AI Assistant — click AI button in header
    console.log("Capturing AI Assistant...");
    await clickLink(page, "Dashboard");
    await page.waitForTimeout(1000);
    try {
      await page.locator('button:has-text("AI")').first().click();
      await page.waitForTimeout(1500);
    } catch (e) { /* ignore */ }
    await screenshot(page, "ai-assistant");

    // Documentation
    console.log("Capturing Documentation...");
    await clickLink(page, "Documentation");
    await screenshot(page, "documentation");

    // AI Configuration
    console.log("Capturing AI Configuration...");
    await clickLink(page, "AI Configuration");
    await screenshot(page, "ai-config");

    console.log("\nDone! All screenshots saved to docs/assets/screenshots/");

  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error("Screenshot capture failed:", err);
  process.exit(1);
});
