// A stand-in for the HTTP layer that replays a REAL recorded session (fixtures/*.json, dumped from the Python Session by scripts/dump_fixtures.py).
// It enforces the same rules the real server does: one commit per prompt, the next observation only after Continue, the debrief only when done.
import type { DebriefView, DeskState, EncodedDecision, ObservationView, PendingState, StepResultView } from "../api/types";

export interface Fixture { steps: { observation: ObservationView; decision: EncodedDecision; result: StepResultView }[]; debrief: DebriefView; debrief_full: DebriefView }

export function fixtureServer(fx: Fixture, id = "fx1") {
  let i = 0;
  let pending: PendingState | null = null;
  const log: string[] = [];
  const episode = () => fx.steps[Math.min(i, fx.steps.length - 1)].observation.episode;
  const state = (): DeskState => ({
    id, episode: episode(),
    phase: pending ? "settled" : i >= fx.steps.length ? "done" : "awaiting",
    observation: pending || i >= fx.steps.length ? null : fx.steps[i].observation, pending,
  });
  return {
    log,
    api: {
      catalogue: async () => ({ episodes: [], train: { tracks: [], sources: 0 } }),
      live: async () => [],
      sessions: async () => [],
      start: async () => { log.push("start"); return state(); },
      state: async (_id: string, transcript = false) => ({ ...state(), transcript: transcript ? fx.steps.slice(0, i) : undefined }),
      parse: async (_id: string, text: string) => {
        log.push(`parse:${text}`);
        const swap = (tenor: number, side: "pay" | "receive", m: number) => ({ kind: "swap" as const, tenor, side, notional: m * 1e6 });
        const hedge = (label: string, trades: EncodedDecision extends infer D ? (D extends { trades: infer T } ? T : never) : never) => ({ ok: true as const, decision: { type: "hedge" as const, label, trades } });
        if (/^(\d+)%/.test(text)) return hedge(text, [swap(5, "pay", 100)]);
        if (text === "flatten") return hedge("Flatten level, slope and curvature (2Y + 5Y + 30Y)", [swap(2, "receive", 200), swap(5, "pay", 76), swap(30, "receive", 40)]);
        if (text === "switch") return hedge("Switch the product hedges into 5Y swaps", [{ kind: "future" as const, code: "FGBL", contracts: 1500 }, { kind: "bond" as const, code: "CTD", face: 40e6 }, swap(5, "pay", 600)]);
        if (text === "keep") return hedge("Keep the book as it is", []);
        const t = /^target (-?\d+)/.exec(text);
        if (t) return hedge(`Run ${Number(t[1]) / 1e3 >= 0 ? "+" : ""}${Number(t[1]) / 1e3}k DV01`, [swap(10, "pay", 50)]);
        return { ok: false as const, error: "unreadable" };
      },
      submit: async (_id: string, decision: EncodedDecision) => {
        if (pending) throw new Error("a decision is not being asked for now");
        const step = fx.steps[i];
        if (decision.type !== step.decision.type) throw new Error(`this prompt needs a ${step.observation.kind}`);
        log.push(`submit:${decision.type}`);
        pending = { observation: step.observation, decision, result: step.result };
        i += 1;
        return { result: step.result, state: state() };
      },
      next: async () => {
        if (!pending) throw new Error("no result is waiting");
        log.push("next");
        pending = null;
        return state();
      },
      debrief: async (_id: string, compare: boolean) => { log.push(`debrief:${compare}`); return compare ? fx.debrief_full : fx.debrief; },
    },
  };
}
