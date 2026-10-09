import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LiveSession } from "../api/types";

const h = vi.hoisted(() => ({
  sessions: [] as unknown[], log: [] as string[], failNext: null as string | null,
}));
vi.mock("../api/client", () => ({
  ApiError: class extends Error {},
  api: {
    live: async () => [...h.sessions],
    sessions: async () => [],
    discard: async (id: string) => {
      h.log.push(`discard:${id}`);
      if (h.failNext) { const m = h.failNext; h.failNext = null; throw new Error(m); }
      h.sessions = (h.sessions as LiveSession[]).filter((s) => s.id !== id);
      return { deleted: id };
    },
    discardAll: async () => { h.log.push("discardAll"); const ids = (h.sessions as LiveSession[]).map((s) => s.id); h.sessions = []; return { deleted: ids }; },
  },
}));
import { StartPanel } from "../desk/StartPanel";

const sess = (id: string, level: number, round: number, phase: "awaiting" | "settled" = "awaiting", in_history = false): LiveSession => ({
  id, phase, started: "2026-10-09T09:15:00", decisions: round, in_history,
  episode: { id: `mm.ep${level}`, level, title: `Level ${level}: ${level === 2 ? "Inventory loop" : "One client, one trade"}`, rounds: level === 2 ? 5 : 1, round, skill: "x", round_title: "" } as unknown as LiveSession["episode"],
});

const onStart = vi.fn(), onResume = vi.fn();
const show = () => render(<StartPanel onStart={onStart} onResume={onResume} busy={false} error={null} />);
beforeEach(() => { h.log = []; h.failNext = null; h.sessions = [sess("aaaaaa1111", 2, 2), sess("bbbbbb2222", 1, 0), sess("cccccc3333", 2, 4, "settled", true)]; onStart.mockClear(); onResume.mockClear(); });
afterEach(cleanup);

describe("deleting unfinished Live Desk sessions from the level menu", () => {
  it("lists each session with level, short id, start time and where it stands", async () => {
    show();
    await screen.findByRole("button", { name: "delete session aaaaaa" });
    const text = screen.getAllByRole("row").map((r) => r.textContent).join("\n");
    expect(text).toMatch(/L2.*Inventory loop/);
    expect(text).toContain("aaaaaa");
    expect(text).toContain("10-09 09:15");
    expect(text).toMatch(/round 3\/5 · awaiting decision/);
    expect(text).toMatch(/round 5\/5 · result waiting · already in history/);
  });

  it("needs a second click: Delete asks first and Cancel changes nothing", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "delete session aaaaaa" }));
    const group = screen.getByRole("group", { name: /delete session aaaaaa\?/ });
    expect(within(group).getByText(/Delete for good/)).toBeInTheDocument();
    expect(h.log).toEqual([]);
    await user.click(within(group).getByRole("button", { name: "Cancel" }));
    expect(h.log).toEqual([]);
    expect(screen.getAllByRole("button", { name: /^delete session/ })).toHaveLength(3);
  });

  it("confirming deletes that one session, refreshes the list and says so", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "delete session bbbbbb" }));
    await user.click(within(screen.getByRole("group", { name: /delete session bbbbbb\?/ })).getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Deleted the L1 session bbbbbb.");
    await waitFor(() => expect(screen.queryByRole("button", { name: "delete session bbbbbb" })).toBeNull());
    expect(screen.getAllByRole("button", { name: /^delete session/ })).toHaveLength(2);
    expect(h.log).toEqual(["discard:bbbbbb2222"]);
    expect(onResume).not.toHaveBeenCalled();                             // deleting never opens, resumes or starts anything
    expect(onStart).not.toHaveBeenCalled();
  });

  it("reports a failed delete as an error and still refreshes from the server", async () => {
    const user = userEvent.setup();
    show();
    h.failNext = "unknown session";
    await user.click(await screen.findByRole("button", { name: "delete session aaaaaa" }));
    await user.click(within(screen.getByRole("group")).getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not delete: unknown session");
    expect(screen.getAllByRole("button", { name: /^delete session/ })).toHaveLength(3);
  });

  it("Delete all also asks first, and says finished episodes are untouched", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: /Delete all unfinished/ }));
    expect(screen.getByText(/Delete all 3 unfinished sessions for good\?/)).toBeInTheDocument();
    expect(screen.getByText(/Finished episodes are kept for Review/)).toBeInTheDocument();
    expect(h.log).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Delete all" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Deleted 3 unfinished sessions.");
    await waitFor(() => expect(screen.queryByText("IN PROGRESS")).toBeNull());
  });

  it("Resume still resumes", async () => {
    const user = userEvent.setup();
    show();
    await user.click((await screen.findAllByRole("button", { name: "Resume" }))[0]);
    expect(onResume).toHaveBeenCalledWith("aaaaaa1111");
  });
});
