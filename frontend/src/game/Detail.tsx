import { Chip, Num, Panel } from "../components/ui";
import { credits, fmtPrice, lots, plural } from "./derive";
import type { MarketView } from "./types";

const CAT_TONE = { experiment: "warn", information: "accent", resolution: "neg" } as const;

/** The selected market in full: the exact question, the rules in force now, what has been announced, every trade. */
export function Detail({ m, coach, onClose }: { m: MarketView | undefined; coach: boolean; onClose?: () => void }) {
  if (!m) return <Panel title="MARKET"><p className="dim">Select a market to see its question, rules and trades.</p></Panel>;
  if (m.status === "upcoming") return <Panel title={`${m.id} · NOT OPEN YET`}><p className="dim">This market opens in {plural(m.opens_in ?? 0, "round")} and resolves in round {m.resolves_at}. Nothing else is shown until it opens.</p></Panel>;
  const resolved = m.status === "resolved";
  const showEdge = resolved || (coach && m.kind === "probability");
  return (
    <Panel title={`${m.id} · ${m.kind === "world" ? "WORLD KNOWLEDGE" : "PROBABILITY"}`} aside={onClose ? <button className="btn btn-sm btn-ghost" onClick={onClose}>Close</button> : <Chip tone={resolved ? "pos" : "accent"}>{m.status.toUpperCase()}</Chip>}>
      <h3 className="gm-q">{m.question}</h3>
      <dl className="dl gm-facts">
        <dt>Unit</dt><dd>{m.unit || "the value asked for"}</dd>
        <dt>Lot</dt><dd>1 lot = <span className="num">{m.lot_value}</span> credits per 1.0 of price · position limit ±{m.limit} lots</dd>
        <dt>Tick</dt><dd className="num">{m.tick} · quotes from {m.range[0]} to {m.range[1]}</dd>
        {!resolved && m.possible ? <><dt>Possible now</dt><dd className="num">{m.possible[0]} to {m.possible[1]}</dd></> : null}
        <dt>Resolves</dt><dd>{resolved ? `in round ${m.resolved_round}` : `after round ${m.resolves_at} (${plural(m.remaining ?? 0, "round")} left)`}</dd>
      </dl>
      {resolved ? (
        <div className="gm-final">
          <div>Settled at <strong className="num">{fmtPrice(m.settle ?? 0, m.decimals)}</strong> {m.unit}. Position at settlement <span className="num">{lots(m.position_at_settlement ?? 0)}</span>. P&amp;L <Num v={m.pnl ?? 0} f={credits} />.</div>
          {m.source ? <div className="dim">Source: {m.source}{m.as_of ? ` (as of ${m.as_of})` : ""}</div> : null}
        </div>
      ) : null}
      <h3>Rules in force</h3>
      <ul className="plain gm-rules">{(m.rules ?? []).map((r, i) => <li key={i}>{r}</li>)}</ul>
      <p className="dim hint">{m.resolution_rule}</p>
      {m.notes.length ? (
        <>
          <h3>Announced</h3>
          <ul className="gm-notes">{m.notes.map((n) => (
            <li key={n.id + n.round}><Chip tone={CAT_TONE[n.category]}>{n.headline}</Chip> <span className="dim">round {n.round}</span><div>{n.text}</div></li>))}</ul>
        </>
      ) : null}
      <h3>Trades <span className="dim">{m.trades?.length ?? 0}</span></h3>
      {m.trades && m.trades.length ? (
        <table className="tbl gm-trades">
          <thead><tr><th>Rd</th><th>Counterparty</th><th>I</th><th className="r">Lots</th><th className="r">Price</th><th className="r">Pos</th>{showEdge ? <th className="r" title="against the public fair value at that moment, per lot">Edge</th> : null}</tr></thead>
          <tbody>{[...m.trades].reverse().map((t) => (
            <tr key={t.n} className={t.phase === "B" ? "row-new" : ""}>
              <td className="num">{t.round}{t.phase === "B" ? "⚡" : ""}</td><td>{t.bot}{t.type ? <span className="dim"> {t.type}</span> : null}</td>
              <td className={t.me === "buy" ? "bid" : "offer"}>{t.me === "buy" ? "bought" : "sold"}</td>
              <td className="r">{t.qty}</td><td className="r">{fmtPrice(t.price, m.decimals)}</td><td className="r">{lots(t.position_after)}</td>
              {showEdge ? <td className={`r ${(t.edge ?? 0) > 0 ? "pos" : (t.edge ?? 0) < 0 ? "neg" : ""}`}>{t.edge === undefined ? "" : (t.edge > 0 ? "+" : t.edge < 0 ? "−" : "") + Math.abs(t.edge).toFixed(m.decimals)}</td> : null}
            </tr>))}</tbody>
        </table>
      ) : <p className="dim">No trades yet.</p>}
      <p className="dim hint">⚡ marks a trade made in the instant after a shock, against the quote you had not yet revised.</p>
    </Panel>
  );
}
