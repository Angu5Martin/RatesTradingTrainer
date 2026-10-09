import type { Book, ResultEvent } from "../api/types";
import { LimitThermometer, SignedBars } from "../components/charts";
import { Chip, Gauge, Num, Panel } from "../components/ui";
import { eur, eurM, pct } from "../lib/format";

export interface AddedHedge { label: string; code: string; kind: "future" | "bond"; quantity: number }
/** What a result adds to the book: swap rows and product hedges. */
export interface Added { swaps: Book["swaps"]; hedges: AddedHedge[] }
export const noAdded: Added = { swaps: [], hedges: [] };

/** Rows the result adds to the book, from public events (a client trade, hedge trades): shown only once the result is revealed. */
export function rowsFromEvents(events: ResultEvent[], round: number): Added {
  const out: Added = { swaps: [], hedges: [] };
  for (const e of events) {
    if (e.type === "fill" && e.filled) out.swaps.push({ label: `client, round ${round + 1}`, side: e.dealer_side, notional: e.notional, tenor: e.tenor, rate: e.rate });
    if (e.type === "hedge_trade" && e.kind === "swap") out.swaps.push({ label: `hedge, round ${round + 1}`, side: e.side, notional: e.notional, tenor: e.tenor, rate: e.rate });
    if (e.type === "hedge_trade" && e.kind === "future") out.hedges.push({ label: `hedge, round ${round + 1}`, code: e.code, kind: "future", quantity: e.contracts });
    if (e.type === "hedge_trade" && e.kind === "bond") out.hedges.push({ label: `hedge, round ${round + 1}`, code: e.code, kind: "bond", quantity: e.face });
  }
  return out;
}

const qty = (kind: "future" | "bond", q: number) => (kind === "bond" ? `${eurM(Math.abs(q))} face` : `${Math.abs(q).toLocaleString("en-US", { maximumFractionDigits: 0 })} contracts`);

/** The trades in the book: swaps, then the futures and bond hedges held (net). Takes the height it is given and scrolls inside. */
export function PositionsPanel({ book, added = noAdded, asAt, grow, shrink }: { book: Book; added?: Added; asAt?: boolean; grow?: boolean; shrink?: boolean }) {
  const n = book.swaps.length + book.hedges.length + added.swaps.length + added.hedges.length;
  return (
    <Panel title="POSITIONS" aside={asAt ? <Chip tone="warn">as at decision</Chip> : <span className="dim">{n} trade{n === 1 ? "" : "s"}</span>} className={`positions-panel ${grow ? "grow" : ""} ${shrink ? "shrink" : ""}`}>
      <table className="tbl positions">
        <thead><tr><th>Trade</th><th>Side</th><th className="r">Size</th><th className="r">Rate</th></tr></thead>
        <tbody>
          {book.swaps.map((r, i) => (
            <tr key={i}><td className="dim">{r.label}</td><td className={r.side === "receive" ? "long" : "short"}>{r.side === "receive" ? "REC" : "PAY"} {r.tenor}Y</td><td className="r">{eurM(r.notional)}</td><td className="r">{pct(r.rate)}</td></tr>
          ))}
          {book.hedges.map((h, i) => (
            <tr key={`h${i}`}><td className="dim">{h.kind === "bond" ? "bond hedge" : "futures hedge"}</td><td className={h.quantity > 0 ? "long" : "short"}>{h.quantity > 0 ? "LONG" : "SHORT"} {h.code}</td><td className="r" colSpan={2}>{qty(h.kind, h.quantity)}</td></tr>
          ))}
          {added.swaps.map((r, i) => (
            <tr key={`n${i}`} className="row-new"><td><Chip tone="accent">new</Chip> <span className="dim">{r.label}</span></td><td className={r.side === "receive" ? "long" : "short"}>{r.side === "receive" ? "REC" : "PAY"} {r.tenor}Y</td><td className="r">{eurM(r.notional)}</td><td className="r">{pct(r.rate)}</td></tr>
          ))}
          {added.hedges.map((h, i) => (
            <tr key={`nh${i}`} className="row-new"><td><Chip tone="accent">new</Chip> <span className="dim">{h.label}</span></td><td className={h.quantity > 0 ? "long" : "short"}>{h.quantity > 0 ? "BUY" : "SELL"} {h.code}</td><td className="r" colSpan={2}>{qty(h.kind, h.quantity)}</td></tr>
          ))}
          {n === 0 ? <tr><td colSpan={4} className="dim">flat</td></tr> : null}
        </tbody>
      </table>
    </Panel>
  );
}

/** The risk figures: DV01 as the headline against its limit on a vertical scale that takes the height it is given. */
export function RiskSummary(p: { book: Book; asAt?: boolean; dv01After?: number | null; hideDv01?: boolean }) {
  const b = p.book;
  return (
    <Panel title="RISK" aside={<span className="dim">DV01 = P&amp;L for a 1bp fall</span>} className="grow risk">
      {p.hideDv01 ? <p className="hint dim">The book below plus the trade just done. Work out your DV01 now.</p> : (
        <>
          <div className="risk-hero">
            <span className="rh-v"><Num v={p.dv01After ?? b.dv01} f={(x) => eur(x)} /></span>
            <span className="rh-k dim">{p.dv01After != null ? "DV01 after your decision" : p.asAt ? "DV01 at decision" : "book DV01"} · {Math.abs(p.dv01After ?? b.dv01) <= 1 ? "flat" : (p.dv01After ?? b.dv01) > 0 ? "long duration" : "short duration"}</span>
          </div>
          <Gauge label="limit use" value={p.dv01After ?? b.dv01} limit={b.limit_dv01} />
          <LimitThermometer value={b.dv01} after={p.dv01After} limit={b.limit_dv01} asAt={p.asAt} />
        </>
      )}
      {b.curve_position != null ? <div className="kv"><span className="dim">Curve position <span title="slope beyond your outright risk in the focus tenor">ⓘ</span></span><Num v={b.curve_position} /></div> : null}
      {p.hideDv01 ? null : <div className="kv"><span className="dim">P&amp;L so far</span><Num v={b.pnl_so_far} /></div>}
    </Panel>
  );
}

export type Exposures = Partial<Record<"level" | "slope" | "curvature" | "swap_spread" | "fut_basis", number>>;

const EXPO: { key: keyof Exposures; label: string; tip: string }[] = [
  { key: "curvature", label: "Curvature", tip: "P&L for a 1bp fall of the belly against the wings: per unit the 5Y falls 1bp and the 10Y 0.25bp, while the 2Y rises 0.125bp and the 30Y 0.5bp. No limit, but it is risk." },
  { key: "swap_spread", label: "Swap spread", tip: "EUR per bp of ASW tightening: futures and bonds hedge rates, not the swap-bond spread." },
  { key: "fut_basis", label: "Futures basis", tip: "EUR per tick of futures richening." },
];

/** Risk for a book that is a curve (levels 3-5): DV01 and slope against their limits, DV01 by bucket, and the exposures that have no limit. Bucket bars are the
 *  book as shown; after a commit `after` carries the exposures the assessment reports for the decision just taken (never before). */
export function CurveRisk(p: { book: Book; asAt?: boolean; after?: Exposures | null; hideDv01?: boolean }) {
  const b = p.book;
  const level = p.after?.level ?? b.dv01;
  const slopeNow = b.slope?.exposure ?? 0;
  const slope = p.after?.slope ?? slopeNow;
  const spreads = b.spreads ?? (p.after && (p.after.swap_spread || p.after.fut_basis) ? { swap_spread: 0, fut_basis: 0 } : null);
  const now: Exposures = { level: b.dv01, slope: slopeNow, curvature: b.curvature ?? 0, swap_spread: spreads?.swap_spread ?? 0, fut_basis: spreads?.fut_basis ?? 0 };
  const rows = EXPO.filter((e) => e.key === "curvature" || spreads);
  return (
    <Panel title="RISK" aside={<span className="dim">P&amp;L for a 1bp fall · slope: 1bp flattening</span>} className="grow risk curve-risk">
      {p.hideDv01 ? <p className="hint dim">The book below plus the trade just done. Work it out now.</p> : (
        <>
          <div className="risk-hero">
            <span className="rh-v"><Num v={level} f={(x) => eur(x)} /></span>
            <span className="rh-k dim">{p.after ? "DV01 after your decision" : p.asAt ? "DV01 at decision" : "book DV01"} · {Math.abs(level) <= 1 ? "flat" : level > 0 ? "long duration" : "short duration"}</span>
          </div>
          <Gauge label="DV01" value={level} limit={b.limit_dv01} />
          {b.slope ? <Gauge label="slope" value={slope} limit={b.slope.limit} /> : null}
        </>
      )}
      {b.buckets ? (
        <div className="bucket-block">
          <div className="sub-h"><span>DV01 BY BUCKET</span>{p.asAt ? <Chip tone="warn">as at decision</Chip> : <span className="dim">EUR per bp</span>}</div>
          <SignedBars labelWidth={34} minScale={25_000} eps={500} rows={b.buckets.map((k) => ({ label: `${k.tenor}Y`, value: k.dv01 }))} />
        </div>
      ) : null}
      <table className="tbl expo">
        <thead><tr><th>Exposure</th><th className="r">{p.after ? "at decision" : "now"}</th>{p.after ? <th className="r">after</th> : null}</tr></thead>
        <tbody>{rows.map((e) => (
          <tr key={e.key}><td title={e.tip}>{e.label} <span className="dim">ⓘ</span></td><td className="r"><Num v={now[e.key] ?? 0} /></td>{p.after ? <td className="r"><Num v={p.after[e.key] ?? 0} /></td> : null}</tr>))}</tbody>
      </table>
      {p.hideDv01 ? null : <div className="kv"><span className="dim">P&amp;L so far</span><Num v={b.pnl_so_far} /></div>}
    </Panel>
  );
}
