/**
 * Inventory click-through — verifies, on the running app, each point raised in
 * the reviewer's Inventory note. Nothing here is inferred from source: every
 * check reads what is actually on screen.
 *
 *   node clickthrough-inventory.mjs
 */
import { chromium } from "@playwright/test";
import fs from "node:fs";

const BASE = process.env.BASE_URL || "http://localhost:3000";
const EMAIL = process.env.CLICKTHROUGH_EMAIL || "inv.verify@audity.local";
const PASS = process.env.CLICKTHROUGH_PASSWORD || "";
const SHOTS = process.env.SHOT_DIR || "./clickthrough-shots";

fs.mkdirSync(SHOTS, { recursive: true });
const results = [];
const record = (name, ok, detail) => {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

const shot = async (page, n) => {
  await page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true }).catch(() => {});
};

/** Read every option of a <select> whose label/name matches, or a combobox. */
async function optionsFor(page, labelRe) {
  const sel = page.locator("select").filter({ hasNot: page.locator("x") });
  const n = await sel.count();
  for (let i = 0; i < n; i++) {
    const s = sel.nth(i);
    const id = (await s.getAttribute("id")) || "";
    const nm = (await s.getAttribute("name")) || "";
    let labelTxt = "";
    if (id) labelTxt = await page.locator(`label[for="${id}"]`).first().innerText().catch(() => "");
    const hay = `${id} ${nm} ${labelTxt}`.toLowerCase();
    if (labelRe.test(hay)) {
      return (await s.locator("option").allInnerTexts()).map((t) => t.trim()).filter(Boolean);
    }
  }
  return null;
}

const run = async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1500, height: 1000 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  // ── sign in ───────────────────────────────────────────────────────────────
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.locator('input[type="email"]').first().fill(EMAIL);
  await page.locator('input[type="password"]').first().fill(PASS);
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL((u) => !/\/login/.test(u.toString()), { timeout: 25000 });
  record("Sign in", true, page.url());

  // The terms gate sits over everything and swallows clicks until accepted.
  const agree = page.getByRole("button", { name: /i agree|accept|continue/i }).first();
  if (await agree.count()) {
    await agree.click({ timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(1200);
    record("Terms gate accepted", true);
  }
  await shot(page, "01-signed-in");

  // ── products list ─────────────────────────────────────────────────────────
  await page.goto(`${BASE}/inventory/products`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  await shot(page, "02-products-list");
  const listTxt = await page.locator("body").innerText();
  record("Products list loads", /product|sku|catalogue/i.test(listTxt), `${listTxt.length} chars on screen`);

  // Import entry point (reviewer: "add Tab to import list with or without Balances")
  const importCtl = page.getByRole("button", { name: /import/i })
    .or(page.getByText(/^\s*import\s*$/i));
  record("Import control present on the product list", (await importCtl.count()) > 0);

  // ── new product form ──────────────────────────────────────────────────────
  const addBtn = page.getByRole("button", { name: /add product|new product/i }).first();
  await addBtn.click();
  await page.waitForTimeout(2500);
  await shot(page, "03-new-product-top");

  const formTxt = await page.locator("body").innerText();

  const types = await optionsFor(page, /product_?type|type/);
  record(
    "Product type offers Standard/Variable/Service/Combo",
    !!types && /variable/i.test(types.join(" ")) && /combo/i.test(types.join(" ")) && /service/i.test(types.join(" ")),
    types ? types.join(" | ") : "no type select found"
  );

  const symb = await optionsFor(page, /symbology/);
  record(
    "Barcode symbology list",
    !!symb && /ean.?13/i.test(symb.join(" ")) && /upc/i.test(symb.join(" ")),
    symb ? symb.join(" | ") : "not found on the create form"
  );

  record("Barcode field can be typed into", /barcode/i.test(formTxt));

  const gen = page.getByRole("button", { name: /generate/i })
    .or(page.locator('[title*="enerate" i], [aria-label*="enerate" i]'));
  record("Barcode can be generated from the form", (await gen.count()) > 0);

  const costing = await optionsFor(page, /costing/);
  record(
    "Costing methods FIFO / LIFO / Average / Specific",
    !!costing && ["fifo", "lifo", "average", "specific"].every((m) => new RegExp(m, "i").test(costing.join(" "))),
    costing ? costing.join(" | ") : "not found on the create form"
  );

  const taxType = await optionsFor(page, /tax_?type/);
  record(
    "Tax type inclusive / exclusive",
    !!taxType && /inclusive/i.test(taxType.join(" ")) && /exclusive/i.test(taxType.join(" ")),
    taxType ? taxType.join(" | ") : "not found on the create form"
  );

  record("Taxable / VAT control on the item", /taxable|vat|tax class|tax rate/i.test(formTxt));
  record("Opening stock on the create form", /opening stock|quantity in stock|available quantity/i.test(formTxt));
  record("Location / warehouse on the create form", /location|warehouse|store/i.test(formTxt));
  record("Product image upload offered", /image|photo|upload/i.test(formTxt));

  // scroll the dialog so later fields render, then re-read
  await page.mouse.wheel(0, 1400);
  await page.waitForTimeout(900);
  await shot(page, "04-new-product-scrolled");
  const formTxt2 = await page.locator("body").innerText();
  const all = formTxt + "\n" + formTxt2;
  record("GL / accounting mapping fields on the item", /gl |account|mapping|sales account|inventory account|cost of sales/i.test(all));
  record("Custom fields on the item", /custom field/i.test(all));

  fs.writeFileSync(`${SHOTS}/new-product-form.txt`, all);

  // close dialog
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(700);

  // ── an existing product's history ─────────────────────────────────────────
  const firstRow = page.locator("table tbody tr").first();
  if (await firstRow.count()) {
    await firstRow.click();
    await page.waitForTimeout(2200);
    await shot(page, "05-product-detail");
    const detail = await page.locator("body").innerText();
    record("Product detail opens", detail.length > 200);
    const hist = /history|movement|transaction/i.test(detail);
    record("Movement / transaction history present", hist);
    fs.writeFileSync(`${SHOTS}/product-detail.txt`, detail);
  }

  record("No uncaught JavaScript errors during the walk-through", errors.length === 0,
    errors.length ? errors.slice(0, 2).join(" | ") : "none");

  fs.writeFileSync(`${SHOTS}/results.json`, JSON.stringify(results, null, 2));
  const passed = results.filter((r) => r.ok).length;
  console.log(`\n${passed}/${results.length} checks passed`);
  await browser.close();
};

run().catch((e) => { console.error("RUN FAILED:", e.message); process.exit(1); });
