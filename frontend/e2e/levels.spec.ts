// Levels 3-5 through the real server and the real episode engine, driven the way a trader would: the ticket, arm, commit, the result, Continue.
import { expect, test, type Page } from "@playwright/test";

async function start(page: Page, level: number, seed: number) {
  await page.goto("/#/desk");
  await page.fill("#seed", String(seed));
  await page.getByRole("button", { name: "Start" }).nth(level - 1).click();
  await page.waitForSelector(".desk");
}
const titles = async (page: Page) => (await page.locator(".panel-h h2").allTextContents()).map((t) => t.trim());
const body = (page: Page) => page.locator(".desk").innerText();

type Strategy = (page: Page, t: string[], n: number) => Promise<void>;

/** Answer whatever the screen asks, with the strategy for hedge-like prompts, then arm, commit and wait for the result. */
async function decide(page: Page, hedge: Strategy, n = 0) {
  const t = await titles(page);
  if (t.includes("CALCULATION CHECK")) await page.fill("input[aria-label='your answer']", "0");
  else if (t.includes("HEDGE") || t.includes("POSITION")) await hedge(page, t, n);
  await page.getByRole("button", { name: /Review/ }).click();
  await expect(page.getByRole("button", { name: /Commit/ })).toBeVisible();
  await page.getByRole("button", { name: /Commit/ }).click();
  await expect(page.locator(".result").first()).toBeVisible();
}
const cont = async (page: Page) => { await page.locator(".continue-row .btn-primary").click(); await page.waitForTimeout(120); };
const noTrade = async (page: Page) => { await page.getByRole("button", { name: /^(No trade|Keep)/ }).click(); };
const helperOrNone: (name: string | RegExp) => Strategy = (name) => async (page) => {
  await page.getByRole("button", { name }).click();
  await page.waitForTimeout(300);
  if ((await page.locator(".leg").count()) === 0) await noTrade(page);
};

/** Play to the debrief. `each` sees every decision screen and result screen. */
async function play(page: Page, hedge: Strategy, each?: (page: Page, state: "decision" | "result", t: string[]) => Promise<void>) {
  const posts: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST") posts.push(new URL(r.url()).pathname.replace(/^\/api\/desk\/[0-9a-f]+/, "")); });
  let n = 0, continues = 0;
  for (let i = 0; i < 20 && (await page.locator(".debrief").count()) === 0; i++) {
    await expect(page.locator(".is-decision, .debrief").first()).toBeVisible();      // the next screen has arrived (or the debrief)
    if ((await page.locator(".debrief").count()) > 0) break;
    if (each) await each(page, "decision", await titles(page));
    const before = posts.length;
    await decide(page, hedge, n++);
    expect(posts.slice(before).filter((p) => p === "/continue"), "the next observation is not asked for before Continue").toHaveLength(0);
    if (each) await each(page, "result", await titles(page));
    await cont(page);
    continues++;
  }
  await expect(page.locator(".strip4")).toBeVisible();
  expect(posts.filter((p) => p === "/continue")).toHaveLength(continues);            // exactly one Continue per result, each pressed by the trainee
  return posts;
}

test("level 3: a curve book from price to debrief: ladder, bucket risk, flatten, par change by tenor, the slope check", async ({ page }) => {
  await start(page, 3, 1);
  const seen = { ladder: false, bucket: false, par: false, request: false, flatten: false };
  await play(page, helperOrNone("Flatten"), async (p, state, t) => {
    if (state === "decision") {
      if (t.includes("SWAP LADDER") && t.includes("RISK")) seen.ladder = true;
      if ((await p.getByText("DV01 BY BUCKET").count()) > 0) seen.bucket = true;
      if (t.includes("THE REQUEST")) seen.request = true;
      if (t.includes("HEDGE") && (await p.getByRole("button", { name: "Flatten" }).count()) > 0) seen.flatten = true;
      expect(await body(p)).not.toMatch(/DV01 after your decision/);                  // nothing of the decision's effect before the commit
    } else if ((await p.getByText("PAR CHANGE BY TENOR").count()) > 0) {
      seen.par = true;
      await expect(p.locator(".bars-row")).not.toHaveCount(0);
      await expect(p.getByText(/DV01 after your decision/)).toBeVisible();            // revealed by the result
    }
  });
  expect(seen).toEqual({ ladder: true, bucket: true, par: true, request: true, flatten: true });
  await expect(page.getByText("LEVEL AND SLOPE BY ROUND")).toBeVisible();
});

test("level 4: hedge with a future, see the carry overnight, switch the hedge into swaps in the morning", async ({ page }) => {
  await start(page, 4, 1);
  const seen = { products: false, spreadRisk: false, close: false, carry: false, switched: false, newFuture: false };
  const strategy: Strategy = async (p, t, n) => {
    if (n === 1 || n === 2) {                                                         // the first hedge (n=0 is the price, n=1 the calculation check)
      const row = p.locator("table.products-menu tr", { hasText: "FGBL" });
      await row.getByRole("button", { name: "Sell" }).click();
      await p.locator("input[aria-label='size, contracts']").fill("1500");
    } else if ((await p.getByRole("button", { name: "Switch to swaps" }).count()) > 0 && (await p.getByRole("button", { name: "Switch to swaps" }).isEnabled())) {
      await p.getByRole("button", { name: "Switch to swaps" }).click();
      await expect(p.locator(".leg").first()).toBeVisible();
      seen.switched = true;
    } else await noTrade(p);
    void t;
  };
  await play(page, strategy, async (p, state, t) => {
    if (state === "decision") {
      if (t.includes("FUTURES AND BOND")) seen.products = true;
      if ((await p.getByText("Swap spread").count()) > 0) seen.spreadRisk = true;
      if (t.includes("THE CLOSE")) seen.close = true;
    } else {
      if (t.includes("OVERNIGHT: CARRY, ROLL AND FUNDING")) seen.carry = true;
      if ((await p.locator(".row-new", { hasText: "FGBL" }).count()) > 0) seen.newFuture = true;
    }
  });
  expect(seen).toEqual({ products: true, spreadRisk: true, close: true, carry: true, switched: true, newFuture: true });
});

test("level 5: the research view, named clients, the release and the limit cut, the position decision, and no hidden state anywhere live; the debrief reveals it", async ({ page }) => {
  const live: string[] = [];
  page.on("response", async (r) => { const u = new URL(r.url()).pathname; if (u.startsWith("/api/desk/") && !u.endsWith("/debrief") && !u.endsWith("/record")) live.push(await r.text().catch(() => "")); });
  await start(page, 5, 1);
  const seen = { room: false, evidence: false, release: false, cut: false, position: false };
  const strategy: Strategy = async (p, t) => {
    if (t.includes("POSITION")) {
      seen.position = true;
      await p.getByRole("button", { name: "target 50k higher" }).click();
      await p.getByRole("button", { name: "Set", exact: true }).click();
      await expect(p.locator(".leg").first()).toBeVisible();
      await expect(p.getByText(/DV01 after your decision/)).toHaveCount(0);
    } else await noTrade(p);
  };
  await play(page, strategy, async (p, _state, t) => {
    const text = await body(p);
    expect(text, "no hidden state on a live screen or result").not.toMatch(/P\(informed|posterior|informed client|signal truth/i);
    if (t.includes("READ THE ROOM")) seen.room = true;
    if ((await p.getByText("NAMED CLIENTS TODAY").count()) > 0) seen.evidence = true;
    if (/release ×3/i.test(text)) seen.release = true;
    if (/Risk management cuts your limits/.test(text)) seen.cut = true;
  });
  expect(seen).toEqual({ room: true, evidence: true, release: true, cut: true, position: true });
  const blob = live.join("\n");
  for (const k of ["p_informed", "\"informed\"", "posteriors", "view_truth", "evidence_vs_truth", "signal_right", "market_paths"]) expect(blob, k).not.toContain(k);
  await expect(page.getByText("INFORMATION, NOW REVEALED")).toBeVisible();
  await expect(page.getByText(/Model's P\(informed\)/)).toBeVisible();
  await expect(page.getByRole("img", { name: /distribution of P&L over simulated market paths/ })).toBeVisible({ timeout: 30_000 });
});

test("a reload on a level 4 result lands on the result, never past it", async ({ page }) => {
  await start(page, 4, 2);
  await decide(page, async (p) => noTrade(p));
  await cont(page);
  await decide(page, async (p) => noTrade(p));                                         // the calculation check
  await page.reload();
  await expect(page.locator(".result").first()).toBeVisible();
  await expect(page.getByLabel("your answer")).toHaveCount(0);
});

for (const level of [3, 4, 5]) {
  for (const [w, h] of [[1280, 720], [1920, 1080]] as const) {
    test(`level ${level} fills a ${w}x${h} window in decision and result states`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: h });
      await start(page, level, 1);
      const check = async (state: string) => {
        const m = await page.evaluate(() => {
          const cols = [...document.querySelectorAll(".desk-main > .col")].map((c) => {
            const kids = [...c.children].map((k) => k.getBoundingClientRect().bottom);
            return { bottom: Math.max(...kids), colBottom: c.getBoundingClientRect().bottom };
          });
          return { cols, tapeBottom: document.querySelector(".tape")!.getBoundingClientRect().bottom, scrollH: document.documentElement.scrollHeight, inner: window.innerHeight, over: document.querySelector(".topbar")!.scrollWidth > document.querySelector(".topbar")!.clientWidth + 1 };
        });
        expect(m.scrollH, `${state}: the page itself does not scroll`).toBeLessThanOrEqual(m.inner + 1);
        expect(Math.abs(m.tapeBottom - m.inner), `${state}: the tape sits at the bottom edge`).toBeLessThan(2);
        expect(m.over, `${state}: the top bar fits on one line`).toBe(false);
        for (const c of m.cols) expect(c.colBottom - c.bottom, `${state}: a column stops short of the bottom`).toBeLessThan(28);
      };
      const hedge: Strategy = async (p) => noTrade(p);
      for (let i = 0; i < 6; i++) {
        await expect(page.locator(".is-decision")).toBeVisible();
        const t = await titles(page);
        await check(t.includes("HEDGE") ? "hedge decision" : "decision");
        await decide(page, hedge, i);
        await check("result");
        await cont(page);
      }
    });
  }
}
