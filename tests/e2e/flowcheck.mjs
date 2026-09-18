import { chromium } from "@playwright/test";
const BASE="http://localhost:3000", SHOTS=process.env.SHOT_DIR;
const b = await chromium.launch();
const p = await (await b.newContext({viewport:{width:1500,height:1000}})).newPage();
await p.goto(`${BASE}/login`,{waitUntil:"domcontentloaded"});
await p.locator('input[type="email"]').first().fill(process.env.CLICKTHROUGH_EMAIL || "inv.verify@audity.local");
await p.locator('input[type="password"]').first().fill(process.env.CLICKTHROUGH_PASSWORD || "");
await p.locator('button[type="submit"]').first().click();
await p.waitForURL(u=>!/\/login/.test(u.toString()),{timeout:25000});
await p.goto(`${BASE}/inventory/products`,{waitUntil:"domcontentloaded"});
await p.waitForTimeout(2500);

// 1. Create a product WITH opening stock, so history can be checked afterwards.
await p.getByRole("button",{name:/add product/i}).first().click();
await p.waitForTimeout(2000);
const sku = "VERIFY-" + Date.now().toString().slice(-6);
await p.locator('input[placeholder*="SVC-001"]').first().fill(sku);
await p.locator('input[placeholder*="Consulting"]').first().fill("Opening Stock Verify Item");
await p.locator('input[placeholder="5,500.00"]').first().fill("1000");
await p.locator('input[placeholder="8,500.00"]').first().fill("1500");
await p.locator('input[placeholder="0"]').first().fill("25");        // Quantity in Stock
const loc = p.locator('select').filter({hasText:/Select location/}).first();
if (await loc.count()) { const o = await loc.locator("option").nth(1).getAttribute("value").catch(()=>null); if(o) await loc.selectOption(o).catch(()=>{}); }
await p.screenshot({path:`${SHOTS}/create-filled.png`,fullPage:true});
await p.getByRole("button",{name:/^create product$/i}).first().click();
await p.waitForTimeout(4000);
await p.screenshot({path:`${SHOTS}/after-create.png`,fullPage:true});
const listTxt = await p.locator("body").innerText();
console.log("created & visible in list:", listTxt.includes(sku) || listTxt.includes("Opening Stock Verify"));

// 2. Open it and look for opening-stock history
const row = p.getByText("Opening Stock Verify Item").first();
if (await row.count()) {
  await row.click().catch(()=>{});
  await p.waitForTimeout(3000);
  await p.screenshot({path:`${SHOTS}/product-detail.png`,fullPage:true});
  const t = await p.locator("body").innerText();
  console.log("detail mentions Opening:", /opening/i.test(t));
  console.log("detail mentions history/movement:", /history|movement/i.test(t));
}

// 3. Import screen — does it take opening balances?
await p.goto(`${BASE}/inventory/products`,{waitUntil:"domcontentloaded"});
await p.waitForTimeout(2000);
const imp = p.getByRole("button",{name:/import/i}).first();
console.log("import control found:", await imp.count() > 0);
if (await imp.count()) {
  await imp.click().catch(()=>{});
  await p.waitForTimeout(2500);
  await p.screenshot({path:`${SHOTS}/import.png`,fullPage:true});
  const t = await p.locator("body").innerText();
  console.log("import screen mentions opening stock:", /opening[_ ]?stock|quantity|balance/i.test(t));
  console.log("import screen mentions warehouse/location:", /warehouse|location/i.test(t));
}
await b.close();
