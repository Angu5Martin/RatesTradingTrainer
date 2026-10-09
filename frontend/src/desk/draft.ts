// Ticket drafts: what the trainee has typed so far, and the translation into the encoded decision the API accepts.

import type { EncodedDecision, EncodedTrade, ObservationView, SideWord } from "../api/types";
import { parseRatePct } from "../lib/format";
import { focusOf } from "./derive";
import { type Leg, describeTrade, hedgeLabel, legToTrade, quoteFromSkewWidth, skewWidthFromQuote } from "../lib/ticket";

export type Draft =
  | { kind: "quote"; bidText: string; offerText: string }
  | { kind: "rfq"; priceText: string }
  | { kind: "checkpoint"; text: string }
  | { kind: "hedge"; legs: Leg[]; none: boolean; macro: { label: string; trades: EncodedTrade[] } | null };

export const fmtRatePct = (r: number): string => (r * 100).toFixed(4);

export function initialDraft(obs: ObservationView): Draft {
  const f = focusOf(obs);
  if (obs.kind === "quote" && f) {
    const { bid, offer } = quoteFromSkewWidth(f.mid, 0, (f.offer - f.bid) * 1e4);
    return { kind: "quote", bidText: fmtRatePct(bid), offerText: fmtRatePct(offer) };
  }
  if (obs.kind === "rfq" && f && obs.inquiry) {
    const s = obs.inquiry.action === "pays" ? f.offer : f.bid;
    return { kind: "rfq", priceText: fmtRatePct(s) };
  }
  if (obs.kind === "checkpoint") return { kind: "checkpoint", text: "" };
  return { kind: "hedge", legs: [], none: false, macro: null };
}

export function quoteState(d: Extract<Draft, { kind: "quote" }>, mid: number): { bid: number | null; offer: number | null; skewBp: number | null; widthBp: number | null } {
  const bid = parseRatePct(d.bidText), offer = parseRatePct(d.offerText);
  if (bid === null || offer === null) return { bid, offer, skewBp: null, widthBp: null };
  const { skewBp, widthBp } = skewWidthFromQuote(mid, bid, offer);
  return { bid, offer, skewBp, widthBp };
}

export type DraftResult = { ok: true; decision: EncodedDecision; summary: string } | { ok: false; error: string };

export function draftToDecision(obs: ObservationView, d: Draft): DraftResult {
  if (d.kind === "quote") {
    const bid = parseRatePct(d.bidText), offer = parseRatePct(d.offerText);
    if (bid === null || offer === null) return { ok: false, error: "Enter a bid and an offer as rates in %, e.g. 2.8417" };
    if (offer <= bid) return { ok: false, error: "The offer (you receive fixed) must be above the bid (you pay fixed)" };
    return { ok: true, decision: { type: "quote", bid, offer }, summary: `Quote ${d.bidText}% / ${d.offerText}%` };
  }
  if (d.kind === "rfq") {
    const level = parseRatePct(d.priceText);
    if (level === null) return { ok: false, error: "Enter your price as a rate in %, e.g. 2.8465, or Pass" };
    return { ok: true, decision: { type: "rfq", level }, summary: `Price ${d.priceText}%` };
  }
  if (d.kind === "checkpoint") {
    if (!d.text.trim()) return { ok: false, error: "Enter your answer" };
    return { ok: true, decision: { type: "checkpoint", raw: d.text.trim() }, summary: `Answer ${d.text.trim()}` };
  }
  if (d.none) return { ok: true, decision: { type: "hedge", label: "Warehouse (no hedge)", trades: [] }, summary: "No trade (warehouse)" };
  if (d.macro && d.legs.length === 0) return { ok: true, decision: { type: "hedge", label: d.macro.label, trades: d.macro.trades }, summary: hedgeLabel(d.macro.trades) };
  const trades: EncodedTrade[] = [];
  for (const l of d.legs) {
    const t = legToTrade(l);
    if (!t) return { ok: false, error: l.product ? `Enter a size for the ${l.product.code} leg` : `Enter a size in EUR m for the ${l.side} ${l.tenor}Y leg` };
    trades.push(t);
  }
  if (!trades.length) return { ok: false, error: "Add a leg, or choose No trade" };
  void obs;
  return { ok: true, decision: { type: "hedge", label: hedgeLabel(trades), trades }, summary: trades.map(describeTrade).join(" + ") };
}

export function rfqPass(): DraftResult {
  return { ok: true, decision: { type: "rfq", level: null }, summary: "Pass" };
}

/** The legs the engine resolved a typed macro into (swaps, futures, the bond), as ordinary editable legs. */
export function legsFromTrades(trades: EncodedTrade[], nextId: number): Leg[] {
  return trades.map((t, i): Leg => {
    if (t.kind === "swap") return { id: nextId + i, side: t.side as SideWord, tenor: t.tenor, sizeM: (t.notional / 1e6).toFixed(1) };
    if (t.kind === "future") return { id: nextId + i, side: t.contracts >= 0 ? "receive" : "pay", tenor: 0, sizeM: String(Math.round(Math.abs(t.contracts))), product: { code: t.code, kind: "future" } };
    return { id: nextId + i, side: t.face >= 0 ? "receive" : "pay", tenor: 0, sizeM: (Math.abs(t.face) / 1e6).toFixed(1), product: { code: t.code, kind: "bond" } };
  });
}
