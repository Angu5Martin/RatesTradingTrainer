// What the screen shows is derived from the observations the trainee has been given so far, never stored twice.
import type { Conditions, FocusQuote, ObservationView } from "../api/types";
import type { DeskStore } from "./store";

type Slice = Pick<DeskStore, "transcript" | "observation" | "pending">;

/** Every observation the trainee has seen, oldest first (the one now being decided included). */
export function seen(s: Slice): ObservationView[] {
  const past = s.transcript.map((t) => t.observation);
  return s.observation ? [...past, s.observation] : past;
}

export function latest<K extends "book" | "conditions" | "market">(obs: ObservationView[], key: K): NonNullable<ObservationView[K]> | null {
  for (let i = obs.length - 1; i >= 0; i--) {
    const v = obs[i][key];
    if (v) return v as NonNullable<ObservationView[K]>;
  }
  return null;
}

export function curveOf(o: ObservationView): { tenor: number; mid: number }[] | null {
  const m = o.market;
  if (!m) return null;
  return m.curve.length ? m.curve : m.ladder.map((r) => ({ tenor: r.tenor, mid: r.mid }));
}

/** The curve at each distinct observation (checkpoints without a market are skipped), for the ghost and open lines. */
export function curveHistory(obs: ObservationView[]): { tenor: number; mid: number }[][] {
  return obs.map(curveOf).filter((c): c is { tenor: number; mid: number }[] => !!c);
}

export const latestConditions = (obs: ObservationView[]): Conditions | null => latest(obs, "conditions");

/** P&L so far as the trainee can know it: the latest book's figure, plus the edge of a fill that happened after that book was shown (a checkpoint
 *  follows a fill and carries no book of its own). Sums public event fields only. */
export function pnlNow(s: Slice): number {
  const obs = seen(s);
  let at = -1;
  for (let i = obs.length - 1; i >= 0; i--) if (obs[i].book) { at = i; break; }
  if (at < 0) return 0;
  let pnl = obs[at].book!.pnl_so_far;
  for (let i = at; i < s.transcript.length; i++) {
    const t = s.transcript[i];
    const rp = t.result.events.find((e) => e.type === "round_pnl");
    if (rp && rp.type === "round_pnl") { pnl = rp.total_pnl; continue; }
    for (const e of t.result.events) if (e.type === "fill" && e.filled) pnl += e.edge; else if (e.type === "hedge_trade") pnl += e.cost;
  }
  return pnl;
}

/** Cumulative P&L after each settled round, from the totals the results report. */
export function pnlPoints(transcript: Slice["transcript"]): { label: string; total: number }[] {
  return transcript.flatMap((t) => t.result.events.flatMap((e) => (e.type === "round_pnl" ? [{ label: `R${t.observation.episode.round + 1}`, total: e.total_pnl }] : [])));
}

/** The street the ticket prices against: the single-tenor market's focus, or, on a ladder, the row of the tenor being asked about (the request's, else the
 *  book's focus tenor). A selection among numbers the engine sent; nothing is computed. */
export function focusOf(o: ObservationView): FocusQuote | null {
  const m = o.market;
  if (!m) return null;
  if (m.focus) return m.focus;
  const t = o.inquiry?.tenor ?? o.book?.focus_tenor ?? null;
  const row = t === null ? undefined : m.ladder.find((r) => r.tenor === t);
  return row ? { tenor: row.tenor, mid: row.mid, bid: row.bid, offer: row.offer, dv01_per_m: row.dv01_per_m } : null;
}
