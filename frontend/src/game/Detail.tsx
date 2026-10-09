import { useState } from "react";
import { Chip, Num, Panel } from "../components/ui";
import { credits, fmtPrice, lots, plural } from "./derive";
import type { MarketView } from "./types";

const CAT_TONE = { experiment: "warn", information: "accent", resolution: "neg" } as const;
const SHOWN = 6;

/** The selected market in full, most decision-relevant first: the question, what has been announced (newest first), the rules in force, the facts of the
 *  contract, how it settles (folded), and the trades (the latest few, all on request). */
export function Detail({ m, coach }: { m: MarketView | undefined; coach: boolean }) {
  const [all, setAll] = useState(false);
  if (!m) return <Panel title="MARKET"><p className="dim">Select a market to see its question, rules and trades.</p></Panel>;
  if (m.status === "upcoming") return <Panel title={`${m.id} · NOT OPEN YET`}><p className="dim">This market opens in {plural(m.opens_in ?? 0, "round")} and resolves in round {m.resolves_at}. Nothing else is shown until it opens.</p></Panel>;
  const resolved = m.status === "resolved";
  const showEdge = resolved || (coach && m.kind === "probability");
  const trades = [...(m.trades ?? [])].reverse();
  const shown = all ? trades : trades.slice(0, SHOWN);
  return (
    <Panel title={`${m.id} · ${m.kind === "world" ? "WORLD KNOWLEDGE" : "PROBABILITY"}`} className="gm-detail" aside={<Chip tone={resolved ? "pos" : m.status === "shocked" ? "warn" : "accent"}>{m.status.toUpperCase()}</Chip>}>
      <h3 className="gm-q">{m.question}</h3>
      {resolved ? (
        <div className="gm-final">
          <div>Settled at <strong className="num">{fmtPrice(m.settle ?? 0, m.decimals)}</strong> {m.unit}. Position at settlement <span className="num">{lots(m.position_at_settlement ?? 0)}</span>. P&amp;L <Num v={m.pnl ?? 0} f={credits} />.</div>
          {m.source ? <div className="dim">Source: {m.source}{m.as_of ? ` (as of ${m.as_of})` : ""}</div> : null}
        </div>
      ) : null}
      {m.notes.length ? (
        <>
          <h4 className="gm-sub">Announced</h4>
          <ul className="gm-notes">{[...m.notes].reverse().map((n) => (
            <li key={n.id + n.round}><Chip tone={CAT_TONE[n.category]}>{n.headline}</Chip> <span className="dim">round {n.round}</span><div>{n.text}</div></li>))}</ul>
        </>
      ) : null}
      <h4 className="gm-sub">Rules in force</h4>
      <ul className="plain gm-rules">{(m.rules ?? []).map((r, i) => <li key={i}>{r}</li>)}</ul>
      <dl className="gm-facts">
        <div><dt>Unit</dt><dd>{m.unit || "the value asked for"}</dd></div>
        <div><dt>Tick</dt><dd className="num">{m.tick}</dd></div>
        <div><dt>Quotes</dt><dd className="num">{m.range[0]} to {m.range[1]}</dd></div>
        {!resolved && m.possible ? <div><dt>Possible now</dt><dd className="num">{m.possible[0]} to {m.possible[1]}</dd></div> : null}
        <div><dt>Lot</dt><dd><span className="num">{m.lot_value}</span> credits per 1.0</dd></div>
        <div><dt>Limit</dt><dd className="num">±{m.limit} lots</dd></div>
        <div><dt>Resolves</dt><dd>{resolved ? `in round ${m.resolved_round}` : `after round ${m.resolves_at} (${plural(m.remaining ?? 0, "round")} left)`}</dd></div>
      </dl>
      <details className="gm-how"><summary>How it settles</summary><p className="dim">{m.resolution_rule}</p></details>
      <h4 className="gm-sub">Trades <span className="dim">{trades.length}</span></h4>
      {trades.length ? (
        <>
          <table className="tbl gm-trades">
            <thead><tr><th>Rd</th><th>Counterparty</th><th>I</th><th className="r">Lots</th><th className="r">Price</th><th className="r">Pos</th>{showEdge ? <th className="r" title="against the public fair value at that moment, per lot">Edge</th> : null}</tr></thead>
            <tbody>{shown.map((t) => (
              <tr key={t.n} className={t.phase === "B" ? "row-new" : ""}>
                <td className="num">{t.round}{t.phase === "B" ? "⚡" : ""}</td><td>{t.bot}{t.type ? <span className="dim"> {t.type}</span> : null}</td>
                <td className={t.me === "buy" ? "bid" : "offer"}>{t.me === "buy" ? "bought" : "sold"}</td>
                <td className="r">{t.qty}</td><td className="r">{fmtPrice(t.price, m.decimals)}</td><td className="r">{lots(t.position_after)}</td>
                {showEdge ? <td className={`r ${(t.edge ?? 0) > 0 ? "pos" : (t.edge ?? 0) < 0 ? "neg" : ""}`}>{t.edge === undefined ? "" : (t.edge > 0 ? "+" : t.edge < 0 ? "−" : "") + Math.abs(t.edge).toFixed(m.decimals)}</td> : null}
              </tr>))}</tbody>
          </table>
          {trades.length > SHOWN ? <button className="btn btn-sm btn-ghost" onClick={() => setAll(!all)}>{all ? `Show the latest ${SHOWN}` : `Show all ${trades.length}`}</button> : null}
        </>
      ) : <p className="dim">No trades yet.</p>}
    </Panel>
  );
}
