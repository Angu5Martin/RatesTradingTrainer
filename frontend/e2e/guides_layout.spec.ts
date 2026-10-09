import { expect, test, type Page } from "@playwright/test";

// The How To guides (Live Desk and Market Making Game) and the game table's adaptive layout, against the REAL server on a private home (playwright.config.ts).

async function deal(page: Page, level: number, seed: string, markets?: number) {
  await page.goto("/#/game");
  await page.getByRole("radio", { name: new RegExp(`LEVEL ${level}`) }).click();
  await page.getByLabel("seed").fill(seed);
  if (markets) await page.getByLabel("number of markets").fill(String(markets));
  await page.getByRole("button", { name: "Deal the table" }).click();
  await page.getByTestId("game-table").waitFor();
}
const gameState = async (page: Page) => {
  const id = await page.evaluate(() => sessionStorage.getItem("rates-game.id"));
  return (await page.request.get(`/api/mmgame/${id}`)).json();
};
const noSideways = async (page: Page) => expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);

test("game guides: open before and during a game, switch World and Probability markets, follow a section link, close with the game untouched", async ({ page }) => {
  await page.goto("/#/game");
  await page.getByRole("button", { name: /How to play well/ }).click();
  const dlg = page.getByRole("dialog", { name: /how to/i });
  await expect(dlg.getByRole("tabpanel")).toContainText("how to play well");
  await page.keyboard.press("Escape");
  await expect(dlg).toHaveCount(0);

  await deal(page, 1, "2");
  await page.getByLabel("M1 bid").fill("1480");
  const before = await gameState(page);
  await page.getByRole("button", { name: "How to", exact: true }).click();
  await dlg.getByRole("tab", { name: "World markets" }).click();
  await expect(dlg.getByRole("tabpanel")).toContainText("When you know better than the crowd");
  await dlg.getByRole("tab", { name: "Probability markets" }).click();
  await dlg.getByRole("navigation", { name: "sections" }).getByRole("button", { name: /Shocks: what changed/ }).click();
  await expect(dlg.locator("[data-anchor='shocks-what-changed-and-how-to-reprice']")).toBeInViewport();
  await dlg.getByRole("link", { name: "How the bots decide" }).first().click();
  await expect(dlg.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  await expect(dlg.locator("[data-anchor='how-the-bots-decide']")).toBeInViewport();
  await dlg.getByRole("button", { name: /Close/ }).click();
  await expect(dlg).toHaveCount(0);
  await expect(page.getByLabel("M1 bid")).toHaveValue("1480");                         // the quote being typed survived
  expect(await gameState(page)).toEqual(before);                                       // and nothing reached the server
});

test("Live Desk guide: opens from the level menu and from the trading-loop rail during an episode, and keys cannot arm a ticket behind it", async ({ page }) => {
  await page.goto("/#/desk");
  await page.getByRole("button", { name: "How to trade the desk" }).click();
  const dlg = page.getByRole("dialog", { name: /how to/i });
  await expect(dlg).toContainText("Live Desk guide");
  await dlg.getByRole("navigation", { name: "sections" }).getByRole("button", { name: "Worked examples" }).click();
  await expect(dlg.locator("[data-anchor='worked-examples']")).toBeInViewport();
  await page.keyboard.press("Escape");
  await page.fill("#seed", "5");
  await page.getByRole("button", { name: "Start" }).nth(1).click();
  await page.waitForSelector(".desk");
  await page.getByRole("button", { name: "How to", exact: true }).click();
  await expect(dlg).toBeVisible();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
  await expect(dlg).toHaveCount(0);
  await expect(page.getByText("ARMED")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Review/ })).toBeEnabled();
});

test("many markets at 1480x900: a three-column grid, the side panel and the play button in view, no sideways scroll", async ({ page }) => {
  await deal(page, 3, "4", 8);
  const cards = page.locator("ul[aria-label='markets'] > li.mk");
  await expect(page.locator("ul[aria-label='markets']")).toHaveAttribute("data-density", "dense");
  const lefts = new Set((await cards.evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().left)))));
  expect(lefts.size).toBeGreaterThanOrEqual(3);
  await expect(page.getByTestId("advance")).toBeInViewport();
  await expect(page.getByRole("complementary")).toBeInViewport();
  await noSideways(page);
});

test("two markets at 1480x900: roomy cards, side by side, each with its rules and recent trades", async ({ page }) => {
  await deal(page, 1, "3", 2);
  await expect(page.locator("ul[aria-label='markets']")).toHaveAttribute("data-density", "roomy");
  const boxes = await page.locator("ul[aria-label='markets'] > li.mk").evaluateAll((els) => els.map((e) => e.getBoundingClientRect()));
  expect(boxes).toHaveLength(2);
  expect(Math.abs(boxes[0].top - boxes[1].top)).toBeLessThan(2);
  for (const b of boxes) expect(b.width).toBeGreaterThan(380);
  await expect(page.getByLabel("M1 recent trades")).toBeVisible();
  await noSideways(page);
});

test("a narrow window stacks the side panel under the markets, keeps the controls reachable and never scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 900 });
  await deal(page, 2, "7");
  const grid = await page.locator("ul[aria-label='markets']").boundingBox();
  const side = await page.getByRole("complementary").boundingBox();
  expect(side!.y).toBeGreaterThan(grid!.y + grid!.height - 1);
  await expect(page.getByTestId("advance")).toBeInViewport();
  const bid = page.locator("ul[aria-label='markets'] input[aria-label$=' bid']").first();
  await bid.scrollIntoViewIfNeeded();
  await expect(bid).toBeInViewport();
  await noSideways(page);
  // the layout changing size does not reset what is typed
  await bid.fill("123");
  await page.setViewportSize({ width: 1480, height: 900 });
  await expect(bid).toHaveValue("123");
});
