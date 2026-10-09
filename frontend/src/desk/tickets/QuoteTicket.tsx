import type { ObservationView } from "../../api/types";
import { PriceLadder } from "../../components/charts";
import { Panel } from "../../components/ui";
import { bp, pct } from "../../lib/format";
import { diffBp, quoteFromSkewWidth } from "../../lib/ticket";
import { focusOf } from "../derive";
import { type Draft, fmtRatePct, quoteState } from "../draft";

type QuoteDraft = Extract<Draft, { kind: "quote" }>;
export const SKEW_STEP = 0.05, SKEW_BIG = 0.25;

export function stepQuote(d: QuoteDraft, mid: number, dSkew: number, dWidth: number): QuoteDraft {
  const q = quoteState(d, mid);
  if (q.skewBp === null || q.widthBp === null) return d;
  const width = Math.max(0.1, +(q.widthBp + dWidth).toFixed(2));
  const { bid, offer } = quoteFromSkewWidth(mid, +(q.skewBp + dSkew).toFixed(2), width);
  return { kind: "quote", bidText: fmtRatePct(bid), offerText: fmtRatePct(offer) };
}

export function QuoteTicket({ obs, draft, setDraft, locked }: { obs: ObservationView; draft: QuoteDraft; setDraft: (d: Draft) => void; locked: boolean }) {
  const f = focusOf(obs)!;
  const q = quoteState(draft, f.mid);
  const step = (ds: number, dw: number) => setDraft(stepQuote(draft, f.mid, ds, dw));
  return (
    <Panel title={`YOUR TWO-WAY MARKET · ${f.tenor}Y`} aside={<span className="dim">fair value = mid {pct(f.mid)}</span>} className="ticket grow">
      <div className="qt-grid">
        <div className="qt-side">
          <label className="qt-label bid" htmlFor="qt-bid">BID <span className="dim">you pay fixed</span></label>
          <input id="qt-bid" className="in in-lg num" inputMode="decimal" value={draft.bidText} disabled={locked} onChange={(e) => setDraft({ ...draft, bidText: e.target.value })} aria-label="bid, percent" />
          <div className="qt-sub">{q.bid !== null ? <>vs street <span className="num">{bp(diffBp(q.bid, f.bid))}</span></> : <span className="neg">enter a rate</span>}</div>
        </div>
        <div className="qt-side">
          <label className="qt-label offer" htmlFor="qt-offer">OFFER <span className="dim">you receive fixed</span></label>
          <input id="qt-offer" className="in in-lg num" inputMode="decimal" value={draft.offerText} disabled={locked} onChange={(e) => setDraft({ ...draft, offerText: e.target.value })} aria-label="offer, percent" />
          <div className="qt-sub">{q.offer !== null ? <>vs street <span className="num">{bp(diffBp(q.offer, f.offer))}</span></> : <span className="neg">enter a rate</span>}</div>
        </div>
      </div>
      <div className="stepper-row">
        <div className="stepper"><span className="dim">SKEW</span>
          <button className="btn btn-sm" disabled={locked} onClick={() => step(-SKEW_STEP, 0)} aria-label="skew down">−</button>
          <span className="num stepper-v">{q.skewBp === null ? "–" : bp(q.skewBp, 2)}</span>
          <button className="btn btn-sm" disabled={locked} onClick={() => step(SKEW_STEP, 0)} aria-label="skew up">+</button>
        </div>
        <div className="stepper"><span className="dim">WIDTH</span>
          <button className="btn btn-sm" disabled={locked} onClick={() => step(0, -SKEW_STEP * 2)} aria-label="narrower">−</button>
          <span className="num stepper-v">{q.widthBp === null ? "–" : `${q.widthBp.toFixed(2)}bp`}</span>
          <button className="btn btn-sm" disabled={locked} onClick={() => step(0, SKEW_STEP * 2)} aria-label="wider">+</button>
        </div>
        <button className="btn btn-sm btn-ghost" disabled={locked} onClick={() => setDraft({ ...draft, ...{ bidText: fmtRatePct(f.bid), offerText: fmtRatePct(f.offer) } })}>match street</button>
      </div>
      <div className="ruler-wrap"><PriceLadder mid={f.mid} street={{ bid: f.bid, offer: f.offer }} mine={[{ value: q.offer, side: "offer", label: "your offer" }, { value: q.bid, side: "bid", label: "your bid" }]} /></div>
      <p className="hint dim">Skew moves the whole market against mid (+ = higher rates); width is offer − bid. The bid is where you pay fixed, the offer where you receive fixed.</p>
    </Panel>
  );
}
