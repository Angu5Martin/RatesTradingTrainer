import { describe, expect, it } from "vitest";
import { checkDraft, credits, draftFrom, fmtPrice, isDirty, lots, nudge, parsePrice, plural, tradeLine } from "../game/derive";
import type { MarketView } from "../game/types";

const m = (over: Partial<MarketView> = {}): MarketView => ({
  id: "M1", title: "Sum of 2d6", kind: "probability", category: "dice", unit: "points", tick: 0.1, decimals: 1, lot_value: 50, range: [0, 100], status: "active", opens_at: 0, resolves_at: 6, limit: 5, notes: [],
  quote: null, ...over,
});

describe("price entry", () => {
  it("reads decimals, commas and plain integers on the tick", () => {
    expect(parsePrice("6.5", m())).toBe(6.5);
    expect(parsePrice(" 7,3 ", m())).toBe(7.3);
    expect(parsePrice("7", m())).toBe(7);
  });
  it("refuses text, off-tick prices and prices outside the range", () => {
    for (const bad of ["", "abc", "6.55", "-1", "101", "1e3", "6.5.1"]) expect(parsePrice(bad, m())).toBeNull();
  });
  it("does not let floating point noise through: 0.3 stays 0.3", () => { expect(parsePrice("0.3", m())).toBe(0.3); expect(parsePrice("1.1", m())).toBe(1.1); });
  it("works on a coarse tick and a fine one", () => {
    expect(parsePrice("1790", m({ tick: 1, decimals: 0, range: [1000, 2025] }))).toBe(1790);
    expect(parsePrice("1790.5", m({ tick: 1, decimals: 0, range: [1000, 2025] }))).toBeNull();
    expect(parsePrice("6.55957", m({ tick: 0.001, decimals: 3, range: [4, 10] }))).toBeNull();
    expect(parsePrice("6.559", m({ tick: 0.001, decimals: 3, range: [4, 10] }))).toBe(6.559);
  });
});

describe("drafts", () => {
  it("starts blank for an unquoted market and mirrors the live quote otherwise", () => {
    expect(draftFrom(m())).toEqual({ bid: "", offer: "", size: 1 });
    expect(draftFrom(m({ quote: { bid: 6.5, offer: 7.5, size: 2, set_round: 0, stale: false } }))).toEqual({ bid: "6.5", offer: "7.5", size: 2 });
  });
  it("is dirty only when it differs from the live quote", () => {
    const q = m({ quote: { bid: 6.5, offer: 7.5, size: 1, set_round: 0, stale: false } });
    expect(isDirty(q, undefined)).toBe(false);
    expect(isDirty(q, { bid: "6.5", offer: "7.5", size: 1 })).toBe(false);
    expect(isDirty(q, { bid: "6.4", offer: "7.5", size: 1 })).toBe(true);
    expect(isDirty(q, { bid: "6.5", offer: "7.5", size: 2 })).toBe(true);
  });
  it("checks a draft: both sides readable, offer above bid", () => {
    expect(checkDraft(m(), { bid: "6.5", offer: "7.5", size: 2 })).toEqual({ ok: true, body: { market: "M1", bid: 6.5, offer: 7.5, size: 2 } });
    expect(checkDraft(m(), { bid: "7.5", offer: "7.5", size: 1 })).toMatchObject({ ok: false });
    expect(checkDraft(m(), { bid: "x", offer: "7.5", size: 1 })).toMatchObject({ ok: false, why: expect.stringContaining("bid") });
    expect(checkDraft(m(), { bid: "6.5", offer: "", size: 1 })).toMatchObject({ ok: false, why: expect.stringContaining("offer") });
  });
  it("nudges the whole market, or its width, a tick at a time and never crosses or leaves the range", () => {
    const d = { bid: "6.5", offer: "7.5", size: 1 };
    expect(nudge(m(), d, "shift", 1)).toEqual({ bid: "6.6", offer: "7.6", size: 1 });
    expect(nudge(m(), d, "shift", -1)).toEqual({ bid: "6.4", offer: "7.4", size: 1 });
    expect(nudge(m(), d, "width", 1)).toEqual({ bid: "6.4", offer: "7.6", size: 1 });
    expect(nudge(m(), d, "width", -1)).toEqual({ bid: "6.6", offer: "7.4", size: 1 });
    expect(nudge(m(), { bid: "7.4", offer: "7.5", size: 1 }, "width", -1)).toEqual({ bid: "7.4", offer: "7.5", size: 1 });   // would cross: unchanged
    expect(nudge(m(), { bid: "", offer: "7.5", size: 1 }, "shift", 1)).toEqual({ bid: "", offer: "7.5", size: 1 });          // unreadable: unchanged
  });
});

describe("display", () => {
  it("formats credits with a real minus, a plus and thousands separators", () => {
    expect(credits(1234.4)).toBe("+1,234"); expect(credits(-340)).toBe("−340"); expect(credits(0.2)).toBe("0"); expect(credits(5000, false)).toBe("5,000");
  });
  it("formats lots, prices and plurals", () => {
    expect(lots(3)).toBe("+3"); expect(lots(-2)).toBe("−2"); expect(lots(0)).toBe("0");
    expect(fmtPrice(6.5, 2)).toBe("6.50"); expect(plural(1, "round")).toBe("1 round"); expect(plural(2, "round")).toBe("2 rounds");
  });
  it("describes a trade from my side: a sale to a bot that lifted my offer, a purchase from one that hit my bid", () => {
    expect(tradeLine({ me: "sell", qty: 2, price: 7.5, bot: "CP-3", type: "Retail" }, 1)).toBe("Sold 2 @ 7.5 to CP-3 (Retail)");
    expect(tradeLine({ me: "buy", qty: 1, price: 6.5, bot: "CP-1", type: null }, 1)).toBe("Bought 1 @ 6.5 from CP-1");
  });
});
