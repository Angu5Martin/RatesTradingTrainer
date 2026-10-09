import { describe, expect, it } from "vitest";
import type { EncodedTrade, ObservationView } from "../api/types";
import { focusOf } from "../desk/derive";
import { draftToDecision, initialDraft, legsFromTrades, rfqPass } from "../desk/draft";
import { legToTrade, productLegCost, productLegDv01 } from "../lib/ticket";
import { type Fixture } from "./fixtureServer";
import l1 from "../fixtures/l1_seed3.json";
import l2 from "../fixtures/l2_seed3.json";

const fx1 = l1 as unknown as Fixture, fx2 = l2 as unknown as Fixture;

describe("ticket drafts become the encoded decisions the API takes", () => {
  it("a quote starts at the street market and encodes bid and offer as decimal rates", () => {
    const obs = fx1.steps[0].observation;
    const d = initialDraft(obs);
    expect(d.kind).toBe("quote");
    const r = draftToDecision(obs, d);
    expect(r.ok && r.decision.type === "quote" && r.decision.offer > r.decision.bid && r.decision.bid < 0.2).toBe(true);
  });
  it("refuses a crossed or unreadable market with a message, not an exception", () => {
    const obs = fx1.steps[0].observation;
    expect(draftToDecision(obs, { kind: "quote", bidText: "2.9", offerText: "2.8" })).toMatchObject({ ok: false });
    expect(draftToDecision(obs, { kind: "quote", bidText: "x", offerText: "2.8" })).toMatchObject({ ok: false });
  });
  it("an RFQ starts at the street level on the side the client's request is priced on; pass is a first-class decision", () => {
    const obs = fx2.steps[0].observation;
    const d = initialDraft(obs);
    const street = obs.inquiry!.action === "pays" ? obs.market!.focus!.offer : obs.market!.focus!.bid;
    expect(d.kind === "rfq" && Number(d.priceText) / 100).toBeCloseTo(street, 6);
    expect(rfqPass()).toEqual({ ok: true, decision: { type: "rfq", level: null }, summary: "Pass" });
  });
  it("a hedge needs a leg with a size, or an explicit no trade", () => {
    const obs = fx2.steps.find((s) => s.observation.kind === "hedge")!.observation;
    const d = initialDraft(obs);
    expect(draftToDecision(obs, d)).toMatchObject({ ok: false });
    expect(draftToDecision(obs, { kind: "hedge", legs: [{ id: 1, side: "pay", tenor: 5, sizeM: "" }], none: false, macro: null })).toMatchObject({ ok: false });
    const ok = draftToDecision(obs, { kind: "hedge", legs: [{ id: 1, side: "pay", tenor: 5, sizeM: "150" }], none: false, macro: null });
    expect(ok).toMatchObject({ ok: true, decision: { type: "hedge", trades: [{ kind: "swap", tenor: 5, side: "pay", notional: 150e6 }] } });
    expect(draftToDecision(obs, { kind: "hedge", legs: [], none: true, macro: null })).toMatchObject({ ok: true, decision: { trades: [] } });
  });
  it("a checkpoint answer is sent as typed", () => {
    const obs = fx1.steps.find((s) => s.observation.kind === "checkpoint")!.observation;
    expect(draftToDecision(obs, { kind: "checkpoint", text: " -11.6k " })).toMatchObject({ ok: true, decision: { type: "checkpoint", raw: "-11.6k" } });
    expect(draftToDecision(obs, { kind: "checkpoint", text: "  " })).toMatchObject({ ok: false });
  });
});

describe("hedge legs beyond swaps (level 4) and the ladder's focus (levels 3-5)", () => {
  it("a futures leg and a bond leg encode to the trades the API takes, buy as + and sell as -", () => {
    expect(legToTrade({ id: 1, side: "pay", tenor: 0, sizeM: "1500", product: { code: "FGBL", kind: "future" } })).toEqual({ kind: "future", code: "FGBL", contracts: -1500 });
    expect(legToTrade({ id: 2, side: "receive", tenor: 0, sizeM: "40", product: { code: "CTD", kind: "bond" } })).toEqual({ kind: "bond", code: "CTD", face: 40e6 });
    expect(legToTrade({ id: 3, side: "pay", tenor: 5, sizeM: "100" })).toEqual({ kind: "swap", tenor: 5, side: "pay", notional: 100e6 });
    expect(legToTrade({ id: 4, side: "pay", tenor: 0, sizeM: "", product: { code: "FGBL", kind: "future" } })).toBeNull();
  });

  it("legs the engine resolved (swaps, futures, the bond) come back as ordinary editable legs and encode to the same trades", () => {
    const trades: EncodedTrade[] = [{ kind: "future", code: "FGBL", contracts: 1500 }, { kind: "bond", code: "CTD", face: -40e6 }, { kind: "swap", tenor: 5, side: "pay", notional: 600e6 }];
    const legs = legsFromTrades(trades, 10);
    expect(legs.map((l) => [l.side, l.product?.code ?? l.tenor, l.sizeM])).toEqual([["receive", "FGBL", "1500"], ["pay", "CTD", "40.0"], ["pay", 5, "600.0"]]);
    expect(legs.map(legToTrade)).toEqual(trades);
  });

  it("a product leg's own DV01 and cost are units times the line's per-unit figures, signed by direction", () => {
    expect(productLegDv01({ id: 1, side: "pay", tenor: 0, sizeM: "1500", product: { code: "FGBL", kind: "future" } }, 108.5)).toBeCloseTo(-162_750);
    expect(productLegDv01({ id: 1, side: "receive", tenor: 0, sizeM: "40", product: { code: "CTD", kind: "bond" } }, 830)).toBeCloseTo(33_200);
    expect(productLegCost({ id: 1, side: "pay", tenor: 0, sizeM: "1500", product: { code: "FGBL", kind: "future" } }, 5)).toBe(7500);
  });

  it("the focus of a ladder is the row of the tenor asked about, else the book's focus tenor; a single-tenor market keeps its own focus", () => {
    const ladder = [2, 5, 10, 30].map((t) => ({ tenor: t, mid: 0.02 + t / 1000, bid: 0.02 + t / 1000 - 1e-5, offer: 0.02 + t / 1000 + 1e-5, dv01_per_m: 100 * t, cost_bp: 0.05 }));
    const o = { market: { mode: "ladder", curve: [], focus: null, ladder, products: [] }, inquiry: { tenor: 5 }, book: { focus_tenor: 10 } } as unknown as ObservationView;
    expect(focusOf(o)?.tenor).toBe(5);
    expect(focusOf({ ...o, inquiry: null } as unknown as ObservationView)?.tenor).toBe(10);
    const single = { market: { mode: "single", focus: { tenor: 7, mid: 0.02, bid: 0.019, offer: 0.021, dv01_per_m: 650 }, ladder: [], curve: [], products: [] }, inquiry: null, book: null } as unknown as ObservationView;
    expect(focusOf(single)?.tenor).toBe(7);
    expect(focusOf({ market: null } as unknown as ObservationView)).toBeNull();
  });
});
