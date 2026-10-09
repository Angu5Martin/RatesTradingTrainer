// Display arithmetic for tickets. This is input transformation and presentation of numbers the engine already gave
// (mid, street, DV01 per EUR 1m, cost in bp): it is NOT pricing, risk or grading, and it never computes a change to the book.

import type { Action, EncodedDecision, EncodedTrade, SideWord } from "../api/types";

export const BP = 1e-4;
const r8 = (x: number): number => Math.round(x * 1e10) / 1e10;

/** Bid and offer (decimal rates) from a skew and width in bp around the mid. */
export function quoteFromSkewWidth(mid: number, skewBp: number, widthBp: number): { bid: number; offer: number } {
  return { bid: r8(mid + (skewBp - widthBp / 2) * BP), offer: r8(mid + (skewBp + widthBp / 2) * BP) };
}

export function skewWidthFromQuote(mid: number, bid: number, offer: number): { skewBp: number; widthBp: number } {
  return { skewBp: ((bid + offer) / 2 - mid) / BP, widthBp: (offer - bid) / BP };
}

export const diffBp = (a: number, b: number): number => (a - b) / BP;

/** The street level for the side a client's request is priced on: a client who PAYS fixed deals at the dealer's offer. */
export const streetFor = (action: Action, street: { bid: number; offer: number }): number => (action === "pays" ? street.offer : street.bid);

/** A swap leg's own DV01 (EUR per bp, + = long duration = receive fixed) from the ladder's DV01 per EUR 1m. */
export const legDv01 = (side: SideWord, notional: number, dv01PerM: number): number => (side === "receive" ? 1 : -1) * (notional / 1e6) * dv01PerM;

/** Indicative cost of crossing = |DV01| x cost in bp (the ladder's half-spread). */
export const crossCost = (dv01: number, costBp: number): number => Math.abs(dv01) * costBp;

/** A hedge leg being built. A swap leg: side and tenor, size in EUR m. A product leg (futures, the CTD bond): `product` names it, `side` receive = buy (long
 *  duration) and pay = sell, and `sizeM` holds contracts for a future or EUR m face for the bond. */
export interface Leg { id: number; side: SideWord; tenor: number; sizeM: string; product?: { code: string; kind: "future" | "bond" } }

export function legToTrade(l: Leg): EncodedTrade | null {
  const n = Number(l.sizeM.replace(",", "."));
  if (!Number.isFinite(n) || n <= 0) return null;
  const sign = l.side === "receive" ? 1 : -1;
  if (l.product?.kind === "future") return { kind: "future", code: l.product.code, contracts: sign * n };
  if (l.product?.kind === "bond") return { kind: "bond", code: l.product.code, face: sign * n * 1e6 };
  return { kind: "swap", tenor: l.tenor, side: l.side, notional: n * 1e6 };
}

/** A product leg's own DV01 and indicative cost of crossing, from the product line's numbers (units x DV01 per unit; units x cost per unit). */
export const productLegDv01 = (l: Leg, dv01PerUnit: number): number => (l.side === "receive" ? 1 : -1) * Number(l.sizeM.replace(",", ".")) * dv01PerUnit;
export const productLegCost = (l: Leg, costPerUnit: number): number => Math.abs(Number(l.sizeM.replace(",", "."))) * costPerUnit;

export function describeTrade(t: EncodedTrade): string {
  if (t.kind === "swap") return `${t.side === "pay" ? "Pay" : "Receive"} fixed €${(t.notional / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })}m ${t.tenor}Y`;
  if (t.kind === "future") return `${t.contracts < 0 ? "Sell" : "Buy"} ${Math.abs(t.contracts).toLocaleString("en-US", { maximumFractionDigits: 0 })} ${t.code}`;
  return `${t.face < 0 ? "Sell" : "Buy"} €${(Math.abs(t.face) / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })}m ${t.code}`;
}

export function describeDecision(d: EncodedDecision): string {
  if (d.type === "quote") return `Quote ${(d.bid * 100).toFixed(4)}% / ${(d.offer * 100).toFixed(4)}%`;
  if (d.type === "rfq") return d.level === null ? "Pass" : `Price ${(d.level * 100).toFixed(4)}%`;
  if (d.type === "checkpoint") return `Answer ${d.raw}`;
  return d.trades.length ? d.trades.map(describeTrade).join(" + ") : "No trade (warehouse)";
}

export function hedgeLabel(trades: EncodedTrade[]): string {
  return trades.length ? trades.map(describeTrade).join(" + ") : "Warehouse (no hedge)";
}
