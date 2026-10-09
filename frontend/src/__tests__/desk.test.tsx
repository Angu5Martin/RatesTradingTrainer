import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import l2 from "../fixtures/l2_seed3.json";
import { type Fixture, fixtureServer } from "./fixtureServer";

const h = vi.hoisted(() => ({ server: null as unknown as ReturnType<typeof import("./fixtureServer").fixtureServer> }));
vi.mock("../api/client", () => ({
  ApiError: class extends Error {},
  api: new Proxy({}, { get: (_t, k: string) => (...a: unknown[]) => (h.server.api as unknown as Record<string, (...x: unknown[]) => unknown>)[k](...a) }),
}));
import { Debrief, verdictLine } from "../desk/Debrief";
import { LiveDesk } from "../desk/LiveDesk";
import { useDesk } from "../desk/store";

const fx = l2 as unknown as Fixture;
beforeEach(() => { sessionStorage.clear(); useDesk.getState().reset(); h.server = fixtureServer(fx); });
afterEach(cleanup);

async function begin() {
  const user = userEvent.setup();
  render(<LiveDesk onExit={() => undefined} />);
  await user.click((await screen.findAllByRole("button", { name: "Start" }))[1]);          // level 2
  await screen.findByText("CLIENT REQUEST");
  return user;
}

describe("Live Desk screens against a recorded session", () => {
  it("shows the client request, its own DV01 and a price ticket, and nothing of the outcome", async () => {
    await begin();
    expect(screen.getByLabelText("your price, percent")).toBeEnabled();
    expect(screen.getByText(/own DV01/)).toBeInTheDocument();
    expect(screen.queryByText("DECISION SUBMITTED")).toBeNull();
    expect(screen.queryByText("ASSESSMENT")).toBeNull();
    expect(screen.queryByText(/benchmark/i)).toBeNull();
  });

  it("arm locks the ticket, Escape unlocks it, and nothing is sent until Commit", async () => {
    const user = await begin();
    await user.click(screen.getByRole("button", { name: /Review/ }));
    expect(screen.getByLabelText("your price, percent")).toBeDisabled();
    expect(screen.getByText("ARMED")).toBeInTheDocument();
    expect(h.server.log).toEqual(["start"]);
    await user.keyboard("{Escape}");
    expect(screen.getByLabelText("your price, percent")).toBeEnabled();
    expect(h.server.log).toEqual(["start"]);
  });

  it("commit reveals the outcome and the assessment, hides the next ticket until Continue, then shows it", async () => {
    const user = await begin();
    await user.keyboard("{Enter}");                                   // arm
    await user.keyboard("{Enter}");                                   // commit
    expect(await screen.findByText("DECISION SUBMITTED", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByText("ASSESSMENT")).toBeInTheDocument();
    expect(screen.getByText(/judged on what you knew when you committed/)).toBeInTheDocument();
    expect(screen.queryByLabelText("your price, percent")).toBeNull();     // the next ticket is not on screen with the old decision
    expect(h.server.log).toEqual(["start", "submit:rfq"]);
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await waitFor(() => expect(screen.getByLabelText("your price, percent")).toBeEnabled());
    expect(screen.queryByText("DECISION SUBMITTED", { selector: "h2" })).toBeNull();
    expect(h.server.log).toEqual(["start", "submit:rfq", "next"]);
  });

  it("the settled right-hand panel is labelled as at the decision, and adds new trades from the result", async () => {
    const user = await begin();
    await user.keyboard("{Enter}{Enter}");
    await screen.findByText("DECISION SUBMITTED", { selector: "h2" });
    expect(screen.getByText("as at decision")).toBeInTheDocument();
    void user;
  });

  it("composes two different screens: the trading workstation while deciding, the trade review once committed", async () => {
    const user = await begin();
    expect(document.querySelector(".is-decision")).not.toBeNull();
    expect(document.querySelector(".is-result")).toBeNull();
    expect(document.querySelectorAll(".is-decision > .col")).toHaveLength(3);
    for (const t of ["STREET", "CURVE", "TENORS", "CLIENT REQUEST", "YOUR PRICE", "RISK", "POSITIONS", "CONDITIONS"]) expect(screen.getByText(t, { exact: false, selector: "h2" })).toBeInTheDocument();
    expect(screen.queryByText("SESSION", { selector: "h2" })).toBeNull();            // no review panels while deciding
    await user.keyboard("{Enter}{Enter}");
    await screen.findByText("DECISION SUBMITTED", { selector: "h2" });
    expect(document.querySelector(".is-decision")).toBeNull();
    expect(document.querySelectorAll(".is-result > .col")).toHaveLength(3);
    for (const t of ["ASSESSMENT", "SESSION", "RISK", "POSITIONS"]) expect(screen.getByText(t, { selector: "h2" })).toBeInTheDocument();
    expect(screen.queryByText("YOUR PRICE", { selector: "h2" })).toBeNull();           // the ticket is gone, not underneath
    await user.click(screen.getByRole("button", { name: /Continue/ }));
    await waitFor(() => expect(document.querySelector(".is-decision")).not.toBeNull());
  });

  it("Pass is a decision of its own, taken with P", async () => {
    const user = await begin();
    await user.keyboard("p");
    expect(screen.getByText("Pass", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("ARMED")).toBeInTheDocument();
  });

  it("the reference sheet carries the conventions and the training assumptions once", async () => {
    const user = await begin();
    await user.click(screen.getByRole("button", { name: "Ref" }));
    const dlg = screen.getByRole("dialog", { name: "Reference" });
    expect(within(dlg).getAllByText(/P&L for a 1bp/).length).toBeGreaterThanOrEqual(2);
    expect(within(dlg).getByText(/not estimates of true market volatility/)).toBeInTheDocument();
    expect(within(dlg).getByText("level (all rates together)")).toBeInTheDocument();
  });
});

describe("Back to Levels", () => {
  it("asks first, and Enter or any other key cannot arm, commit or continue behind the dialog", async () => {
    const user = await begin();
    await user.keyboard("{Enter}");                                    // armed, not committed
    expect(screen.getByText("ARMED")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Levels/ }));
    const dlg = screen.getByRole("alertdialog");
    expect(within(dlg).getByText(/not been committed and will not be sent/)).toBeInTheDocument();
    await user.keyboard("{Enter}");                                    // the focused button is Keep playing
    expect(h.server.log).toEqual(["start"]);                           // nothing was submitted
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByText("ARMED")).toBeInTheDocument();             // still armed: Keep playing changed nothing
  });

  it("Escape closes the dialog without disarming; Leave goes to the level menu and sends nothing", async () => {
    const user = await begin();
    await user.keyboard("{Enter}");
    await user.click(screen.getByRole("button", { name: /Levels/ }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByText("ARMED")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Levels/ }));
    await user.click(screen.getByRole("button", { name: "Leave to levels" }));
    expect((await screen.findAllByRole("button", { name: "Start" })).length).toBeGreaterThan(1);
    expect(screen.getByText("LIVE DESK", { selector: "h2" })).toBeInTheDocument();
    expect(h.server.log).toEqual(["start"]);
    expect(sessionStorage.length).toBe(0);
  });

  it("leaving from a result does not continue it", async () => {
    const user = await begin();
    await user.keyboard("{Enter}{Enter}");
    await screen.findByText("DECISION SUBMITTED", { selector: "h2" });
    await user.click(screen.getByRole("button", { name: /Levels/ }));
    await user.keyboard("{Enter}");                                    // Keep playing
    expect(screen.getByText("DECISION SUBMITTED", { selector: "h2" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Levels/ }));
    await user.click(screen.getByRole("button", { name: "Leave to levels" }));
    expect(h.server.log).toEqual(["start", "submit:rfq"]);             // no "next"
  });

  it("is disabled while a commit is in flight", async () => {
    await begin();
    useDesk.setState({ phase: "submitting" });
    expect(await screen.findByRole("button", { name: /Levels/ })).toBeDisabled();
  });

  it("the debrief also offers Back to Levels", () => {
    useDesk.setState({ phase: "finished", sessionId: "x", episode: fx.steps[0].observation.episode, transcript: fx.steps, debrief: fx.debrief, debriefFull: null, loadingFull: false });
    render(<Debrief onNewEpisode={() => undefined} onExit={() => undefined} />);
    expect(screen.getByRole("button", { name: /Back to Levels/ })).toBeInTheDocument();
  });
});

describe("Debrief", () => {
  it("keeps decision quality, outcome, luck and same-path policies as separate parts, and loads the alternatives second", async () => {
    useDesk.setState({ phase: "finished", sessionId: "x", episode: fx.steps[0].observation.episode, transcript: fx.steps, debrief: fx.debrief, debriefFull: null, loadingFull: true });
    render(<Debrief onNewEpisode={() => undefined} onExit={() => undefined} />);
    expect(screen.getByText(/DECISION QUALITY/)).toBeInTheDocument();
    expect(screen.getByText(/REALISED OUTCOME/)).toBeInTheDocument();
    expect(screen.getByText(/^LUCK/)).toBeInTheDocument();
    expect(screen.getAllByText(/running the alternatives/).length).toBeGreaterThan(0);
    useDesk.setState({ debriefFull: fx.debrief_full, loadingFull: false });
    await waitFor(() => expect(screen.getByText(fx.debrief_full.counterfactuals!.policies[0].name)).toBeInTheDocument());
    expect(screen.getByText("Expected P&L from execution uncertainty", { exact: false })).toBeInTheDocument();
  });

  it("states a mismatch between decisions and result in words, never as a badge", () => {
    const d = structuredClone(fx.debrief_full);
    d.decisions.forEach((x) => { x.rating = "sound"; });
    d.outcome.total = -50000; d.luck.luck = -40000;
    expect(verdictLine(d)).toMatch(/unlucky/);
    d.decisions[0].rating = "poor"; d.outcome.total = 50000; d.luck.luck = 40000;
    expect(verdictLine(d)).toMatch(/do not read the profit as skill/);
  });
});
