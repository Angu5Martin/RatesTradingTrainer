import { describe, expect, it } from "vitest";
import { type DeskEvent, type Phase, inputsEditable, showsNextObservation, showsResult, transition } from "../desk/machine";

const run = (from: Phase, evs: DeskEvent[]): Phase | null => evs.reduce<Phase | null>((p, e) => (p === null ? null : transition(p, e)), from);

describe("the Live Desk phase machine", () => {
  it("walks arm -> commit -> settled -> continue -> awaiting", () => {
    expect(run("idle", ["START", "STARTED_AWAITING", "ARM", "COMMIT", "COMMITTED", "CONTINUE", "CONTINUED_AWAITING"])).toBe("awaiting");
    expect(run("awaiting", ["ARM", "COMMIT", "COMMITTED", "CONTINUE", "CONTINUED_FINISHED"])).toBe("finished");
  });

  it("cannot reach the next observation from a settled result except through Continue", () => {
    for (const ev of ["ARM", "DISARM", "COMMIT", "COMMITTED", "STARTED_AWAITING", "CONTINUED_AWAITING", "CONTINUED_FINISHED"] as DeskEvent[]) {
      expect(transition("settled", ev)).toBeNull();
    }
    expect(transition("settled", "CONTINUE")).toBe("continuing");
    expect(transition("continuing", "CONTINUED_AWAITING")).toBe("awaiting");
  });

  it("allows one commit per prompt and only from an armed ticket", () => {
    expect(transition("awaiting", "COMMIT")).toBeNull();
    expect(transition("armed", "COMMIT")).toBe("submitting");
    expect(transition("submitting", "COMMIT")).toBeNull();
    expect(transition("submitting", "COMMITTED")).toBe("settled");
    expect(transition("submitting", "COMMIT_REFUSED")).toBe("awaiting");     // a refused decision changes nothing
    expect(transition("armed", "DISARM")).toBe("awaiting");
  });

  it("shows the next observation only while a decision is being taken, and the result only while it is settled", () => {
    const phases: Phase[] = ["idle", "starting", "awaiting", "armed", "submitting", "settled", "continuing", "finished", "error"];
    expect(phases.filter(showsNextObservation)).toEqual(["awaiting", "armed", "submitting"]);
    expect(phases.filter(showsResult)).toEqual(["settled", "continuing"]);
    expect(phases.filter(inputsEditable)).toEqual(["awaiting"]);
    expect(phases.filter((p) => showsNextObservation(p) && showsResult(p))).toEqual([]);
  });
});
