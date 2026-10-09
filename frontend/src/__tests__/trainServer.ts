// A stand-in for the TRAIN endpoints that replays a REAL recorded QuestionSession (fixtures/train_*.json, dumped from the Python code by scripts/dump_fixtures.py).
// It keeps the server's rules: one answer per part, the next part or question only after Continue, an unreadable entry refused (not marked).
import type { PartResult, TrainState, TrainSummary } from "../api/types";

export interface TrainFixture {
  start: TrainState;
  steps: { answer: string | null; result: PartResult; after: TrainState; next: TrainState }[];
  summary: TrainSummary;
}

export function trainServer(fx: TrainFixture, opts: { unreadable?: RegExp } = {}) {
  let i = 0;
  let phase: "answering" | "feedback" = "answering";
  const log: string[] = [];
  const state = (): TrainState => (phase === "feedback" ? fx.steps[i].after : i === 0 ? fx.start : fx.steps[i - 1].next);
  return {
    log,
    api: {
      trainStart: async (b: unknown) => { log.push(`start:${JSON.stringify(b)}`); return state(); },
      trainState: async () => state(),
      trainCheck: async (_id: string, text: string) => {
        log.push(`check:${text}`);
        return opts.unreadable?.test(text) ? { ok: false as const, error: `could not read a number from '${text}'` } : { ok: true as const, read_as: `read ${text}` };
      },
      trainAnswer: async (_id: string, text: string, skip = false) => {
        if (phase !== "answering") throw new Error("there is nothing to answer now");
        if (!skip && opts.unreadable?.test(text)) { log.push(`refused:${text}`); throw new Error(`could not read a number from '${text}'`); }
        log.push(skip ? "skip" : `answer:${text}`);
        phase = "feedback";
        return { result: fx.steps[i].result, state: state() };
      },
      trainNext: async () => {
        if (phase !== "feedback") throw new Error("answer the current part first");
        log.push("next");
        phase = "answering";
        i += 1;
        return state();
      },
      trainFinish: async () => { log.push("finish"); return { ...fx.summary, ended_early: true }; },
      trainSummary: async () => fx.summary,
      trainHistory: async () => [],
      catalogue: async () => ({ episodes: [], train: (await import("../fixtures/train_catalogue.json")).default }),
    },
  };
}
