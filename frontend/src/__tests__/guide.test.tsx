import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fx from "../fixtures/game_l1.json";
import l2 from "../fixtures/l2_seed3.json";
import { GuideSheet } from "../guide/GuideSheet";
import { GAME_GUIDES, GUIDES, type GuideId, resolveLink } from "../guide/guides";
import { headings, links, parseMarkdown, slugify } from "../guide/markdown";
import { type Fixture, fixtureServer } from "./fixtureServer";
import { type GameFixture, gameServer } from "./gameServer";

const h = vi.hoisted(() => ({
  game: null as unknown as ReturnType<typeof import("./gameServer").gameServer>,
  desk: null as unknown as ReturnType<typeof import("./fixtureServer").fixtureServer>,
}));
vi.mock("../game/api", () => ({
  GameApiError: class extends Error {},
  gameApi: new Proxy({}, { get: (_t, k: string) => (...a: unknown[]) => (h.game.api as unknown as Record<string, (...x: unknown[]) => unknown>)[k](...a) }),
}));
vi.mock("../api/client", () => ({
  ApiError: class extends Error {},
  api: new Proxy({}, { get: (_t, k: string) => (...a: unknown[]) => (h.desk.api as unknown as Record<string, (...x: unknown[]) => unknown>)[k](...a) }),
}));
import { LiveDesk } from "../desk/LiveDesk";
import { useDesk } from "../desk/store";
import { Game } from "../game/Game";
import { useGame } from "../game/store";

beforeEach(() => {
  sessionStorage.clear();
  useGame.getState().leave(); useGame.setState({ list: null });
  useDesk.getState().reset();
  h.game = gameServer(fx as unknown as GameFixture);
  h.desk = fixtureServer(l2 as unknown as Fixture);
});
afterEach(cleanup);

describe("the Markdown subset the guides are written in", () => {
  const doc = [
    "# Title", "", "Intro **bold** and *it* and `code` and [a link](#second-section).", "",
    "## Second section", "", "| A | B |", "|---|---|", "| x \\| y | 12 |", "",
    "- one", "- two", "  - nested", "- [ ] tick me", "", "1. first", "2. second", "",
    "```text", "P&L ≈ −DV01 × Δr", "```", "", "<details>", "<summary>Worked example: it opens</summary>", "", "Inside **it**.", "", "</details>", "",
    "## Second section", "", "> a quote", "", "---",
  ].join("\n");
  const blocks = parseMarkdown(doc);

  it("parses headings with GitHub's anchors (duplicates numbered), tables with escaped pipes, lists, code and expandable sections", () => {
    expect(headings(blocks).map((x) => x.slug)).toEqual(["title", "second-section", "second-section-1"]);
    const table = blocks.find((b) => b.t === "table");
    expect(table).toMatchObject({ head: ["A", "B"], rows: [["x | y", "12"]] });
    const lists = blocks.filter((b) => b.t === "list");
    expect(lists[0]).toMatchObject({ ordered: false });
    expect(lists[0].t === "list" && lists[0].items.map((i) => [i.text, i.check])).toEqual([["one", null], ["two", null], ["tick me", false]]);
    expect(lists[0].t === "list" && lists[0].items[1].children[0]).toMatchObject({ t: "list" });
    expect(lists[1]).toMatchObject({ ordered: true });
    expect(blocks.find((b) => b.t === "code")).toMatchObject({ lang: "text", text: "P&L ≈ −DV01 × Δr" });
    expect(blocks.find((b) => b.t === "details")).toMatchObject({ summary: "Worked example: it opens" });
    expect(blocks.some((b) => b.t === "quote") && blocks.some((b) => b.t === "hr")).toBe(true);
  });

  it("slugs headings as GitHub does", () => {
    expect(slugify("Shocks: what changed, and how to reprice")).toBe("shocks-what-changed-and-how-to-reprice");
    expect(slugify("Information reveals (NEW INFORMATION)")).toBe("information-reveals-new-information");
    expect(slugify("Buckets, slope and curvature (levels 3–5)")).toBe("buckets-slope-and-curvature-levels-35");
  });
});

describe("the guides", () => {
  const ids = Object.keys(GUIDES) as GuideId[];

  it.each(ids)("%s parses into sections, with worked examples that expand", (id) => {
    const b = parseMarkdown(GUIDES[id].source);
    const secs = headings(b).filter((x) => x.level === 2);
    expect(secs.length).toBeGreaterThanOrEqual(6);
    expect(b.filter((x) => x.t === "details").length).toBeGreaterThanOrEqual(3);
    expect(b.some((x) => x.t === "table")).toBe(true);
  });

  it.each(ids)("every link in %s that points at a guide lands on a real section of it", (id) => {
    for (const href of links(GUIDES[id].source)) {
      const r = resolveLink(href, id);
      if (!r) { expect(href).toMatch(/\.md$|\.md#/); continue; }                           // another document in the repository: shown as a reference, not followed
      if (!r.anchor) continue;
      const slugs = headings(parseMarkdown(GUIDES[r.guide].source)).map((x) => x.slug);
      expect(slugs, `${id}: ${href}`).toContain(r.anchor);
    }
  });
});

describe("the guide sheet", () => {
  it("opens on the overview, switches to World and Probability markets, jumps to sections and follows links between guides", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<GuideSheet guides={GAME_GUIDES} onClose={onClose} />);
    const dlg = screen.getByRole("dialog", { name: /how to/i });
    expect(within(dlg).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Overview", "World markets", "Probability markets"]);
    expect(within(dlg).getByRole("tabpanel", { name: /how to play well/i })).toBeInTheDocument();
    await user.click(within(dlg).getByRole("tab", { name: "World markets" }));
    expect(within(dlg).getByRole("tab", { name: "World markets" })).toHaveAttribute("aria-selected", "true");
    expect(within(dlg).getByRole("tabpanel", { name: "World markets" })).toHaveTextContent(/quoting what you are not sure of/i);
    await user.click(within(dlg).getByRole("tab", { name: "Probability markets" }));
    expect(within(dlg).getByRole("navigation", { name: "sections" })).toHaveTextContent(/Shocks: what changed/);
    // a link from the probability guide back to the overview switches tab
    await user.click(within(dlg).getAllByRole("link", { name: "How the bots decide" })[0]);
    expect(within(dlg).getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    // worked examples are folded until opened
    const ex = within(dlg).getAllByText(/^Worked example/)[0].closest("details")!;
    expect(ex.open).toBe(false);
    await user.click(within(ex).getByText(/^Worked example/));
    expect(ex.open).toBe(true);
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("renders the Markdown as elements, never as raw HTML text", () => {
    render(<GuideSheet guides={["desk"]} onClose={() => undefined} />);
    const body = screen.getByTestId("guide-body");
    expect(body.textContent).not.toMatch(/<details>|<summary>|\]\(|\|---/);
    expect(body.querySelectorAll("table").length).toBeGreaterThan(3);
    expect(body.querySelectorAll("pre code").length).toBeGreaterThan(1);
  });
});

describe("How To from the Market Making Game", () => {
  it("opens from the lobby and from the table, and closing it leaves the quote being typed, the round and the server untouched", async () => {
    const user = userEvent.setup();
    render(<Game />);
    await user.click(await screen.findByRole("button", { name: /How to play well/ }));
    expect(screen.getByRole("dialog", { name: /how to/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Close/ }));
    await user.click(screen.getByRole("button", { name: "Deal the table" }));
    await screen.findByTestId("game-table");
    await user.type(screen.getByLabelText("M1 bid"), "1400");
    await user.click(screen.getByLabelText("M1 raise both").closest("li")!.querySelector("button.mk-head")!);
    const log = [...h.game.log];
    await user.click(screen.getByRole("button", { name: "How to" }));
    const dlg = screen.getByRole("dialog", { name: /how to/i });
    await user.click(within(dlg).getByRole("tab", { name: "Probability markets" }));
    await user.click(within(dlg).getByRole("tab", { name: "World markets" }));
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByLabelText("M1 bid")).toHaveValue("1400");
    expect(screen.getByLabelText("round")).toHaveTextContent("1 / 8");
    expect(screen.getByLabelText("M1 active")).toHaveClass("sel");
    expect(h.game.log).toEqual(log);
  });
});

describe("How To from the Live Desk", () => {
  it("opens from the level menu and from the trading-loop rail; while it is open no key can arm, commit or continue", async () => {
    const user = userEvent.setup();
    render(<LiveDesk onExit={() => undefined} />);
    await user.click(await screen.findByRole("button", { name: "How to trade the desk" }));
    expect(screen.getByRole("dialog", { name: /how to/i })).toHaveTextContent(/Live Desk guide/);
    await user.keyboard("{Escape}");
    await user.click((await screen.findAllByRole("button", { name: "Start" }))[1]);
    await screen.findByText("CLIENT REQUEST");
    await user.click(screen.getByRole("button", { name: "How to" }));
    expect(screen.getByRole("dialog", { name: /how to/i })).toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(screen.queryByText("ARMED")).toBeNull();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByLabelText("your price, percent")).toBeEnabled();
    expect(h.desk.log).toEqual(["start"]);
  });
});
