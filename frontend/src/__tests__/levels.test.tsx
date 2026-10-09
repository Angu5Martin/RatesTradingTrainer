// Levels 3-5 on screen, against REAL recorded sessions of each level (fixtures dumped from the Python Session). What the desk shows is what the views carry:
// no panel exists unless its block is in the observation, and nothing from a decision's result is on screen before the commit.
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import l3 from "../fixtures/l3_seed1.json";
import l4 from "../fixtures/l4_products.json";
import l5 from "../fixtures/l5_seed1.json";
import l5p from "../fixtures/l5_position.json";
import { type Fixture, fixtureServer } from "./fixtureServer";

const h = vi.hoisted(() => ({ server: null as unknown as ReturnType<typeof import("./fixtureServer").fixtureServer> }));
vi.mock("../api/client", () => ({
  ApiError: class extends Error {},
  api: new Proxy({}, { get: (_t, k: string) => (...a: unknown[]) => (h.server.api as unknown as Record<string, (...x: unknown[]) => unknown>)[k](...a) }),
}));
import { Debrief } from "../desk/Debrief";
import { LiveDesk } from "../desk/LiveDesk";
import { useDesk } from "../desk/store";
import { eur } from "../lib/format";

const L3 = l3 as unknown as Fixture, L4 = l4 as unknown as Fixture, L5 = l5 as unknown as Fixture, L5P = l5p as unknown as Fixture;
beforeEach(() => { sessionStorage.clear(); useDesk.getState().reset(); });
afterEach(cleanup);

async function begin(fx: Fixture, level: number) {
  h.server = fixtureServer(fx);
  const user = userEvent.setup();
  render(<LiveDesk onExit={() => undefined} />);
  await user.click((await screen.findAllByRole("button", { name: "Start" }))[level - 1]);
  await screen.findByRole("button", { name: /Review/ });
  return user;
}
/** Commit what the screen asks with its simplest valid answer, and wait for the result. */
async function commit(user: ReturnType<typeof userEvent.setup>, fillAnswer = "0") {
  if (screen.queryByLabelText("your answer")) await user.type(screen.getByLabelText("your answer"), fillAnswer);
  await user.keyboard("{Enter}");
  await screen.findByRole("button", { name: /Commit/ });
  await user.keyboard("{Enter}");
  await screen.findByText("DECISION SUBMITTED", { selector: "h2" });
}
const cont = async (user: ReturnType<typeof userEvent.setup>) => { await user.click(screen.getByRole("button", { name: /Continue|Open the debrief/ })); };
const obsAt = (fx: Fixture, i: number) => fx.steps[i].observation;
const bodyText = () => document.body.textContent ?? "";

describe("level 3: the curve book", () => {
  it("reads a ladder: the curve, the street of the tenor asked about, bucket DV01 and slope against their limits, and the request's own DV01", async () => {
    await begin(L3, 3);
    const o = obsAt(L3, 0);
    expect(screen.getByText("SWAP LADDER", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByText("STREET · 10Y", { selector: "h2" })).toBeInTheDocument();                     // the request is a 10Y
    const ladder = screen.getByText("SWAP LADDER", { selector: "h2" }).closest("section")!;
    for (const t of ["2Y", "5Y", "10Y", "30Y"]) expect(within(ladder).getByText(t)).toBeInTheDocument();
    expect(screen.getByText("DV01 BY BUCKET")).toBeInTheDocument();
    expect(screen.getAllByRole("meter", { name: "DV01" }).length).toBeGreaterThanOrEqual(2);              // the top bar and the risk panel
    expect(screen.getAllByRole("meter", { name: "slope" }).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/Curvature/)).toBeInTheDocument();
    expect(screen.getByText("own DV01")).toBeInTheDocument();
    const row10 = o.market!.ladder.find((r) => r.tenor === 10)!;
    expect((screen.getByLabelText("your price, percent") as HTMLInputElement).value).toBe((row10.bid * 100).toFixed(4));   // a client who receives fixed deals at your bid
    expect(screen.queryByText(/DV01 after your decision/)).toBeNull();
  });

  it("the hedge ticket is built from the ladder, offers flatten, shows each leg's own DV01 and nothing of the hedge's effect on the book before the commit", async () => {
    const user = await begin(L3, 3);
    await commit(user);                                                           // price
    await cont(user);
    await screen.findByText("HEDGE", { selector: "h2" });
    const menu = screen.getByText("Swap", { selector: "th" }).closest("table")!;
    expect(within(menu).getAllByRole("row")).toHaveLength(5);                      // header and the four tenors
    await user.click(screen.getByRole("button", { name: "Flatten" }));
    expect(await screen.findAllByLabelText("size, EUR millions")).toHaveLength(3);  // the engine's three legs as ordinary, editable legs
    expect(h.server.log).toContain("parse:flatten");
    expect(screen.getAllByText(/leg DV01/).length).toBe(3);
    expect(screen.queryByText(/DV01 after your decision/)).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "after" })).toBeNull();
    await user.click(screen.getByRole("button", { name: /Review/ }));
    expect(screen.getByText(/Receive fixed €200m 2Y/)).toBeInTheDocument();
    expect(h.server.log.filter((l) => l.startsWith("submit"))).toEqual(["submit:rfq"]);   // armed, not committed
  });

  it("after the commit the result shows the curve's par change by tenor, the exposures after, and the new trades; the next screen waits for Continue", async () => {
    const user = await begin(L3, 3);
    await commit(user);
    await cont(user);
    await screen.findByText("HEDGE", { selector: "h2" });
    await user.click(screen.getByRole("button", { name: "Flatten" }));
    await screen.findAllByLabelText("size, EUR millions");
    await commit(user);
    const r = L3.steps[1].result;
    const ev = r.events.find((e) => e.type === "market")!;
    expect(screen.getByText("PAR CHANGE BY TENOR")).toBeInTheDocument();
    if (ev.type === "market") expect(ev.tenor_moves.map((t) => t.tenor)).toEqual([2, 5, 10, 30]);
    expect(screen.getByRole("columnheader", { name: "after" })).toBeInTheDocument();
    expect(screen.getByText(/DV01 after your decision/)).toBeInTheDocument();
    expect(screen.getAllByText("new").length).toBeGreaterThan(0);
    expect(document.querySelector(".is-result")).not.toBeNull();
    expect(h.server.log.filter((l) => l === "next")).toHaveLength(1);              // only the Continue after the price: this result's next screen has not been asked for
    await cont(user);
    expect(h.server.log.filter((l) => l === "next")).toHaveLength(2);
    await waitFor(() => expect(document.querySelector(".is-decision")).not.toBeNull());
  });

  it("the slope check shows the request it refers to and the slope loadings, and is not marked until the price", async () => {
    const user = await begin(L3, 3);
    await commit(user); await cont(user);
    await screen.findByText("HEDGE", { selector: "h2" });
    await user.click(screen.getByRole("button", { name: "Flatten" }));
    await screen.findAllByLabelText("size, EUR millions");
    await commit(user); await cont(user);
    await screen.findByText("THE REQUEST", { selector: "h2" });
    expect(screen.getByText(/RECEIVES fixed/)).toBeInTheDocument();
    expect(screen.getByText(/Slope loading of each tenor/)).toBeInTheDocument();
    expect(screen.getByText(/not priced yet/)).toBeInTheDocument();
    expect(screen.getByText("DV01 BY BUCKET")).toBeInTheDocument();               // the checkpoint keeps the book on screen to work from
    await commit(user, "51000");
    expect(screen.getByText(/Answer recorded: it is checked after you price the request/)).toBeInTheDocument();
    expect(screen.queryByText(/✓|✗/)).toBeNull();
  });
});

const noTrade = async (user: ReturnType<typeof userEvent.setup>) => { await user.click(screen.getByRole("button", { name: /^No trade/ })); };

describe("level 4: products and the overnight", () => {
  it("shows futures and the CTD bond with their DV01 and cost, the swap-cost conditions, and a hedge menu with products", async () => {
    const user = await begin(L4, 4);
    expect(screen.getByText("FUTURES AND BOND", { selector: "h2" })).toBeInTheDocument();
    for (const code of ["FGBM", "FGBL", "CTD"]) expect(screen.getAllByText(code).length).toBeGreaterThan(0);
    expect(screen.getByText(/CTD 2\.25% Sep-35, CF 0\.7467/)).toBeInTheDocument();
    expect(screen.getByText(/about 2\.0× their usual spread/)).toBeInTheDocument();
    expect(screen.getByText(/Futures still trade tight/)).toBeInTheDocument();
    await commit(user); await cont(user);
    expect(await screen.findByText("CALCULATION CHECK", { selector: "h2" })).toBeInTheDocument();
    expect(screen.queryByText("RISK", { selector: "h2" })).toBeNull();                // the check asks for the DV01: the risk panel is not there to read it off
    expect(screen.getByText("POSITIONS", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByText("FUTURES AND BOND", { selector: "h2" })).toBeInTheDocument();
    await commit(user, "-5320"); await cont(user);
    await screen.findByText("HEDGE", { selector: "h2" });
    const prod = screen.getByText("Product", { selector: "th" }).closest("table")!;
    expect(within(prod).getAllByRole("row")).toHaveLength(4);
    await user.click(within(prod.querySelector("tr:nth-child(2)") as HTMLElement).getByRole("button", { name: "Sell" }));   // the first product row (a future, first in the list)
  });

  it("a futures leg is sized in contracts with its own DV01 and cost, summarised before the commit, and its trade appears as a new position after", async () => {
    const user = await begin(L4, 4);
    await commit(user); await cont(user); await commit(user, "-5320"); await cont(user);
    await screen.findByText("HEDGE", { selector: "h2" });
    const fgbl = within(screen.getByText("Product", { selector: "th" }).closest("table")!).getByText("FGBL").closest("tr")!;
    await user.click(within(fgbl).getByRole("button", { name: "Sell" }));
    await user.type(screen.getByLabelText("size, contracts"), "1500");
    const dv01 = obsAt(L4, 2).market!.products.find((p) => p.code === "FGBL")!.dv01_per_unit;
    expect(screen.getByText(/leg DV01/).closest("span")!.textContent).toContain(eur(-1500 * dv01).replace(/^-/, "−"));
    await user.keyboard("{Enter}");
    expect(await screen.findByText(/Sell 1,500 FGBL/)).toBeInTheDocument();
    await user.keyboard("{Enter}");
    await screen.findByText("DECISION SUBMITTED", { selector: "h2" });
    expect(screen.getAllByText("new").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/SELL FGBM/).length).toBeGreaterThan(0);              // from the result's hedge_trade event
    expect(screen.getAllByText(/contracts/).length).toBeGreaterThan(0);
    expect(within(screen.getByText("RISK", { selector: "h2" }).closest("section")!).getByText(/Swap spread/)).toBeInTheDocument();   // spread exposure after the product hedge, revealed by the result
  });

  it("the close shows the book's overnight carry, roll-down and funding, the result splits it by cause, and the morning offers to switch the hedges into swaps", async () => {
    const user = await begin(L4, 4);
    await commit(user); await cont(user); await commit(user, "-5320"); await cont(user);
    await screen.findByText("HEDGE", { selector: "h2" });
    await noTrade(user); await commit(user); await cont(user);                    // round 1 hedge
    await screen.findByText("CLIENT REQUEST", { selector: "h2" });
    await commit(user); await cont(user);
    await screen.findByText("HEDGE", { selector: "h2" });
    await noTrade(user); await commit(user); await cont(user);                    // round 2 hedge
    await screen.findByText("THE CLOSE", { selector: "h2" });
    const carry = obsAt(L4, 5).overnight!.time_pnl;
    expect(screen.getByText("CARRY, ROLL-DOWN AND FUNDING").closest("section")!.textContent).toContain(eur(carry));
    expect(screen.getByText("Swap spread", { exact: false })).toBeInTheDocument();    // product hedges held: the spread exposures are on the risk panel
    expect(screen.getAllByText(/SHORT FGBM|SHORT CTD/).length).toBeGreaterThan(0);
    await noTrade(user); await commit(user);
    expect(screen.getByText("OVERNIGHT: CARRY, ROLL AND FUNDING", { selector: "h2" })).toBeInTheDocument();
    const carryPanel = screen.getByText("OVERNIGHT: CARRY, ROLL AND FUNDING", { selector: "h2" }).closest("section")!;
    for (const c of ["swap carry", "futures convergence"]) expect(within(carryPanel).getByText(c)).toBeInTheDocument();
    await cont(user);
    await screen.findByText("HEDGE", { selector: "h2" });
    await user.click(screen.getByRole("button", { name: "Switch to swaps" }));
    expect(await screen.findAllByLabelText("size, EUR millions")).toHaveLength(1);
    expect(screen.getByLabelText("size, contracts")).toHaveValue("1500");
    expect(screen.getByLabelText("size, EUR millions face")).toHaveValue("40.0");
    expect(h.server.log).toContain("parse:switch");
  });
});

const HIDDEN_WORDS = /informed|posterior|P\(inform|probab|signal truth/i;

describe("level 5: information, views and changing conditions", () => {
  it("opens on a quote in the focus tenor with the research view, its stated reliability and the data calendar, and no sign of who is informed", async () => {
    await begin(L5, 5);
    expect(screen.getByText("YOUR TWO-WAY MARKET · 10Y", { selector: "h2" })).toBeInTheDocument();
    const row = obsAt(L5, 0).market!.ladder.find((r) => r.tenor === 10)!;
    expect((screen.getByLabelText("bid, percent") as HTMLInputElement).value).toBe((row.bid * 100).toFixed(4));
    expect(screen.getByText("READ THE ROOM", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByText(/we expect the 10Y to RISE about 3bp/)).toBeInTheDocument();
    expect(screen.getByText("30% reliable")).toBeInTheDocument();
    expect(screen.getByText(/What is left of the view: about 3\.0bp rise over the 4 steps/)).toBeInTheDocument();
    expect(screen.getByText(/No named client has traded yet today/)).toBeInTheDocument();
    expect(bodyText()).not.toMatch(HIDDEN_WORDS);
  });

  it("walks a whole level 5 episode: the named clients' evidence, the release, the limit cut and the position decision, with no hidden state on any live screen or result", async () => {
    const user = await begin(L5, 5);
    let sawEvidence = false, sawRelease = false, sawCut = false, sawPosition = false, sawSeenToday = false;
    for (let guard = 0; guard < 12 && !screen.queryByText("DEBRIEF", { exact: false, selector: "strong" }); guard++) {
      const titles = screen.queryAllByRole("heading", { level: 2 }).map((x) => x.textContent);
      if (titles.includes("NAMED CLIENTS TODAY") || screen.queryByLabelText("named clients today")) sawEvidence = true;
      if (screen.queryByText(/release ×3/)) sawRelease = true;
      if (screen.queryByText(/Risk management cuts your limits to 200k DV01 and 100k slope/) && screen.queryByText(/€200\.0k/)) sawCut = true;
      if (screen.queryByText(/Seen today:/)) sawSeenToday = true;
      if (titles.includes("POSITION")) { sawPosition = true; await user.click(screen.getByRole("button", { name: /^Keep/ })); }
      else if (titles.includes("HEDGE")) await noTrade(user);
      expect(bodyText()).not.toMatch(HIDDEN_WORDS);                                  // decision screen
      await user.keyboard("{Enter}");
      await screen.findByRole("button", { name: /Commit/ });
      await user.keyboard("{Enter}");
      await screen.findByText("DECISION SUBMITTED", { selector: "h2" });
      expect(bodyText()).not.toMatch(HIDDEN_WORDS);                                  // result screen: assessment reasons carry no probability on the live desk
      await cont(user);
      await waitFor(() => expect(screen.queryByText("DECISION SUBMITTED", { selector: "h2" })).toBeNull());
    }
    expect(sawEvidence && sawRelease && sawCut && sawPosition && sawSeenToday).toBe(true);
    expect(h.server.log.filter((l) => l.startsWith("submit")).length).toBe(L5.steps.length);
  });

  it("the position ticket offers keep, flat and a DV01 target in steps, resolved by the engine into legs, with the limit shown and no effect on the book", async () => {
    const user = await begin(L5P, 5);
    await commit(user); await cont(user);                                          // the quote
    await screen.findByText("HEDGE", { selector: "h2" });
    await noTrade(user); await commit(user); await cont(user);
    await screen.findByText("CLIENT REQUEST", { selector: "h2" });
    await commit(user); await cont(user);
    await screen.findByText("POSITION", { selector: "h2" });
    expect(screen.getByText(/limit €300\.0k/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "target 50k higher" }));
    const want = String(Math.round((obsAt(L5P, 3).book!.dv01 + 50_000) / 1000) * 1000);
    expect((screen.getByLabelText("target DV01") as HTMLInputElement).value).toBe(want);       // the book's DV01 as shown, plus a step
    await user.click(screen.getByRole("button", { name: "Set" }));
    expect(h.server.log).toContain(`parse:target ${want}`);
    expect(await screen.findAllByLabelText("size, EUR millions")).toHaveLength(1);
    expect(screen.queryByText(/DV01 after your decision/)).toBeNull();
    await user.click(screen.getByRole("button", { name: /^Keep/ }));                 // Keep replaces what was built
    expect(screen.queryAllByLabelText("size, EUR millions")).toHaveLength(0);
    expect(await screen.findByText("Keep the book as it is")).toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(await screen.findByText(/COMMIT/)).toBeInTheDocument();
    expect(h.server.log.filter((l) => l === "submit:hedge")).toHaveLength(1);        // only the one earlier hedge: arming sent nothing
  });

  it("the debrief reveals what the live desk hid: the model's probabilities against the truth, the view, and the distribution over simulated paths", async () => {
    const d = L5.debrief_full;
    useDesk.setState({ phase: "finished", sessionId: "x", episode: L5.steps[0].observation.episode, transcript: L5.steps, debrief: L5.debrief, debriefFull: d, loadingFull: false });
    render(<Debrief onNewEpisode={() => undefined} onExit={() => undefined} />);
    expect(screen.getByText("INFORMATION, NOW REVEALED", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByText(/Model's P\(informed\)/)).toBeInTheDocument();
    expect(screen.getAllByText(/informed/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/stated reliability 30%/).length).toBeGreaterThan(0);
    expect(screen.getByRole("img", { name: /distribution of P&L over simulated market paths/ })).toBeInTheDocument();
    expect(screen.getByText(/200 paths/)).toBeInTheDocument();
    expect(screen.getByText(/LEVEL AND SLOPE BY ROUND/)).toBeInTheDocument();
  });
});
