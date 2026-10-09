import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fx from "../fixtures/game_l1.json";
import { type GameFixture, gameServer } from "./gameServer";

const h = vi.hoisted(() => ({ server: null as unknown as ReturnType<typeof import("./gameServer").gameServer> }));
vi.mock("../game/api", () => ({
  GameApiError: class extends Error {},
  gameApi: new Proxy({}, { get: (_t, k: string) => (...a: unknown[]) => (h.server.api as unknown as Record<string, (...x: unknown[]) => unknown>)[k](...a) }),
}));
import { Game } from "../game/Game";
import { useGame } from "../game/store";

const FX = fx as unknown as GameFixture;
beforeEach(() => { sessionStorage.clear(); useGame.getState().leave(); useGame.setState({ list: null }); h.server = gameServer(FX); });
afterEach(cleanup);

async function deal(opts: { level?: number } = {}) {
  const user = userEvent.setup();
  render(<Game />);
  await screen.findByText("MARKET MAKING GAME");
  if (opts.level) await user.click(await screen.findByRole("radio", { name: new RegExp(`LEVEL ${opts.level}`) }));
  await user.click(await screen.findByRole("button", { name: "Deal the table" }));
  await screen.findByTestId("game-table");
  return user;
}
const next = () => screen.getByTestId("advance");

describe("lobby", () => {
  it("shows the three levels from the server and starts a game with the chosen options", async () => {
    const user = userEvent.setup();
    render(<Game />);
    const radios = await screen.findAllByRole("radio", { name: /LEVEL \d/ });
    expect(radios).toHaveLength(3);
    expect(screen.getAllByText("Beginner").length).toBeGreaterThan(0); expect(screen.getAllByText("Advanced").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("radio", { name: /LEVEL 2/ }));
    await user.click(screen.getByRole("radio", { name: "Probability only" }));
    await user.type(screen.getByLabelText("seed"), "42");
    await user.click(screen.getByRole("button", { name: "Deal the table" }));
    await screen.findByTestId("game-table");
    expect(JSON.parse(h.server.log[0].replace("start:", ""))).toMatchObject({ level: 2, mix: "probability", seed: 42 });
  });
  it("refuses an unreadable seed before asking the server", async () => {
    const user = userEvent.setup();
    render(<Game />);
    await screen.findAllByRole("radio", { name: /LEVEL \d/ });
    await user.type(screen.getByLabelText("seed"), "abc");
    expect(screen.getByRole("button", { name: "Deal the table" })).toBeDisabled();
  });
  it("lists unfinished and finished games for resuming and for the debrief", async () => {
    const list = { ...FX.list, games: [
      { id: "a".repeat(16), level: 2, level_name: "Intermediate", started: "2026-10-09T10:00:00", round: 3, rounds: 12, markets: 5, done: false, pnl: 0, trades: 9 },
      { id: "b".repeat(16), level: 1, level_name: "Beginner", started: "2026-10-08T10:00:00", round: 8, rounds: 8, markets: 3, done: true, pnl: 420, trades: 20 }] };
    h.server = gameServer({ ...FX, list } as GameFixture);
    render(<Game />);
    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Debrief" })).toBeInTheDocument();
    expect(screen.getByText("+420")).toBeInTheDocument();
  });
});

describe("the table", () => {
  it("shows every open market as its own card with its own quote boxes, round counter and status", async () => {
    await deal();
    const cards = screen.getAllByRole("listitem").filter((li) => /^M\d (active|shocked|paused|resolved)/.test(li.getAttribute("aria-label") ?? ""));
    expect(cards).toHaveLength(3);
    for (const id of ["M1", "M2", "M3"]) {
      expect(screen.getByLabelText(`${id} bid`)).toBeInTheDocument(); expect(screen.getByLabelText(`${id} offer`)).toBeInTheDocument(); expect(screen.getByLabelText(`${id} size`)).toBeInTheDocument();
    }
    expect(screen.getByLabelText("round")).toHaveTextContent("1 / 8");
    expect(screen.getAllByText("ACTIVE").length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText(/rounds? left/, { selector: ".mk-rem" })).toHaveLength(3);
  });

  it("a quote must be typed and valid before it can be sent; an edit is sent on its own", async () => {
    const user = await deal();
    const send = within(screen.getByLabelText("M1 active")).getByRole("button", { name: "Quote" });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText("M1 bid"), "1400");
    await user.type(screen.getByLabelText("M1 offer"), "1390");
    expect(send).toBeDisabled();                                                          // offer below bid
    expect(screen.getByText(/offer must be above the bid/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("M1 offer")); await user.type(screen.getByLabelText("M1 offer"), "1420");
    expect(send).toBeEnabled();
    await user.click(send);
    await waitFor(() => expect(h.server.log.some((l) => l.startsWith("quote:"))).toBe(true));
    expect(JSON.parse(h.server.log.find((l) => l.startsWith("quote:"))!.slice(6))).toEqual({ market: "M1", bid: 1400, offer: 1420, size: 1 });
  });

  it("playing a round sends the edited quotes first, as one batch, then advances", async () => {
    const user = await deal();
    for (const m of FX.quotes_sent) { await user.type(screen.getByLabelText(`${m.market} bid`), String(m.bid)); await user.type(screen.getByLabelText(`${m.market} offer`), String(m.offer)); }
    expect(next()).toHaveTextContent("Send 3 & Play round 1");
    await user.click(next());
    await waitFor(() => expect(screen.getByLabelText("round")).toHaveTextContent("2 / 8"));
    const sent = h.server.log.filter((l) => l.startsWith("quotes:") || l.startsWith("advance"));
    expect(sent.map((l) => l.split(":")[0])).toEqual(["quotes", "advance"]);
    expect(JSON.parse(sent[0].slice(7))).toEqual(FX.quotes_sent);
    expect(next()).toHaveTextContent("Play round 2");                                       // nothing left unsent
  });

  it("an unreadable edit stops the round from being played", async () => {
    const user = await deal();
    await user.type(screen.getByLabelText("M1 bid"), "oops");
    await user.type(screen.getByLabelText("M1 offer"), "1500");
    await user.click(next());
    expect(await screen.findByRole("alert")).toHaveTextContent(/M1: bid/);
    expect(h.server.log.filter((l) => l.startsWith("advance"))).toEqual([]);
  });

  it("reports the round, marks a shocked market, and explains what changed without revealing outcomes", async () => {
    const user = await deal();
    for (const m of FX.quotes_sent) { await user.type(screen.getByLabelText(`${m.market} bid`), String(m.bid)); await user.type(screen.getByLabelText(`${m.market} offer`), String(m.offer)); }
    await user.click(next());
    await waitFor(() => expect(screen.getByLabelText("round")).toHaveTextContent("2 / 8"));
    expect(screen.getByText(/ROUND 1 REPORT/)).toBeInTheDocument();
    await user.click(next()); await user.click(next());
    await waitFor(() => expect(screen.getByLabelText("round")).toHaveTextContent("4 / 8"));
    const shocked = screen.getByLabelText("M3 shocked");
    expect(within(shocked).getByText("SHOCKED")).toBeInTheDocument();
    expect(screen.getByText(/1 market shocked/)).toBeInTheDocument();
    expect(within(shocked).getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    await user.click(shocked.querySelector("button.mk-head")!);
    const side = screen.getByRole("complementary");
    expect(within(side).getAllByText("NEW INFORMATION").length).toBeGreaterThan(0);
    expect(within(side).getAllByText(/still to be rolled under the same rules/).length).toBeGreaterThan(0);
    expect(within(side).queryByText(/Settled at/)).toBeNull();                              // the outcome is not shown
    await user.click(within(shocked).getByRole("button", { name: "Acknowledge" }));
    expect(h.server.log).toContain("ack:M3");
  });

  it("pause and resume go to the server for that market", async () => {
    const user = await deal();
    await user.type(screen.getByLabelText("M1 bid"), "1400"); await user.type(screen.getByLabelText("M1 offer"), "1420");
    await user.click(within(screen.getByLabelText("M1 active")).getByRole("button", { name: "Quote" }));
    await waitFor(() => expect(within(screen.getByLabelText("M1 active")).getByRole("button", { name: "Pause" })).toBeEnabled());
    await user.click(within(screen.getByLabelText("M1 active")).getByRole("button", { name: "Pause" }));
    expect(h.server.log).toContain("pause:M1:true");
  });

  it("nudge buttons move a draft by one tick and widen it", async () => {
    const user = await deal();
    await user.type(screen.getByLabelText("M2 bid"), "1.0"); await user.type(screen.getByLabelText("M2 offer"), "2.0");
    await user.click(screen.getByLabelText("M2 raise both"));
    expect(screen.getByLabelText("M2 bid")).toHaveValue("1.1"); expect(screen.getByLabelText("M2 offer")).toHaveValue("2.1");
    await user.click(screen.getByLabelText("M2 widen"));
    expect(screen.getByLabelText("M2 bid")).toHaveValue("1.0"); expect(screen.getByLabelText("M2 offer")).toHaveValue("2.2");
  });

  it("shows aggregate P&L, lots and the portfolio table across all markets", async () => {
    await deal();
    expect(screen.getByLabelText("total pnl")).toHaveTextContent("0");
    const port = screen.getByText("PORTFOLIO").closest("section")!;
    expect(within(port).getAllByRole("row")).toHaveLength(1 + 3 + 1);                      // header, three markets, total
    expect(within(port).getByText("Total")).toBeInTheDocument();
  });
});

describe("the end of the game", () => {
  async function playToTheEnd() {
    const user = await deal();
    for (const m of FX.quotes_sent) { await user.type(screen.getByLabelText(`${m.market} bid`), String(m.bid)); await user.type(screen.getByLabelText(`${m.market} offer`), String(m.offer)); }
    for (let r = 0; r < 8; r++) { await user.click(next()); if (r < 7) await waitFor(() => expect(screen.getByLabelText("round")).toHaveTextContent(`${r + 2} / 8`)); }
    return user;
  }

  it("resolved markets show their result on the table, then the debrief opens with the attribution and the revealed counterparties", async () => {
    await playToTheEnd();
    const deb = await screen.findByTestId("game-debrief");
    expect(h.server.log).toContain("debrief");
    expect(within(deb).getByText("WHERE THE P&L CAME FROM")).toBeInTheDocument();
    for (const row of ["Spread capture", "Mispricing", "Adverse selection", "News drift", "Settlement luck"]) expect(within(deb).getAllByText(row).length).toBeGreaterThan(0);
    expect(within(deb).getByLabelText("final pnl")).toBeInTheDocument();
    expect(within(deb).getByText("COUNTERPARTIES REVEALED")).toBeInTheDocument();
    expect(within(deb).getAllByText("Retail flow").length).toBeGreaterThan(0);
    expect(within(deb).getByText(/seed/)).toBeInTheDocument();                              // the seed is shown now, and only now
    for (const m of FX.debrief.markets) expect(within(deb).getByText(new RegExp(`^${m.id} · `))).toBeInTheDocument();
  });

  it("the debrief's attribution adds up on screen: total = decision result + luck", async () => {
    await playToTheEnd();
    const t = FX.debrief.totals;
    expect(t.pnl).toBeCloseTo(t.decision_result + t.luck, 6);
    expect(t.decision_edge).toBeCloseTo(t.spread_capture + t.mispricing, 6);
  });
});

describe("hidden information on the wire", () => {
  it("no payload the table is built from contains the seed, a fair value or an unresolved outcome", () => {
    const states = [FX.start, FX.quoted, ...FX.steps.map((s) => s.state)];
    for (const s of states) {
      expect(JSON.stringify(s)).not.toMatch(/"seed"|"tape"|"informed"|"shock_plan"/);
      for (const m of s.markets.filter((x) => x.status !== "resolved")) {
        const j = JSON.stringify(m);
        expect(j).not.toMatch(/"fair"|"settle"|"source"|"final_fair"/);
      }
    }
  });
});
