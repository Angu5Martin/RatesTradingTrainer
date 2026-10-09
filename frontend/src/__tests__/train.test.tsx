import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import multi from "../fixtures/train_multi.json";
import focus from "../fixtures/train_focus.json";
import { type TrainFixture, trainServer } from "./trainServer";

const h = vi.hoisted(() => ({ server: null as unknown as ReturnType<typeof import("./trainServer").trainServer> }));
vi.mock("../api/client", () => ({
  ApiError: class extends Error {},
  api: new Proxy({}, { get: (_t, k: string) => (...a: unknown[]) => (h.server.api as unknown as Record<string, (...x: unknown[]) => unknown>)[k](...a) }),
}));
import { Train } from "../train/Train";
import { useTrain } from "../train/store";

const MULTI = multi as unknown as TrainFixture;
const FOCUS = focus as unknown as TrainFixture;
beforeEach(() => { sessionStorage.clear(); useTrain.getState().reset(); h.server = trainServer(MULTI); });
afterEach(cleanup);

/** Open the catalogue, replay the multi-part question and wait for the first prompt. */
async function open(fx: TrainFixture = MULTI, opts = {}) {
  h.server = trainServer(fx, opts);
  const user = userEvent.setup();
  render(<Train />);
  await user.type(await screen.findByLabelText("question id"), "basis.irs_vs_ois#1");
  await user.click(screen.getByRole("button", { name: "Replay" }));
  await screen.findByText(fx.start.question!.current!.prompt);
  return user;
}
const step = (n: number) => MULTI.steps[n];

describe("TRAIN catalogue from the real question catalogue", () => {
  it("lists the ten real tracks and every source, marks planned skills, and disables what has no questions", async () => {
    render(<Train />);
    const tracks = await screen.findAllByRole("checkbox", { name: /practise the .* track/ });
    expect(tracks).toHaveLength(10);
    expect(screen.getByText(/62 question sources in 10 tracks/)).toBeInTheDocument();
    expect(screen.getAllByText("planned").length).toBe(7);
    expect(screen.getByRole("checkbox", { name: "practise Bootstrapping a curve from par swap rates" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "practise Swap DV01 and P&L for a rate move" })).toBeEnabled();
  });

  it("builds a focused practice from one skill, a mixed one from several, and carries the filters", async () => {
    const user = userEvent.setup();
    render(<Train />);
    await user.click(await screen.findByRole("checkbox", { name: "practise Swap DV01 and P&L for a rate move" }));
    expect(screen.getByRole("button", { name: "Start focused practice" })).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "practise Forward-starting swaps and forward par rates" }));
    expect(screen.getByRole("button", { name: "Start mixed practice" })).toBeInTheDocument();
    await user.click(within(screen.getByRole("group", { name: "difficulty" })).getByRole("button", { name: "2" }));
    await user.click(within(screen.getByRole("group", { name: "question type" })).getByRole("button", { name: "Calculation" }));
    await user.click(within(screen.getByRole("group", { name: "number of questions" })).getByRole("button", { name: "5" }));
    await user.click(screen.getByRole("button", { name: "Start mixed practice" }));
    await waitFor(() => expect(h.server.log.some((l) => l.startsWith("start:"))).toBe(true));
    expect(JSON.parse(h.server.log[0].slice(6))).toEqual({ tracks: [], skills: ["swaps.dv01", "swaps.forward_start"], difficulty: 2, kind: "calculation", count: 5 });
  });

  it("counts the sources that match and refuses to start on none", async () => {
    const user = userEvent.setup();
    render(<Train />);
    await user.click(await screen.findByRole("checkbox", { name: "practise Swap DV01 and P&L for a rate move" }));
    expect(screen.getByText(/3 sources match/)).toBeInTheDocument();
    await user.click(within(screen.getByRole("group", { name: "difficulty" })).getByRole("button", { name: "3" }));
    expect(screen.getByText(/Nothing matches these filters/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start focused practice/ })).toBeDisabled();
  });

  it("lists a skill's real sources and practises one of them on its own", async () => {
    const user = userEvent.setup();
    render(<Train />);
    const row = (await screen.findByText("Swap DV01 and P&L for a rate move")).closest("li")!;
    await user.click(within(row).getByRole("button", { name: "questions" }));
    expect(within(row).getByText("swaps.dv01_pnl")).toBeInTheDocument();
    await user.click(within(row).getAllByRole("button", { name: "Practise this one" })[2]);
    await waitFor(() => expect(h.server.log[0]).toBe('start:{"template_id":"swaps.dv01_pnl"}'));
  });
});

describe("the question screen", () => {
  it("shows the stem and the first part only, with no answer, expected value or later prompt", async () => {
    await open();
    expect(screen.getByText(/EUR curves, 30Y/)).toBeInTheDocument();
    expect(screen.getByText("Which describes the position?")).toBeInTheDocument();
    expect(screen.queryByText(MULTI.steps[1].after.question!.parts_done[1].prompt)).toBeNull();          // part 2 waits for Continue
    expect(screen.queryByText(/WORKED SOLUTION/)).toBeNull();
    expect(screen.queryByText("Expected")).toBeNull();
    expect(screen.getAllByRole("radio")).toHaveLength(MULTI.start.question!.current!.kind === "choice" ? (MULTI.start.question!.current as { options: string[] }).options.length : 0);
  });

  it("selects an option by letter, submits with Enter, and shows submitted answer, result, expected and rationale as separate rows", async () => {
    const user = await open();
    await user.keyboard("b");
    expect(screen.getByRole("radio", { name: /^B/ })).toHaveAttribute("aria-checked", "true");
    expect(h.server.log.filter((l) => l.startsWith("answer"))).toEqual([]);          // choosing is not answering
    await user.keyboard("{Enter}");
    await screen.findByText("CORRECT");
    expect(h.server.log).toContain("answer:B");
    const rows = screen.getByText("Your answer").closest("dl")!;
    expect(within(rows).getByText("Expected")).toBeInTheDocument();
    expect(within(rows).getByText("Why")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).toBeNull();                                  // the options are gone: one answer per part
    expect(screen.getByRole("button", { name: /Next part/ })).toBeInTheDocument();
  });

  it("the next part appears only after Next, and the numeric part shows its unit, hint and how the entry was read", async () => {
    const user = await open();
    await user.keyboard("b{Enter}");
    await screen.findByText("CORRECT");
    expect(screen.queryByText(step(1).after.question!.parts_done[1].prompt)).toBeNull();
    await user.click(screen.getByRole("button", { name: /Next part/ }));
    const input = await screen.findByLabelText("your answer");
    expect(screen.getByText("EUR")).toBeInTheDocument();
    expect(screen.getByText(/k, m and bn suffixes are read/)).toBeInTheDocument();
    await user.type(input, "-811.7k");
    expect(await screen.findByText("read -811.7k")).toBeInTheDocument();             // asked of the server's own parser
    expect(h.server.log.filter((l) => l.startsWith("answer"))).toEqual(["answer:B"]);
  });

  it("a wrong numeric answer shows the grader's own words, the expected figure and the working, not an invented explanation", async () => {
    const user = await open();
    await user.keyboard("b{Enter}");
    await user.click(await screen.findByRole("button", { name: /Next part/ }));
    await user.type(await screen.findByLabelText("your answer"), "-811744.99");
    await user.keyboard("{Enter}");
    await screen.findByText("NOT CORRECT");
    expect(screen.getByText(/Right size, wrong sign/)).toBeInTheDocument();
    expect(screen.getByText("+€811.7k")).toBeInTheDocument();
    expect(screen.getByText(/first-order estimate/)).toBeInTheDocument();
  });

  it("an unreadable entry is refused with a message and cannot be submitted or marked", async () => {
    const user = await open(MULTI, { unreadable: /monkeys/ });
    await user.keyboard("b{Enter}");
    await user.click(await screen.findByRole("button", { name: /Next part/ }));
    await user.type(await screen.findByLabelText("your answer"), "12 monkeys");
    expect(await screen.findByText(/could not read a number/)).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: /Submit answer/ });
    expect(submit).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(h.server.log.filter((l) => l.startsWith("answer"))).toEqual(["answer:B"]);     // nothing was sent for marking
    expect(useTrain.getState().state?.phase).toBe("answering");
  });

  it("Skip is a result of its own, and the worked solution and the finish come with the last part", async () => {
    const user = await open();
    await user.keyboard("b{Enter}");
    await user.click(await screen.findByRole("button", { name: /Next part/ }));
    await user.type(await screen.findByLabelText("your answer"), "-811744.99{Enter}");
    await user.click(await screen.findByRole("button", { name: /Next part/ }));
    await screen.findByText(MULTI.steps[2].after.question!.parts_done[2].prompt);
    expect(screen.queryByText("WORKED SOLUTION")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Skip" }));
    await screen.findByText("SKIPPED");
    expect(screen.getByText("WORKED SOLUTION")).toBeInTheDocument();
    expect(screen.getByText(MULTI.steps[2].after.question!.solution![0])).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Finish session/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Finish session/ }));
    expect(await screen.findByText("Session complete")).toBeInTheDocument();
    expect(screen.getByText(/Replay what you missed \(1\)/)).toBeInTheDocument();
    expect(screen.getByText("basis.irs_vs_ois#1")).toBeInTheDocument();
  });

  it("a reload while a result is showing lands on the result, not on the next prompt", async () => {
    const user = await open();
    await user.keyboard("b{Enter}");
    await screen.findByText("CORRECT");
    const id = useTrain.getState().sessionId!;
    cleanup();
    useTrain.getState().reset();                                                    // the page is reloaded: the store is empty, the server still has the session
    render(<Train />);
    await useTrain.getState().resume(id);
    await screen.findByText("CORRECT");
    expect(screen.queryByText(step(1).after.question!.parts_done[1].prompt)).toBeNull();
    expect(screen.getByRole("button", { name: /Next part/ })).toBeInTheDocument();
  });
});

describe("the store only sends what the phase allows", () => {
  it("does not continue before an answer, answer twice, or submit an empty entry", async () => {
    await open();
    const t = useTrain.getState();
    await t.next();                                                                // answering: nothing to continue past
    await t.submit();                                                              // nothing chosen
    expect(h.server.log.filter((l) => l === "next" || l.startsWith("answer"))).toEqual([]);
    t.setDraft("B");
    await useTrain.getState().submit();
    await useTrain.getState().submit();                                            // already answered: one answer per part
    await useTrain.getState().skip();
    expect(h.server.log.filter((l) => l.startsWith("answer") || l === "skip")).toEqual(["answer:B"]);
    useTrain.getState().setDraft("A");                                             // editing is ignored while a result is showing
    expect(useTrain.getState().draft).toBe("B");
  });
});

describe("leaving a session and the summary", () => {
  it("ending a session asks first; Enter or Escape cannot answer or continue behind the dialog; ending keeps what was answered", async () => {
    const user = await open(FOCUS);
    await user.keyboard("a{Enter}");
    await screen.findByRole("button", { name: /Next question/ });
    await user.click(screen.getByRole("button", { name: /Catalogue/ }));
    const dlg = screen.getByRole("alertdialog");
    expect(within(dlg).getByText(/answered 1 part \(1 correct\)/)).toBeInTheDocument();
    (document.activeElement as HTMLElement).blur();                                // focus nowhere in particular: Enter still must not Continue
    await user.keyboard("{Enter}");
    expect(h.server.log).not.toContain("next");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: /Catalogue/ }));
    await user.click(screen.getByRole("button", { name: "End session" }));
    expect(await screen.findByText("Session ended early")).toBeInTheDocument();
    expect(h.server.log).toContain("finish");
  });

  it("with nothing answered, leaving goes straight back to the catalogue and records nothing", async () => {
    const user = await open();
    await user.click(screen.getByRole("button", { name: /Catalogue/ }));
    expect(await screen.findByText("Practise a skill")).toBeInTheDocument();
    expect(h.server.log.filter((l) => l === "finish")).toEqual([]);
    expect(sessionStorage.length).toBe(0);
  });

  it("the summary offers a replay of exactly the missed questions", async () => {
    const user = await open(FOCUS);
    await user.keyboard("a{Enter}");
    await user.click(await screen.findByRole("button", { name: /Next question/ }));
    await screen.findByText(/Question 2/);
    await user.keyboard("{Enter}");                                                // no option chosen: nothing is submitted
    expect(h.server.log.filter((l) => l.startsWith("answer"))).toHaveLength(1);
    await user.keyboard("a{Enter}");
    await user.click(await screen.findByRole("button", { name: /Finish session/ }));
    await screen.findByText("Session complete");
    await user.click(screen.getByRole("button", { name: /Replay what you missed/ }));
    await waitFor(() => expect(h.server.log.some((l) => l.includes('"ids":'))).toBe(true));
    expect(h.server.log.filter((l) => l.includes('"ids":')).pop()).toContain(FOCUS.summary.missed[0]);
  });
});
