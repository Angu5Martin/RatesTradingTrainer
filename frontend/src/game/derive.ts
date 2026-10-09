import type { MarketView, QuoteBody } from "./types";

/** What is typed in a market's quote boxes. Text, so a half-typed number is never silently changed. */
export interface Draft { bid: string; offer: string; size: number }

export const fmtPrice = (x: number, decimals: number): string => x.toFixed(decimals);

/** A signed whole number of credits with a thousands separator and a real minus sign; zero is "0". */
export function credits(x: number, signed = true): string {
  const r = Math.round(x);
  if (r === 0) return "0";
  const body = Math.abs(r).toLocaleString("en-US");
  return `${r < 0 ? "−" : signed ? "+" : ""}${body}`;
}
export const lots = (n: number): string => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n)}`;
export const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? "" : "s"}`;

export function draftFrom(m: MarketView): Draft {
  const q = m.quote;
  return q ? { bid: fmtPrice(q.bid, m.decimals), offer: fmtPrice(q.offer, m.decimals), size: q.size } : { bid: "", offer: "", size: 1 };
}

/** A price typed by the player, or null when it cannot be one: not a number, outside the market's range, or not on the tick. The server is the authority; this saves a round trip. */
export function parsePrice(raw: string, m: MarketView): number | null {
  const t = raw.trim().replace(",", ".");
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(t)) return null;
  const x = Number(t);
  if (!Number.isFinite(x) || x < m.range[0] - 1e-9 || x > m.range[1] + 1e-9) return null;
  const k = x / m.tick;
  return Math.abs(k - Math.round(k)) < 1e-6 ? Math.round(x * 10 ** m.decimals) / 10 ** m.decimals : null;
}

export type DraftCheck = { ok: true; body: QuoteBody } | { ok: false; why: string };
export function checkDraft(m: MarketView, d: Draft): DraftCheck {
  const b = parsePrice(d.bid, m), o = parsePrice(d.offer, m);
  if (b === null) return { ok: false, why: `bid: a multiple of ${m.tick} from ${m.range[0]} to ${m.range[1]}` };
  if (o === null) return { ok: false, why: `offer: a multiple of ${m.tick} from ${m.range[0]} to ${m.range[1]}` };
  if (o <= b) return { ok: false, why: "the offer must be above the bid" };
  return { ok: true, body: { market: m.id, bid: b, offer: o, size: d.size } };
}

export function isDirty(m: MarketView, d: Draft | undefined): boolean {
  if (!d) return false;
  const base = draftFrom(m);
  return d.bid.trim() !== base.bid || d.offer.trim() !== base.offer || d.size !== base.size;
}

/** Move both sides together by n ticks (skew the market), or widen / tighten it by n ticks each side. Needs a readable draft; otherwise returns it unchanged. */
export function nudge(m: MarketView, d: Draft, kind: "shift" | "width", n: number): Draft {
  const b = parsePrice(d.bid, m), o = parsePrice(d.offer, m);
  if (b === null || o === null) return d;
  const step = n * m.tick;
  let nb = kind === "shift" ? b + step : b - step, no = kind === "shift" ? o + step : o + step;
  if (no - nb < m.tick - 1e-9) return d;
  nb = Math.max(m.range[0], nb); no = Math.min(m.range[1], no);
  return { ...d, bid: fmtPrice(nb, m.decimals), offer: fmtPrice(no, m.decimals) };
}

export const STATUS_LABEL: Record<string, string> = { active: "ACTIVE", shocked: "SHOCKED", paused: "PAUSED", resolved: "RESOLVED", upcoming: "OPENS SOON" };

/** "Sold 2 @ 6.4 to CP-3 (Retail)" from my side. */
export function tradeLine(t: { me: "buy" | "sell"; qty: number; price: number; bot: string; type: string | null }, decimals: number): string {
  return `${t.me === "buy" ? "Bought" : "Sold"} ${t.qty} @ ${fmtPrice(t.price, decimals)} ${t.me === "buy" ? "from" : "to"} ${t.bot}${t.type ? ` (${t.type})` : ""}`;
}
