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

describe("the layout adapts to the table", () => {
  type M = (typeof FX.start.markets)[number];
  const S0 = FX.start, S3 = FX.steps[2].state, S5 = FX.steps[4].state;                       // the start; round 3 (M3 shocked); round 5 (M1, M2 resolved)
  const clone = (m: M, id: string, patch: Partial<M> = {}): M => ({ ...m, id, ...patch });
  const dealWith = async (markets: M[], base = S0) => {
    const start = { ...base, markets };
    h.server = gameServer({ ...FX, start, quoted: start } as GameFixture);
    return deal();
  };
  const grid = () => screen.getByRole("list", { name: "markets" });

  it("density is a pure function of the number of live markets", async () => {
    const { densityFor } = await import("../game/Table");
    expect([1, 2, 3, 4, 5, 8].map(densityFor)).toEqual(["roomy", "roomy", "standard", "standard", "dense", "dense"]);
  });

  it("one live market gets the room: its question, rules in force and recent trades are on the card", async () => {
    await dealWith([S0.markets[1]]);
    expect(grid()).toHaveAttribute("data-density", "roomy"); expect(grid()).toHaveAttribute("data-count", "1");
    const card = screen.getByLabelText("M2 active");
    expect(within(card).getByLabelText("M2 rules in force")).toHaveTextContent(/3 still to be drawn/);
    expect(within(card).getByLabelText("M2 recent trades")).toHaveTextContent(/no trades yet/);
    expect(within(card).getByText(/How many spades are among the 3 cards drawn/)).toBeInTheDocument();
  });

  it("two live markets are still roomy; a world market then shows its settlement definition on the card", async () => {
    await dealWith([S0.markets[0], S0.markets[1]]);
    expect(grid()).toHaveAttribute("data-density", "roomy"); expect(grid()).toHaveAttribute("data-count", "2");
    expect(within(screen.getByLabelText("M1 active")).getByLabelText("M1 rules in force")).toHaveTextContent(/Settles on the true value of/);
  });

  it("many live markets get a dense grid with every quote control still there", async () => {
    const many = Array.from({ length: 7 }, (_, i) => clone(S0.markets[1 + (i % 2)], `M${i + 1}`));
    await dealWith(many);
    expect(grid()).toHaveAttribute("data-density", "dense"); expect(grid()).toHaveAttribute("data-count", "7");
    for (let i = 1; i <= 7; i++) {
      for (const f of ["bid", "offer", "size"]) expect(screen.getByLabelText(`M${i} ${f}`)).toBeEnabled();
      expect(screen.getByLabelText(`M${i} widen`)).toBeInTheDocument();
    }
    expect(screen.queryByLabelText("M1 recent trades")).toBeNull();                         // dense cards keep the last trade line, not the list
    expect(screen.getByRole("complementary")).toBeInTheDocument();
  });

  it("settled markets move to a compact list below and do not count towards the density", async () => {
    await dealWith(S5.markets, S5);
    expect(grid()).toHaveAttribute("data-count", "1");
    const settled = screen.getByRole("region", { name: "settled markets" });
    expect(within(settled).getByLabelText("M1 resolved")).toHaveTextContent(/Settled/);
    expect(within(settled).getByLabelText("M2 resolved")).toBeInTheDocument();
    expect(within(grid()).queryByLabelText("M1 resolved")).toBeNull();
    expect(screen.queryByLabelText("M1 bid")).toBeNull();
  });

  it("an unusually long question is clamped on the card, kept whole in its tooltip and the detail, and leaves the grid alone", async () => {
    const long = "In what year did a very long-winded question about a treaty, its signatories, the conference at which it was negotiated and the ratification that followed in several parliaments finally enter into force for all of them?";
    const user = await dealWith([clone(S0.markets[0], "M1", { title: long, question: long }), S0.markets[1], S0.markets[2]]);
    expect(grid()).toHaveAttribute("data-density", "standard");
    const title = within(screen.getByLabelText("M1 active")).getByText(long);
    expect(title).toHaveClass("mk-title"); expect(title).toHaveAttribute("title", long);
    await user.click(screen.getByLabelText("M1 active").querySelector("button.mk-head")!);
    expect(within(screen.getByRole("complementary")).getByRole("heading", { name: long })).toBeInTheDocument();
  });

  it("a shock puts what changed on the card itself, and the banner jumps to the shocked market", async () => {
    const user = await dealWith(S3.markets, S3);
    const card = screen.getByLabelText("M3 shocked");
    const box = within(card).getByRole("status");
    expect(box).toHaveTextContent("NEW INFORMATION"); expect(box).toHaveTextContent(/still to be rolled under the same rules/);
    expect(box).toHaveTextContent(/Acknowledge/);
    await user.click(screen.getByRole("button", { name: "show M3" }));
    expect(screen.getByRole("tab", { name: /Market M3/ })).toHaveAttribute("aria-selected", "true");
    expect(within(screen.getByRole("tabpanel")).getByText(/M3 · PROBABILITY/)).toBeInTheDocument();
  });

  it("the side panel's tabs show the round report after a round and the market on request, without touching quotes being typed", async () => {
    const user = await deal();
    await user.type(screen.getByLabelText("M2 bid"), "1.2");
    expect(screen.getByRole("tab", { name: /^Market/ })).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByRole("tab", { name: /Round report/ }));
    expect(within(screen.getByRole("tabpanel")).getByText("ROUND REPORT")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /^Market/ }));
    expect(screen.getByLabelText("M2 bid")).toHaveValue("1.2");
    expect(within(screen.getByRole("complementary")).getByText("PORTFOLIO")).toBeInTheDocument();      // the portfolio stays in view whatever the tab
    await user.clear(screen.getByLabelText("M2 bid"));
    await user.click(next());
    await waitFor(() => expect(screen.getByLabelText("round")).toHaveTextContent("2 / 8"));
    expect(screen.getByRole("tab", { name: /Round 1/ })).toHaveAttribute("aria-selected", "true");
    expect(within(screen.getByRole("tabpanel")).getByText(/ROUND 1 REPORT/)).toBeInTheDocument();
  });

  it("a change of layout (a market settling) keeps the quotes being typed and the selection", async () => {
    const user = await deal();
    await user.type(screen.getByLabelText("M1 bid"), "1490");
    await user.click(screen.getByLabelText("M1 active").querySelector("button.mk-head")!);
    expect(grid()).toHaveAttribute("data-density", "standard");
    const st = useGame.getState().state!;
    useGame.setState({ state: { ...st, markets: st.markets.map((m) => (m.id === "M2" ? S5.markets[1] : m)) } });
    await waitFor(() => expect(grid()).toHaveAttribute("data-density", "roomy"));
    expect(screen.getByLabelText("M1 bid")).toHaveValue("1490");
    expect(screen.getByLabelText("M1 active")).toHaveClass("sel");
  });
});
