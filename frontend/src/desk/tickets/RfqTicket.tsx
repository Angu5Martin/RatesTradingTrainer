import type { ObservationView } from "../../api/types";
import { PriceLadder } from "../../components/charts";
import { Num, Panel } from "../../components/ui";
import { bp, eur, pct } from "../../lib/format";
import { diffBp, streetFor } from "../../lib/ticket";
import { focusOf } from "../derive";
import { type Draft } from "../draft";
import { parseRatePct } from "../../lib/format";

function tightness(youReceive: boolean, price: number, street: number): string {
  const d = diffBp(price, street) * (youReceive ? -1 : 1);       // + = tighter than the street for the client
  return Math.abs(d) < 0.05 ? "(at the street)" : d > 0 ? "(tighter: you win more often)" : "(wider: you win less often)";
}

type RfqDraft = Extract<Draft, { kind: "rfq" }>;

export function RfqTicket({ obs, draft, setDraft, locked, onPass }: { obs: ObservationView; draft: RfqDraft; setDraft: (d: Draft) => void; locked: boolean; onPass: () => void }) {
  const q = obs.inquiry!;
  const f = focusOf(obs)!;
  const youReceive = q.action === "pays";
  const price = parseRatePct(draft.priceText);
  const street = streetFor(q.action, f);
  const nudge = (d: number) => price !== null && setDraft({ kind: "rfq", priceText: ((price * 1e4 + d) / 1e4 * 100).toFixed(4) });
  return (
    <>
      <Panel title="YOUR PRICE" aside={<span className="dim">street {youReceive ? "offer" : "bid"} {pct(street)}</span>} className="ticket grow">
        <div className="rfq-row">
          <input className="in in-lg num" inputMode="decimal" value={draft.priceText} disabled={locked} aria-label="your price, percent" onChange={(e) => setDraft({ kind: "rfq", priceText: e.target.value })} />
          <span className="dim">%</span>
          <button className="btn btn-sm" disabled={locked} onClick={() => nudge(-0.1)}>−0.1bp</button>
          <button className="btn btn-sm" disabled={locked} onClick={() => nudge(0.1)}>+0.1bp</button>
          <button className="btn btn-sm btn-ghost" disabled={locked} onClick={onPass}>Pass <span className="kbd-inline">P</span></button>
        </div>
        <div className="ruler-wrap"><PriceLadder mid={f.mid} street={{ bid: f.bid, offer: f.offer }} mine={[{ value: price, side: youReceive ? "offer" : "bid", label: "your price" }]} /></div>
        <dl className="rfq-reads">
          <dt>vs mid (fair value)</dt><dd className="num">{price !== null ? bp(diffBp(price, f.mid)) : "–"}</dd>
          <dt>vs street {youReceive ? "offer" : "bid"}</dt>
          <dd><span className="num">{price !== null ? bp(diffBp(price, street)) : "–"}</span>{price !== null ? <span className="dim"> · {tightness(youReceive, price, street)}</span> : null}</dd>
          <dt>if it deals you</dt><dd><strong>{youReceive ? "RECEIVE" : "PAY"}</strong> fixed · DV01 <Num v={q.dv01} f={eur} /></dd>
        </dl>
      </Panel>
    </>
  );
}
