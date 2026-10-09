import { beforeEach, describe, expect, it, vi } from "vitest";
import l1 from "../fixtures/l1_seed3.json";
import l2 from "../fixtures/l2_seed3.json";
import { type Fixture, fixtureServer } from "./fixtureServer";

const h = vi.hoisted(() => ({ server: null as unknown as ReturnType<typeof import("./fixtureServer").fixtureServer> }));
vi.mock("../api/client", () => ({
  ApiError: class extends Error {},
  api: new Proxy({}, { get: (_t, k: string) => (...a: unknown[]) => (h.server.api as unknown as Record<string, (...x: unknown[]) => unknown>)[k](...a) }),
}));
import { rememberedSession, useDesk } from "../desk/store";

const fx = (l2 as unknown as Fixture);
const quick = async () => {
  const s = useDesk.getState();
  s.setDraft({ kind: "rfq", priceText: "2.40" });
};

beforeEach(() => { sessionStorage.clear(); useDesk.getState().reset(); h.server = fixtureServer(fx); });

describe("the Live Desk store drives the real session contract", () => {
  it("starts on the first observation, awaiting a decision", async () => {
    await useDesk.getState().start(2, 5);
    const s = useDesk.getState();
    expect(s.phase).toBe("awaiting");
    expect(s.observation?.kind).toBe("rfq");
    expect(s.draft?.kind).toBe("rfq");
    expect(h.server.log).toEqual(["start"]);
  });

  it("will not arm an invalid draft, and says why", async () => {
    await useDesk.getState().start(2, 5);
    useDesk.getState().setDraft({ kind: "rfq", priceText: "banana" });
    useDesk.getState().arm();
    expect(useDesk.getState().phase).toBe("awaiting");
    expect(useDesk.getState().error).toMatch(/rate/i);
  });

  it("arming locks the ticket; editing is ignored until disarmed", async () => {
    await useDesk.getState().start(2, 5);
    await quick();
    useDesk.getState().arm();
    expect(useDesk.getState().phase).toBe("armed");
    useDesk.getState().setDraft({ kind: "rfq", priceText: "9.99" });
    expect(useDesk.getState().draft).toMatchObject({ priceText: "2.40" });
    useDesk.getState().disarm();
    expect(useDesk.getState().phase).toBe("awaiting");
  });

  it("commit reveals the result and holds back the next observation until Continue", async () => {
    await useDesk.getState().start(2, 5);
    await quick();
    useDesk.getState().arm();
    await useDesk.getState().commit();
    let s = useDesk.getState();
    expect(s.phase).toBe("settled");
    expect(s.observation).toBeNull();                    // nothing of the next screen is in the store
    expect(s.pending?.result.events.length).toBeGreaterThan(0);
    expect(s.transcript).toHaveLength(1);
    expect(h.server.log).toEqual(["start", "submit:rfq"]);        // no observation was requested after the commit
    await useDesk.getState().commit();                            // a second commit is not possible
    useDesk.getState().arm();
    expect(h.server.log).toEqual(["start", "submit:rfq"]);
    await useDesk.getState().next();
    s = useDesk.getState();
    expect(h.server.log).toEqual(["start", "submit:rfq", "next"]);
    expect(s.phase).toBe("awaiting");
    expect(s.pending).toBeNull();
    expect(s.observation?.episode.round).toBe(fx.steps[1].observation.episode.round);
  });

  it("plays a whole recorded episode to the finish and then loads the debrief in two steps", async () => {
    await useDesk.getState().start(2, 5);
    for (const step of fx.steps) {
      const st = useDesk.getState();
      expect(st.observation?.kind).toBe(step.observation.kind);
      useDesk.setState({ draft: st.draft, armed: null });
      // arm with the recorded decision's shape through the same path the UI uses
      const d = step.decision;
      if (d.type === "rfq") st.setDraft(d.level === null ? { kind: "rfq", priceText: "2.40" } : { kind: "rfq", priceText: (d.level * 100).toFixed(4) });
      if (d.type === "hedge") st.setDraft({ kind: "hedge", legs: d.trades.flatMap((t, i) => (t.kind === "swap" ? [{ id: i, side: t.side, tenor: t.tenor, sizeM: String(t.notional / 1e6) }] : [])), none: d.trades.length === 0, macro: null });
      useDesk.getState().arm();
      await useDesk.getState().commit();
      await useDesk.getState().next();
    }
    expect(useDesk.getState().phase).toBe("finished");
    await useDesk.getState().loadDebrief();
    const s = useDesk.getState();
    expect(s.debrief?.counterfactuals).toBeNull();
    expect(s.debriefFull?.counterfactuals).not.toBeNull();
    expect(h.server.log.filter((l) => l.startsWith("debrief"))).toEqual(["debrief:false", "debrief:true"]);
  });

  it("a refused decision changes nothing: back to awaiting with the message", async () => {
    await useDesk.getState().start(2, 5);
    h.server.api.submit = async () => { throw new Error("this prompt needs a rfq"); };
    await quick();
    useDesk.getState().arm();
    await useDesk.getState().commit();
    const s = useDesk.getState();
    expect(s.phase).toBe("awaiting");
    expect(s.error).toMatch(/needs a rfq/);
    expect(s.transcript).toHaveLength(0);
    expect(s.observation?.kind).toBe("rfq");
  });

  it("a reload while a result is pending lands on the result, with the transcript, never past it", async () => {
    await useDesk.getState().start(2, 5);
    await quick();
    useDesk.getState().arm();
    await useDesk.getState().commit();
    const id = useDesk.getState().sessionId!;
    useDesk.getState().reset();                                    // the page is reloaded: store is empty, the server still holds the session
    await useDesk.getState().resume(id);
    const s = useDesk.getState();
    expect(s.phase).toBe("settled");
    expect(s.observation).toBeNull();
    expect(s.pending?.result).toEqual(fx.steps[0].result);
    expect(s.transcript).toHaveLength(1);
  });
});

describe("level 1 fixture checkpoint", () => {
  it("is asked after the fill and graded on commit", async () => {
    const f1 = l1 as unknown as Fixture;
    h.server = fixtureServer(f1);
    await useDesk.getState().start(1, 3);
    expect(useDesk.getState().observation?.kind).toBe("quote");
    useDesk.getState().arm();
    await useDesk.getState().commit();
    await useDesk.getState().next();
    expect(useDesk.getState().observation?.kind).toBe("checkpoint");
    useDesk.getState().setDraft({ kind: "checkpoint", text: "-11.6k" });
    useDesk.getState().arm();
    expect(useDesk.getState().armed?.decision).toEqual({ type: "checkpoint", raw: "-11.6k" });
    await useDesk.getState().commit();
    expect(useDesk.getState().pending?.result.grade).not.toBeUndefined();
  });
});

describe("leaving an episode for the level menu", () => {
  it("returns to the menu from any decision state, forgets the session on this screen, and sends nothing", async () => {
    await useDesk.getState().start(2, 5);
    await quick();
    useDesk.getState().arm();
    expect(useDesk.getState().phase).toBe("armed");
    expect(useDesk.getState().leave()).toBe(true);
    let s = useDesk.getState();
    expect([s.phase, s.sessionId, s.armed, s.observation, s.draft]).toEqual(["idle", null, null, null, null]);
    expect(rememberedSession()).toBeNull();                          // a reload does not drop the trainee back into the abandoned episode
    expect(h.server.log).toEqual(["start"]);                         // no submit, no continue, no next observation

    await useDesk.getState().start(2, 5);                            // and from a settled result
    await quick(); useDesk.getState().arm(); await useDesk.getState().commit();
    expect(useDesk.getState().phase).toBe("settled");
    const before = [...h.server.log];
    expect(useDesk.getState().leave()).toBe(true);
    s = useDesk.getState();
    expect([s.phase, s.pending, s.transcript]).toEqual(["idle", null, []]);
    expect(h.server.log).toEqual(before);                            // leaving a result never advances it
  });

  it("will not leave while a commit or a continue is in flight", () => {
    for (const phase of ["starting", "submitting", "continuing"] as const) {
      useDesk.setState({ phase, sessionId: "x" });
      expect(useDesk.getState().leave()).toBe(false);
      expect(useDesk.getState().phase).toBe(phase);
    }
  });

  it("a start that returns after the screen was abandoned does not take the screen back", async () => {
    const orig = h.server.api.start;
    let release!: () => void;
    (h.server.api as unknown as Record<string, unknown>).start = (...a: unknown[]) => new Promise((res) => { release = () => res((orig as (...x: unknown[]) => unknown)(...a)); });
    const pending = useDesk.getState().start(2, 5);
    useDesk.getState().reset();
    release();
    await pending;
    expect(useDesk.getState().phase).toBe("idle");
    expect(useDesk.getState().observation).toBeNull();
    expect(rememberedSession()).toBeNull();
  });
});
