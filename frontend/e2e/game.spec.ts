import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// MARKET MAKING GAME against the REAL server and engine (no mock): the server runs on a private port with a private history directory (see playwright.config.ts).

type Mkt = { id: string; status: string; kind: string; range: [number, number]; tick: number; decimals: number; quote: unknown };
type St = { phase: string; round: number; markets: Mkt[] };

const gameId = (page: Page) => page.evaluate(() => sessionStorage.getItem("rates-game.id")!);
const state = async (page: Page, request: APIRequestContext): Promise<St> => (await request.get(`/api/mmgame/${await gameId(page)}`)).json();

async function deal(page: Page, level: number, seed: string, extra?: (p: Page) => Promise<void>) {
  await page.goto("/#/game");
  await page.getByRole("radio", { name: new RegExp(`LEVEL ${level}`) }).click();
  await page.getByLabel("seed").fill(seed);
  if (extra) await extra(page);
  await page.getByRole("button", { name: "Deal the table" }).click();
  await page.getByTestId("game-table").waitFor();
}

/** Type a market into every open market that has none yet (a third of the way up its range, two ticks each side). */
async function quoteMissing(page: Page, request: APIRequestContext) {
  const st = await state(page, request);
  for (const m of st.markets) {
    if (m.status === "upcoming" || m.status === "resolved" || m.quote) continue;
    const mid = m.range[0] + (m.range[1] - m.range[0]) * (m.kind === "world" ? 0.5 : 0.3);
    const b = Math.round(mid / m.tick) * m.tick;
    await page.getByLabel(`${m.id} bid`).fill((b - 2 * m.tick).toFixed(m.decimals));
    await page.getByLabel(`${m.id} offer`).fill((b + 2 * m.tick).toFixed(m.decimals));
  }
}

async function playRound(page: Page, request: APIRequestContext) {
  const before = (await state(page, request)).round;
  await quoteMissing(page, request);
  await page.getByTestId("advance").click();
  await expect.poll(async () => (await state(page, request)).round).toBe(before + 1);
}

test("the game is a top-level area in the shell and opens on its lobby", async ({ page }) => {
  await page.goto("/#/train");
  await page.getByRole("button", { name: /MARKET MAKING GAME/ }).click();
  await expect(page).toHaveURL(/#\/game$/);
  await expect(page.getByRole("heading", { name: "MARKET MAKING GAME" })).toBeVisible();
  await expect(page.getByRole("radio", { name: /LEVEL 1/ })).toBeVisible();
  await expect(page.getByRole("radio", { name: /LEVEL 3/ })).toBeVisible();
});

test("a whole level 1 game through the browser: quote, play every round, resolve, debrief", async ({ page, request }) => {
  const seen: string[] = [];
  page.on("response", async (r) => { if (r.url().includes("/api/mmgame") && !r.url().endsWith("/debrief")) seen.push(await r.text().catch(() => "")); });
  await deal(page, 1, "2");
  await expect(page.getByLabel("round")).toHaveText("1 / 8");
  expect(await page.locator("li.mk").count()).toBe(3);
  for (let r = 0; r < 8; r++) {
    if (r < 7) await playRound(page, request);
    else { await quoteMissing(page, request); await page.getByTestId("advance").click(); }
  }
  const deb = page.getByTestId("game-debrief");
  await expect(deb).toBeVisible();
  const id = await page.evaluate(() => sessionStorage.getItem("rates-game.id"));
  expect(id).toBeNull();                                                                       // a finished game is no longer "the current table"
  await expect(deb.getByText("WHERE THE P&L CAME FROM")).toBeVisible();
  await expect(deb.getByText(/seed 2 /)).toBeVisible();
  await expect(deb.getByText("COUNTERPARTIES REVEALED")).toBeVisible();
  // hidden information never crossed the wire during play
  const wire = seen.join("\n");
  expect(wire).not.toMatch(/"seed"|"tape"|"shock_plan"|"informed"|"fair_hist"|"final_fair"/);
  // the on-screen total equals the server's debrief, and total = decision result + luck
  const list = (await (await request.get("/api/mmgame")).json()).games as { id: string; done: boolean; pnl: number }[];
  const g = list.find((x) => x.done)!;
  const d = await (await request.get(`/api/mmgame/${g.id}/debrief`)).json();
  expect(d.totals.pnl).toBeCloseTo(g.pnl, 6);
  expect(d.totals.pnl).toBeCloseTo(d.totals.decision_result + d.totals.luck, 6);
  const shown = (await deb.getByLabel("final pnl").textContent())!.replace(/[^\d−+-]/g, "").replace("−", "-");
  expect(Number(shown)).toBe(Math.round(d.totals.pnl));
});

test("reloading in the middle of a game lands on the same table, with the same positions and round", async ({ page, request }) => {
  await deal(page, 2, "31");
  await playRound(page, request);
  await playRound(page, request);
  const before = await state(page, request);
  await page.reload();
  await page.getByTestId("game-table").waitFor();
  await expect(page.getByLabel("round")).toHaveText(`${before.round + 1} / 12`);
  const after = await state(page, request);
  expect(after).toEqual(before);
});

test("level 3: many markets at once, shocks that flag markets, acknowledge, pause, and the risk budget", async ({ page, request }) => {
  await deal(page, 3, "4");
  expect(await page.locator("li.mk").count()).toBeGreaterThanOrEqual(5);
  await expect(page.locator("[role=meter][aria-label='Risk budget']")).toBeVisible();
  let shocked = 0;
  for (let r = 0; r < 6 && !shocked; r++) {
    await playRound(page, request);
    shocked = await page.getByText("SHOCKED", { exact: true }).count();
  }
  expect(shocked).toBeGreaterThan(0);
  await expect(page.getByRole("status").filter({ hasText: /shocked\./ })).toBeVisible();
  const card = page.locator("li.mk-shocked").first();
  const id = (await card.locator(".mk-id").first().textContent())!.trim();
  await card.locator("button.mk-head").click();
  await expect(page.getByRole("complementary").getByText(/RULE CHANGE|NEW INFORMATION|RESOLUTION CHANGE/).first()).toBeVisible();
  await card.getByRole("button", { name: "Acknowledge" }).click();
  await expect(page.locator(`li[aria-label='${id} shocked']`)).toHaveCount(0);
  // pause one market: it is labelled, and gets no flow
  const act = page.locator("li.mk-active").first();
  const aid = (await act.locator(".mk-id").first().textContent())!.trim();
  await act.getByRole("button", { name: "Pause" }).click();
  await expect(page.locator(`li[aria-label='${aid} paused']`)).toBeVisible();
  await page.getByRole("button", { name: "Resume all" }).click();
  await expect(page.locator("li.mk-paused")).toHaveCount(0);
  // resolved markets are shown as such, and do not block the others
  for (let r = 0; r < 14 && (await page.locator("li.mk-resolved").count()) === 0; r++) {
    if ((await state(page, request)).phase === "done") break;
    await playRound(page, request);
  }
  expect(await page.locator("li.mk-resolved").count()).toBeGreaterThan(0);
});

test("a refused quote shows the server's reason and nothing changes", async ({ page, request }) => {
  await deal(page, 1, "5");
  await page.getByLabel("M1 bid").fill("5000000");
  await page.getByLabel("M1 offer").fill("5000001");
  await page.getByTestId("advance").click();
  await expect(page.getByRole("alert")).toContainText("M1");
  expect((await state(page, request)).round).toBe(0);
});

test("TRAIN and LIVE DESK are untouched by the game: same catalogue, same history, still working", async ({ page, request }) => {
  const before = { train: await (await request.get("/api/train/history")).json(), review: await (await request.get("/api/review/sessions")).json(), cat: (await (await request.get("/api/catalogue")).json()).train.sources };
  await deal(page, 1, "9");
  await playRound(page, request);
  await page.goto("/#/train");
  await expect(page.getByText(new RegExp(`${before.cat} question sources in 10 tracks`))).toBeVisible();
  await page.goto("/#/desk");
  await expect(page.getByText("choose a level")).toBeVisible();
  expect(await (await request.get("/api/train/history")).json()).toEqual(before.train);
  expect(await (await request.get("/api/review/sessions")).json()).toEqual(before.review);
  await page.goto("/#/review");
  await expect(page.getByText("REVIEW", { exact: true }).first()).toBeVisible();
});
