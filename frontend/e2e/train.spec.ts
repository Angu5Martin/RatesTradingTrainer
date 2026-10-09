import { expect, test, type Page } from "@playwright/test";

async function replay(page: Page, id: string) {
  await page.goto("/#/train");
  await page.getByLabel("question id").fill(id);
  await page.getByRole("button", { name: "Replay" }).click();
  await page.locator(".train-q").waitFor();
}

test("the catalogue is the real one: ten tracks, every source, no skill left without standalone questions", async ({ page, request }) => {
  const cat = (await (await request.get("/api/catalogue")).json()).train as { sources: number; tracks: { skills: { id: string; planned: boolean; sources: number }[] }[] };
  const skills = cat.tracks.flatMap((t) => t.skills);
  await page.goto("/#/train");
  await expect(page.getByText(`${cat.sources} question sources in 10 tracks`)).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /practise the .* track/ })).toHaveCount(10);
  await expect(page.getByText("planned", { exact: true })).toHaveCount(skills.filter((s) => s.planned).length);
  await expect(page.getByText("no standalone questions", { exact: true })).toHaveCount(skills.filter((s) => !s.planned && s.sources === 0).length);
  expect(skills.filter((s) => s.planned || s.sources === 0)).toEqual([]);
  await page.getByRole("checkbox", { name: "practise Swap DV01 and P&L for a rate move" }).check();
  await expect(page.getByText(new RegExp(`${skills.find((s) => s.id === "swaps.dv01")!.sources} sources match`))).toBeVisible();
  await expect(page.getByRole("button", { name: "Start focused practice" })).toBeVisible();
});

/** Work through every part of the question on screen. `answer(expected index)` is told the part number and returns what to do; collects each part's Expected text. */
async function walk(page: Page, how: (n: number, expected: string[]) => "skip" | { type: string } | { letter: string }, expected: string[] = []) {
  for (let n = 0; ; n++) {
    const choice = (await page.getByRole("radio").count()) > 0;
    const todo = how(n, expected);
    if (todo === "skip") await page.getByRole("button", { name: "Skip" }).click();
    else if ("letter" in todo) { await page.keyboard.press(todo.letter); await page.keyboard.press("Enter"); }
    else { await page.locator("input[aria-label='your answer']").fill(todo.type); await page.keyboard.press("Enter"); }
    await expect(page.locator(".result")).toBeVisible();
    const text = (await page.locator(".rows dd").nth(1).textContent())!.trim();
    expected.push(choice ? `choice:${text}` : text);
    const next = page.getByRole("button", { name: /Next part|Finish session|Next question/ });
    const label = (await next.textContent())!;
    await next.click();
    if (!/Next part/.test(label)) return expected;
    await expect(page.locator(".result")).toHaveCount(0);                                   // wait for the next part to replace the result before reading it (else its kind is read from the old screen)
  }
}

test("a numeric question: unreadable entry refused, answers hidden until due, and the expected answers typed back are marked correct", async ({ page, request }) => {
  const before: string[] = [];
  page.on("response", async (r) => { if (r.url().includes("/api/train/") && !r.url().endsWith("/answer") && !r.url().endsWith("/continue") && !r.url().endsWith("/finish")) before.push(await r.text().catch(() => "")); });
  await replay(page, "swaps.dv01_pnl#7");
  await expect(page.locator(".stem")).toBeVisible();
  const input = page.locator("input[aria-label='your answer']");
  if (await input.count()) {
    await input.fill("banana");
    await expect(page.getByText(/could not read a number/)).toBeVisible();
    await expect(page.getByRole("button", { name: /Submit answer/ })).toBeDisabled();
    await input.fill("");
  }
  const expected = await walk(page, () => "skip");                                          // skip every part: the grader shows what it expected
  await expect(page.getByText("Session complete")).toBeVisible();
  await expect(page.getByText(/Replay what you missed \(1\)/)).toBeVisible();
  for (const e of expected) expect(before.join("")).not.toContain(e.replace("choice:", ""));   // none of it was in any response before the answer
  await page.getByRole("button", { name: /Replay what you missed/ }).click();
  await walk(page, (n, got) => { const e = expected[n]; return e.startsWith("choice:") ? { letter: e.slice(7, 8).toLowerCase() } : { type: e }; }, []);
  await expect(page.getByText("Session complete")).toBeVisible();
  await expect(page.getByText(/nothing missed/)).toBeVisible();
  await expect(page.getByText(/Replay what you missed/)).toHaveCount(0);
  const history = await (await request.get("/api/train/history")).json();
  expect(history.length).toBeGreaterThanOrEqual(2);                                         // both attempts were recorded
});

test("a multi-part conceptual-plus-numeric question: one part at a time, in order, and a reload keeps the result on screen", async ({ page }) => {
  await replay(page, "basis.irs_vs_ois#1");
  await expect(page.getByText("Which describes the position?")).toBeVisible();
  await expect(page.getByText(/IRS rate moves \+2bp/)).toHaveCount(0);                      // part 2 is not there yet
  await page.keyboard.press("a");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Your answer")).toBeVisible();
  await expect(page.getByText(/IRS rate moves \+2bp/)).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("Your answer")).toBeVisible();                                // reload lands on the same result
  await expect(page.getByText(/IRS rate moves \+2bp/)).toHaveCount(0);
  await page.getByRole("button", { name: /Next part/ }).click();
  await expect(page.getByText(/IRS rate moves \+2bp/)).toBeVisible();
  await expect(page.locator(".earlier li")).toHaveCount(1);                                 // the answered part stays visible beside the next
  await expect(page.locator("input[aria-label='your answer']")).toBeFocused();
  await page.keyboard.type("banana");                                                       // unreadable: said so, cannot be submitted, nothing marked
  await expect(page.getByText(/could not read a number/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Submit answer/ })).toBeDisabled();
  await page.keyboard.press("Enter");
  await expect(page.locator(".result")).toHaveCount(0);
});

test("ending a session keeps what was answered, and switching to the Live Desk and back keeps the practice where it was", async ({ page, request }) => {
  await page.goto("/#/train");
  await page.getByRole("checkbox", { name: "practise Swap DV01 and P&L for a rate move" }).check();
  await page.getByRole("button", { name: "5", exact: true }).click();
  await page.getByRole("button", { name: "Start focused practice" }).click();
  await page.locator(".train-q").waitFor();
  const first = await page.locator(".tq-foot .num").textContent();
  await page.getByRole("button", { name: "Skip" }).click();
  await expect(page.getByText("SKIPPED")).toBeVisible();
  await page.getByRole("button", { name: "LIVE DESK market making" }).click();
  await expect(page.getByText("LIVE DESK", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "TRAIN focused practice" }).click();
  await expect(page.getByText("SKIPPED")).toBeVisible();                                    // still on the same result
  await page.getByRole("button", { name: /Next/ }).click();
  await page.getByRole("button", { name: /Catalogue/ }).click();
  await page.keyboard.press("Enter");                                                       // the dialog's default is Keep practising
  await expect(page.locator(".train-q")).toBeVisible();
  await page.getByRole("button", { name: /Catalogue/ }).click();
  await page.getByRole("button", { name: "End session" }).click();
  await expect(page.getByText("Session ended early")).toBeVisible();
  const h = await (await request.get("/api/train/history")).json();
  const mine = h.find((x: { ended_early: boolean; parts_total: number }) => x.ended_early && x.parts_total >= 1);
  expect(mine).toBeTruthy();
  expect(first).toBeTruthy();
});

// The sources added in the curriculum expansion go through the same interface: one part at a time, nothing of the answer on screen before it, and the expected answers typed back are marked correct.
for (const id of ["math.bootstrap_par_curve#1", "risk.key_rate_read#1", "mm.quote_review#2", "mm.requote_sequence#3", "portfolio.bucket_book#1"]) {
  test(`a new source (${id}) is practised through the existing interface and its expected answers mark correct`, async ({ page, request }) => {
    const seen: string[] = [];
    page.on("response", async (r) => { if (r.url().includes("/api/train/") && !r.url().endsWith("/answer") && !r.url().endsWith("/continue") && !r.url().endsWith("/finish")) seen.push(await r.text().catch(() => "")); });
    await replay(page, id);
    await expect(page.locator(".stem")).toBeVisible();
    await expect(page.getByText("WORKED SOLUTION")).toHaveCount(0);
    const expected = await walk(page, () => "skip");
    await expect(page.getByText("Session complete")).toBeVisible();
    for (const e of expected) if (!e.startsWith("choice:")) expect(seen.join("")).not.toContain(e);        // no numeric answer was in any response before it was due
    await expect(page.getByText(/Replay what you missed \(\d+\)/)).toBeVisible();                          // the summary has finished rendering
    await page.getByRole("button", { name: /Replay what you missed/ }).click();
    await expect(page.getByText("Session complete")).toHaveCount(0);
    await page.locator(".train-q").waitFor();
    await walk(page, (n) => { const e = expected[n]; return e.startsWith("choice:") ? { letter: e.slice(7, 8).toLowerCase() } : { type: e }; }, []);
    await expect(page.getByText(/nothing missed/)).toBeVisible();
    expect(((await (await request.get("/api/train/history")).json()) as unknown[]).length).toBeGreaterThanOrEqual(2);
  });
}
