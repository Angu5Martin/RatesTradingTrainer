// The Live Desk phase machine. It is the only thing that decides what the screen may show:
//   awaiting -> armed -> submitting -> settled -> (continuing) -> awaiting | finished
// A result stays in `settled` until the trainee presses Continue; nothing can move from `settled` to the next observation except CONTINUE.

export type Phase = "idle" | "starting" | "awaiting" | "armed" | "submitting" | "settled" | "continuing" | "finished" | "error";
export type DeskEvent =
  | "START" | "STARTED_AWAITING" | "STARTED_SETTLED" | "STARTED_FINISHED"
  | "ARM" | "DISARM" | "COMMIT" | "COMMITTED" | "COMMIT_REFUSED"
  | "CONTINUE" | "CONTINUED_AWAITING" | "CONTINUED_FINISHED" | "FAIL" | "RESET";

const TABLE: Record<Phase, Partial<Record<DeskEvent, Phase>>> = {
  idle: { START: "starting", RESET: "idle" },
  starting: { STARTED_AWAITING: "awaiting", STARTED_SETTLED: "settled", STARTED_FINISHED: "finished", FAIL: "error" },
  awaiting: { ARM: "armed", RESET: "idle" },
  armed: { DISARM: "awaiting", COMMIT: "submitting", RESET: "idle" },
  submitting: { COMMITTED: "settled", COMMIT_REFUSED: "awaiting", FAIL: "error" },
  settled: { CONTINUE: "continuing", RESET: "idle" },
  continuing: { CONTINUED_AWAITING: "awaiting", CONTINUED_FINISHED: "finished", FAIL: "error" },
  finished: { RESET: "idle" },
  error: { RESET: "idle", START: "starting" },
};

/** The next phase, or null if the event is not allowed in this phase. */
export function transition(phase: Phase, ev: DeskEvent): Phase | null {
  return TABLE[phase][ev] ?? null;
}

/** Inputs are editable only while awaiting; armed locks them; a settled result shows no live ticket at all. */
export const inputsEditable = (p: Phase): boolean => p === "awaiting";
export const showsNextObservation = (p: Phase): boolean => p === "awaiting" || p === "armed" || p === "submitting";
export const showsResult = (p: Phase): boolean => p === "settled" || p === "continuing";
