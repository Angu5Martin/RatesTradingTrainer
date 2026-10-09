// The browser's types and rules against REAL recorded sessions (dumped from the Python Session). If the Python contract drifts, these fail.
import { describe, expect, it } from "vitest";
import l1a from "../fixtures/l1_seed1.json";
import l1b from "../fixtures/l1_seed3.json";
import l2a from "../fixtures/l2_seed3.json";
import l2b from "../fixtures/l2_seed5.json";
import l3a from "../fixtures/l3_seed1.json";
import l3b from "../fixtures/l3_seed2.json";
import l4a from "../fixtures/l4_seed1.json";
import l4p from "../fixtures/l4_products.json";
import l5a from "../fixtures/l5_seed1.json";
import l5b from "../fixtures/l5_seed2.json";
import l5p from "../fixtures/l5_position.json";
import { type Fixture } from "./fixtureServer";

const FIXTURES: Record<string, Fixture> = { l1_seed1: l1a as unknown as Fixture, l1_seed3: l1b as unknown as Fixture, l2_seed3: l2a as unknown as Fixture, l2_seed5: l2b as unknown as Fixture,
  l3_seed1: l3a as unknown as Fixture, l3_seed2: l3b as unknown as Fixture, l4_seed1: l4a as unknown as Fixture, l4_products: l4p as unknown as Fixture,
  l5_seed1: l5a as unknown as Fixture, l5_seed2: l5b as unknown as Fixture, l5_position: l5p as unknown as Fixture };

// What must never reach the browser before the debrief (the same list the Python tests use for the public views).
const HIDDEN = ["informed", "posterior", "p_informed", "signal_right", "truth", "z", "uniform", "uniforms", "seed", "market_seed", "answer", "ctx", "lean", "leans", "toxicity", "evidence_vs_truth", "view_truth"];

function keys(x: unknown, out = new Set<string>()): Set<string> {
  if (Array.isArray(x)) x.forEach((v) => keys(v, out));
  else if (x && typeof x === "object") for (const [k, v] of Object.entries(x)) { out.add(k); keys(v, out); }
  return out;
}

describe.each(Object.entries(FIXTURES))("recorded session %s", (_name, fx) => {
  it("carries no hidden field in any observation or result", () => {
    for (const s of fx.steps) {
      const seen = keys([s.observation, s.result]);
      for (const h of HIDDEN) expect(seen.has(h), `${h} in ${s.observation.kind}`).toBe(false);
    }
  });

  it("every observation has the blocks the desk reads, and checkpoints never carry their answer", () => {
    for (const s of fx.steps) {
      const o = s.observation;
      expect(o.schema).toBe(1);
      expect(["quote", "rfq", "checkpoint", "hedge", "position", "overnight", "rehedge"]).toContain(o.kind);
      expect(o.input.type).toBeTruthy();
      if (o.kind !== "checkpoint") {
        expect(o.book).toBeTruthy();
        expect(o.market?.mode === "single" ? o.market.focus : o.market?.ladder.length).toBeTruthy();    // a focus tenor, or a ladder of tenors
      }
      if (o.market?.mode === "ladder") expect(o.market.ladder.map((r) => r.tenor)).toEqual([2, 5, 10, 30]);
      if (o.book?.buckets) { expect(o.book.buckets.map((b) => b.tenor)).toEqual([2, 5, 10, 30]); expect(o.book.slope).toBeTruthy(); }
      if (o.kind === "overnight") expect(typeof o.overnight?.time_pnl).toBe("number");
      if (o.kind === "position") expect(o.input.can_target).toBe(true);
      if (o.kind === "checkpoint") expect(Object.keys(o.checkpoint!).sort()).toEqual(["inquiry", "intro", "note", "prompt", "with_screen"]);
    }
  });

  it("every market move carries the par change at 2, 5, 10 and 30Y (the additive field the curve-change bars read)", () => {
    for (const s of fx.steps) for (const e of s.result.events) if (e.type === "market") expect(e.tenor_moves.map((t) => t.tenor)).toEqual([2, 5, 10, 30]);
  });

  it("level 5's hidden state is only in the debrief: live views carry the research view and the named clients' evidence, not their truth", () => {
    const live = JSON.stringify(fx.steps.map((s) => [s.observation, s.result]));
    expect(live).not.toMatch(/"informed"|"posteriors"|"right"|"view_truth"|"evidence_vs_truth"|P\(informed/);
    const l5 = fx.steps[0].observation.episode.level === 5;
    expect(fx.debrief_full.market_paths !== null).toBe(l5);
    if (l5) {
      expect(fx.debrief_full.market_paths!.yours.samples).toHaveLength(200);
      expect(fx.debrief_full.view_truth).toBeTruthy();
      for (const s of fx.steps) if (s.observation.conditions?.research) expect(Object.keys(s.observation.conditions.research).sort()).toEqual(["expected_per_step_bp", "per_step_bp", "reliability", "remaining_bp", "steps_left", "steps_total", "text", "total_bp"]);
    } else expect(fx.debrief_full.view_truth).toBeNull();
  });

  it("input.unit is a unit, not the hint (the fixed bug)", () => {
    for (const s of fx.steps) {
      const i = s.observation.input;
      if (i.type === "number") { expect(i.unit).toBeTruthy(); expect(i.unit).not.toBe(i.hint); expect(i.unit).not.toContain(" "); }
      if (i.type === "quote" || i.type === "rfq") expect(i.unit).toBe("%");
    }
  });

  it("the recorded decision is of the kind the prompt asks for", () => {
    const want = { quote: "quote", rfq: "rfq", checkpoint: "checkpoint", hedge: "hedge", position: "hedge", overnight: "hedge", rehedge: "hedge" } as const;
    for (const s of fx.steps) expect(s.decision.type).toBe(want[s.observation.kind]);
  });

  it("the live desk's results never quote the model's probability that a client is informed", () => {
    const blob = JSON.stringify(fx.steps.map((s) => s.result));
    expect(blob).not.toMatch(/P\(informed/);
    expect(blob).not.toContain("p_informed");
  });

  it("events are all of the types the result panel knows how to draw", () => {
    const known = new Set(["client_arrives", "passed", "fill", "checkpoint_recorded", "checkpoint_grade", "flat_book", "hedge_trade", "skipped_trade", "no_trade", "overnight", "market", "round_pnl"]);
    for (const s of fx.steps) for (const e of s.result.events) expect(known.has(e.type)).toBe(true);
  });

  it("the debrief keeps decision quality, outcome, luck and same-path policies as separate fields", () => {
    const d = fx.debrief_full;
    expect(d.luck.label).toBe("Expected P&L from execution uncertainty");
    expect(d.luck.luck).toBeCloseTo(d.luck.realised_pnl - d.luck.expected_pnl, 6);
    expect(d.counterfactuals?.policies.length).toBeGreaterThan(0);
    expect(fx.debrief.counterfactuals).toBeNull();
    expect(d.decisions.every((x) => x.reasons.length > 0)).toBe(true);
  });
});
