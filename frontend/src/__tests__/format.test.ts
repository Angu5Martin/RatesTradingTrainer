import { describe, expect, it } from "vitest";
import { bp, eur, eurM, parseRatePct, parseSizeM, pct } from "../lib/format";
import { crossCost, diffBp, legDv01, quoteFromSkewWidth, skewWidthFromQuote, streetFor } from "../lib/ticket";

describe("formatting follows the Python fmt_eur conventions", () => {
  it.each([[0.2, "€0"], [12, "+€12"], [-1348, "−€1.3k"], [81633.5, "+€81.6k"], [-2_940_000, "−€2.94m"], [999.4, "+€999"]])("eur(%s) = %s", (x, s) => expect(eur(x)).toBe(s));
  it("unsigned and sized forms", () => { expect(eur(125000, false)).toBe("€125.0k"); expect(eurM(150e6)).toBe("€150m"); expect(pct(0.028417)).toBe("2.8417%"); expect(bp(-0.04, 1)).toBe("0.0bp"); expect(bp(1.26)).toBe("+1.3bp"); });
});

describe("typed numbers", () => {
  it("rates in percent", () => { expect(parseRatePct("2.8465")).toBeCloseTo(0.028465); expect(parseRatePct("2,8465%")).toBeCloseTo(0.028465); });
  it.each(["", "abc", "0", "-1", "20", "2.8.4"])("rejects %j", (t) => expect(parseRatePct(t)).toBeNull());
  it("sizes in EUR millions", () => { expect(parseSizeM("150")).toBe(150e6); expect(parseSizeM("62.5m")).toBe(62.5e6); expect(parseSizeM("0")).toBeNull(); expect(parseSizeM("x")).toBeNull(); });
});

describe("ticket arithmetic is display arithmetic only", () => {
  it("bid and offer from skew and width, and back", () => {
    const { bid, offer } = quoteFromSkewWidth(0.02845, 0.5, 4);
    expect(bid).toBeCloseTo(0.02845 + (0.5 - 2) * 1e-4, 10);
    expect(offer).toBeCloseTo(0.02845 + (0.5 + 2) * 1e-4, 10);
    const back = skewWidthFromQuote(0.02845, bid, offer);
    expect(back.skewBp).toBeCloseTo(0.5, 6); expect(back.widthBp).toBeCloseTo(4, 6);
  });
  it("a client who pays fixed deals at the offer; one who receives, at the bid", () => {
    expect(streetFor("pays", { bid: 0.0283, offer: 0.0285 })).toBe(0.0285);
    expect(streetFor("receives", { bid: 0.0283, offer: 0.0285 })).toBe(0.0283);
  });
  it("leg DV01 is + for receive fixed and − for pay fixed; cost is |DV01| x bp", () => {
    expect(legDv01("receive", 100e6, 456)).toBeCloseTo(45600);
    expect(legDv01("pay", 100e6, 456)).toBeCloseTo(-45600);
    expect(crossCost(-45600, 0.11)).toBeCloseTo(5016);
    expect(diffBp(0.02846, 0.02845)).toBeCloseTo(0.1);
  });
});
