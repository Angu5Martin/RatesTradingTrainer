import { expect, test, type Page } from "@playwright/test";

async function start(page: Page, level: number, seed: number) {
  await page.goto("/#/desk");
  await page.fill("#seed", String(seed));
  await page.getByRole("button", { name: "Start" }).nth(level - 1).click();
  await page.waitForSelector(".desk");
}

/** Take whatever decision the screen asks for with the simplest valid input, then arm and commit. */
async function decide(page: Page) {
  const titles = (await page.locator(".panel-h h2").allTextContents()).join("|");
  if (titles.includes("CALCULATION")) await page.fill("input[aria-label='your answer']", "0");
  if (titles.includes("HEDGE")) { await page.getByRole("button", { name: "100%" }).click(); await expect(page.locator(".leg")).toHaveCount(1); }
  await page.getByRole("button", { name: /Review/ }).click();
  await expect(page.getByRole("button", { name: /Commit/ })).toBeVisible();
  await page.getByRole("button", { name: /Commit/ }).click();
  await expect(page.locator(".result").first()).toBeVisible();
}

test("a whole level 2 episode through the real server: arm, commit, reveal, continue, debrief, saved", async ({ page, request }) => {
  const posts: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST") posts.push(new URL(r.url()).pathname.replace(/^\/api\/desk\/[0-9a-f]+/, "")); });
  await start(page, 2, 5);
  for (let i = 0; i < 20 && (await page.locator(".debrief").count()) === 0; i++) {
    await expect(page.locator(".panel-h h2", { hasText: /CLIENT REQUEST|HEDGE|CALCULATION|YOUR TWO-WAY/ }).first()).toBeVisible();
    const before = posts.length;
    await decide(page);
    // between the commit and Continue the next observation was not requested, and the next ticket is not on screen
    expect(posts.slice(before).filter((p) => p === "/continue")).toHaveLength(0);
    expect(posts.slice(before)).toContain("/submit");
    await expect(page.locator("input[aria-label='your price, percent']")).toHaveCount(0);
    await page.locator(".continue-row .btn-primary").click();
    await page.waitForTimeout(150);
  }
  await expect(page.locator(".strip4")).toBeVisible();
  await expect(page.getByText("SAME CLIENTS, SAME MARKET PATH", { exact: false }).first()).toBeVisible();
  await expect(page.locator("table tr.you")).toBeVisible({ timeout: 30_000 });      // the alternatives arrive second
  const saved = await (await request.get("/api/review/sessions")).json();
  expect(saved.length).toBe(1);
  expect(saved[0].level).toBe(2);
  await page.getByRole("button", { name: "Back to shell" }).click();
  await expect(page.getByText("REVIEW", { exact: true }).first()).toBeVisible();
  await expect(page.locator("table tbody tr")).toHaveCount(1);
});

test("a reload after a commit lands on the result, not on the next screen", async ({ page }) => {
  await start(page, 2, 7);
  await decide(page);
  await page.reload();
  await expect(page.locator(".result").first()).toBeVisible();
  await expect(page.locator("input[aria-label='your price, percent']")).toHaveCount(0);
  await expect(page.getByText("as at decision")).toBeVisible();
  await page.locator(".continue-row .btn-primary").click();
  await expect(page.locator(".result")).toHaveCount(0);
});

test("level 1: the calculation check carries its unit and the book to work from", async ({ page }) => {
  await start(page, 1, 3);
  await page.getByRole("button", { name: /Review/ }).click();
  await page.getByRole("button", { name: /Commit/ }).click();
  await page.locator(".continue-row .btn-primary").click();
  await expect(page.locator(".panel-h h2", { hasText: "CALCULATION CHECK" })).toBeVisible();
  await expect(page.locator(".rfq-row .dim", { hasText: /^EUR$/ })).toBeVisible();          // the unit, from input.unit
  await expect(page.locator(".row-new")).toHaveCount(1);                                    // the trade just done is in the book
});

test("the shell has its three areas: TRAIN shows the real catalogue and REVIEW reads the saved episodes", async ({ page }) => {
  await page.goto("/#/train");
  await expect(page.getByText("Practise a skill")).toBeVisible();
  await expect(page.locator(".track").first()).toBeVisible();
  await page.getByRole("button", { name: /REVIEW/ }).click();
  await expect(page.getByText("REVIEW", { exact: true }).first()).toBeVisible();
});

// The point of the composition: whichever state the desk is in, the columns use the window. No page scroll, and no column ends well above the bottom of the work area.
for (const [w, h] of [[1280, 720], [1480, 900], [1920, 1080]] as const) {
  test(`the desk fills a ${w}x${h} window in decision and result states`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await start(page, 2, 5);
    const check = async (state: string) => {
      const m = await page.evaluate(() => {
        const main = document.querySelector(".desk-main")!.getBoundingClientRect();
        const cols = [...document.querySelectorAll(".desk-main > .col")].map((c) => {
          const kids = [...c.children].map((k) => k.getBoundingClientRect().bottom);
          return { bottom: Math.max(...kids), colBottom: c.getBoundingClientRect().bottom, top: c.getBoundingClientRect().top };
        });
        const tape = document.querySelector(".tape")!.getBoundingClientRect();
        return { main: { top: main.top, bottom: main.bottom }, cols, tapeBottom: tape.bottom, scrollH: document.documentElement.scrollHeight, inner: window.innerHeight };
      });
      expect(m.scrollH, `${state}: the page itself does not scroll`).toBeLessThanOrEqual(m.inner + 1);
      expect(Math.abs(m.tapeBottom - m.inner), `${state}: the tape sits at the bottom edge`).toBeLessThan(2);
      for (const c of m.cols) expect(c.colBottom - c.bottom, `${state}: a column stops short of the bottom`).toBeLessThan(28);
    };
    await check("decision");
    await decide(page);
    await check("result");
    await page.locator(".continue-row .btn-primary").click();
    for (let i = 0; i < 6; i++) {                                 // reach the hedge screen if this seed shows one
      if ((await page.locator(".panel-h h2", { hasText: "HEDGE" }).count()) > 0) { await check("hedge"); break; }
      await decide(page);
      await page.locator(".continue-row .btn-primary").click();
      await page.waitForTimeout(100);
    }
  });
}

test("Back to Levels: abandoning an in-progress episode sends nothing, is not resumed by a reload, and can be picked up from the menu", async ({ page }) => {
  const posts: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST") posts.push(new URL(r.url()).pathname.replace(/^\/api\/desk\/[0-9a-f]+/, "")); });
  const started = page.waitForResponse((r) => r.url().endsWith("/api/desk/start"));
  await start(page, 2, 11);
  const id = (await (await started).json()).id as string;
  await page.getByRole("button", { name: /Review/ }).click();                       // armed, not committed
  await expect(page.getByRole("button", { name: /Commit/ })).toBeVisible();
  await page.getByRole("button", { name: /Levels/ }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.keyboard.press("Enter");                                               // Keep playing, not Commit
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Commit/ })).toBeVisible();
  await page.getByRole("button", { name: /Levels/ }).click();
  await page.getByRole("button", { name: "Leave to levels" }).click();
  await expect(page.getByText("IN PROGRESS")).toBeVisible();
  expect(posts).toEqual(["/api/desk/start"]);                                       // only the start was ever posted: no parse, submit or continue
  await page.reload();
  await expect(page.getByText("IN PROGRESS")).toBeVisible();                        // the reload does not silently resume it
  const live = (await (await page.request.get("/api/desk")).json()) as { id: string }[];   // other tests' sessions share this server
  await page.getByRole("button", { name: "Resume" }).nth(live.findIndex((d) => d.id === id)).click();
  await expect(page.locator("input[aria-label='your price, percent']")).toBeEnabled();   // same unanswered request, ticket editable
  await expect(page.locator(".topbar").getByText("1/5")).toBeVisible();
});

test("deleting an unfinished session removes it from the server: it is gone after a reload and cannot be reopened", async ({ page, request }) => {
  const posts: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST") posts.push(new URL(r.url()).pathname); });
  const started = page.waitForResponse((r) => r.url().endsWith("/api/desk/start"));
  await start(page, 2, 21);
  const id = (await (await started).json()).id as string;
  await page.getByRole("button", { name: /Levels/ }).click();
  await page.getByRole("button", { name: "Leave to levels" }).click();
  const del = page.getByRole("button", { name: `delete session ${id.slice(0, 6)}` });
  await expect(del).toBeVisible();
  await del.click();
  await expect(page.getByRole("group", { name: new RegExp(`delete session ${id.slice(0, 6)}`) })).toBeVisible();   // asked first: still on the server
  expect((await request.get(`/api/desk/${id}`)).status()).toBe(200);
  await page.getByRole("group", { name: new RegExp(id.slice(0, 6)) }).getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("status")).toContainText(`${id.slice(0, 6)}`);
  await expect(page.getByRole("button", { name: `delete session ${id.slice(0, 6)}` })).toHaveCount(0);
  expect((await request.get(`/api/desk/${id}`)).status()).toBe(404);                 // really gone, not hidden
  expect((await request.post(`/api/desk/${id}/continue`)).status()).toBe(404);
  await page.reload();
  await expect(page.getByRole("button", { name: `delete session ${id.slice(0, 6)}` })).toHaveCount(0);
  expect(posts.filter((p) => /\/(submit|continue|parse)$/.test(p))).toEqual([]);     // deleting committed and advanced nothing
});
