import { Chip, Panel } from "../components/ui";
import { tradeLine } from "./derive";
import type { GameState } from "./types";

const CAT_TONE = { experiment: "warn", information: "accent", resolution: "neg" } as const;

/** What happened in the round that was just played, in the order it happened. */
export function Report({ s }: { s: GameState }) {
  const r = s.last_report;
  const dec = (id: string) => s.markets.find((m) => m.id === id)?.decimals ?? 2;
  return (
    <Panel title={r ? `ROUND ${r.round} REPORT` : "ROUND REPORT"} aside={<span className="dim">{r ? `${r.events.length} events` : ""}</span>}>
      {!r ? <p className="dim">Post your markets, then play the round. Bots will look at your quotes; the report lists what they did.</p> : r.events.length === 0 ? <p className="dim">A quiet round: nobody traded and nothing changed.</p> : (
        <ul className="gm-events">
          {r.events.map((e, i) => e.type === "trade" ? (
            <li key={i} className={e.trade.phase === "B" ? "ev-fast" : ""}><span className="mk-id">{e.market}</span> {e.trade.phase === "B" ? "⚡ " : ""}{tradeLine(e.trade, dec(e.market))}
              {e.trade.edge !== undefined ? <span className={e.trade.edge < 0 ? "neg" : "pos"}> · edge {(e.trade.edge > 0 ? "+" : e.trade.edge < 0 ? "−" : "") + Math.abs(e.trade.edge).toFixed(dec(e.market))}</span> : null}</li>
          ) : e.type === "shock" ? (
            <li key={i} className="ev-shock"><Chip tone={CAT_TONE[e.category]}>{e.headline}</Chip> <span className="mk-id">{e.markets.join(" ")}</span><div>{e.text}</div></li>
          ) : e.type === "resolved" ? (
            <li key={i} className="ev-res"><Chip tone="pos">RESOLVED</Chip> <span className="mk-id">{e.market}</span> settled at <strong className="num">{e.settle}</strong>; position {e.position}; P&amp;L <strong className={`num ${e.pnl > 0 ? "pos" : e.pnl < 0 ? "neg" : ""}`}>{Math.round(e.pnl)}</strong></li>
          ) : (
            <li key={i}><Chip tone="accent">OPENED</Chip> <span className="mk-id">{e.market}</span> {e.title}</li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
