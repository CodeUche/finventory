/**
 * Reads the New Product dialog itself — every field label and every dropdown's
 * options — by scrolling the dialog's own scroll container rather than the page.
 */
import { chromium } from "@playwright/test";
import fs from "node:fs";

const BASE = process.env.BASE_URL || "http://localhost:3000";
const SHOTS = process.env.SHOT_DIR || "./shots";
fs.mkdirSync(SHOTS, { recursive: true });

const run = async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1500, height: 1000 } })).newPage();

  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.locator('input[type="email"]').first().fill(process.env.CLICKTHROUGH_EMAIL || "inv.verify@audity.local");
  await page.locator('input[type="password"]').first().fill(process.env.CLICKTHROUGH_PASSWORD || "");
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL((u) => !/\/login/.test(u.toString()), { timeout: 25000 });

  await page.goto(`${BASE}/inventory/products`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  await page.getByRole("button", { name: /add product/i }).first().click();
  await page.waitForTimeout(2500);

  // The dialog is the element containing the "New Product" heading.
  const dialog = page.locator('div').filter({ hasText: /^New Product/ }).last();

  // Find the actual scrolling element inside the dialog and walk it to the bottom,
  // screenshotting as we go, so late fields are rendered and captured.
  const scrollInfo = await page.evaluate(() => {
    const cands = Array.from(document.querySelectorAll("div"))
      .filter((d) => d.scrollHeight > d.clientHeight + 40 && d.clientHeight > 200);
    const el = cands[cands.length - 1];
    if (!el) return null;
    el.setAttribute("data-scroller", "1");
    return { scrollHeight: el.scrollHeight, clientHeight: el.clientHeight };
  });
  console.log("scroller:", JSON.stringify(scrollInfo));

  const texts = [];
  const steps = scrollInfo ? Math.ceil(scrollInfo.scrollHeight / (scrollInfo.clientHeight * 0.8)) : 1;
  for (let i = 0; i < Math.min(steps + 1, 8); i++) {
    texts.push(await dialog.innerText().catch(() => ""));
    await page.screenshot({ path: `${SHOTS}/form-${String(i).padStart(2, "0")}.png` });
    await page.evaluate((n) => {
      const el = document.querySelector('[data-scroller="1"]');
      if (el) el.scrollTop = el.clientHeight * 0.8 * (n + 1);
    }, i);
    await page.waitForTimeout(700);
  }

  // Every dropdown inside the dialog, with its label and options.
  const selects = await page.evaluate(() => {
    const root = document.querySelector('[data-scroller="1"]')?.closest("div") || document;
    return Array.from(root.querySelectorAll("select")).map((s) => {
      let label = "";
      if (s.id) label = document.querySelector(`label[for="${s.id}"]`)?.innerText || "";
      if (!label) {
        const prev = s.closest("div")?.previousElementSibling;
        label = prev?.innerText || s.closest("div")?.querySelector("label")?.innerText || "";
      }
      return { label: (label || s.name || s.id || "?").trim().split("\n")[0],
               options: Array.from(s.options).map((o) => o.text.trim()) };
    });
  });

  const all = [...new Set(texts.join("\n").split("\n").map((l) => l.trim()).filter(Boolean))].join("\n");
  fs.writeFileSync(`${SHOTS}/dialog-text.txt`, all);
  fs.writeFileSync(`${SHOTS}/dialog-selects.json`, JSON.stringify(selects, null, 2));

  console.log("\n=== DROPDOWNS ON THE NEW PRODUCT FORM ===");
  for (const s of selects) console.log(`  ${s.label}: ${s.options.join(" | ").slice(0, 160)}`);
  console.log("\n=== FIELD LABELS SEEN ===");
  console.log(all.slice(0, 2200));

  await browser.close();
};
run().catch((e) => { console.error("FAILED:", e.message); process.exit(1); });
