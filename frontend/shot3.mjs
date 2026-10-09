import { chromium } from "@playwright/test";
const S = process.argv[2], level = process.argv[3], seed = process.argv[4], W = Number(process.argv[5] ?? 1480), H = Number(process.argv[6] ?? 900);
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: W, height: H } });
p.on("pageerror", (e) => console.log("PAGEERROR", e.message));
await p.goto("http://127.0.0.1:8765/#/desk");
await p.fill("#seed", seed);
await p.getByRole("button", { name: "Start" }).nth(Number(level) - 1).click();
await p.waitForSelector(".desk");
let n = 0;
const tag = `${W}x${H}-L${level}`;
for (let i = 0; i < 40; i++) {
  await p.waitForTimeout(250);
  if (await p.locator(".debrief").count()) break;
  const title = (await p.locator(".panel-h h2").allTextContents()).join("|");
  if (await p.locator(".is-result").count()) { await p.screenshot({ path: `${S}/${tag}-${String(++n).padStart(2, "0")}-result.png` }); await p.locator(".continue-row .btn-primary").click(); continue; }
  await p.screenshot({ path: `${S}/${tag}-${String(++n).padStart(2, "0")}-decision.png` });
  if (title.includes("CALCULATION")) await p.fill("input[aria-label='your answer']", "0");
  if (title.includes("HEDGE")) { await p.getByRole("button", { name: "100%" }).click(); await p.waitForTimeout(400); }
  await p.getByRole("button", { name: /Review/ }).click();
  await p.getByRole("button", { name: /Commit/ }).click();
  await p.waitForTimeout(300);
}
await b.close();
