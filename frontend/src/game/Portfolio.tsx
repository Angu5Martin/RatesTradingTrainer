import { Chip, Gauge, Num, Panel } from "../components/ui";
import { credits, lots } from "./derive";
import type { GameState } from "./types";

/** The whole table at a glance: position, exposure and P&L in every market, with the totals. */
export function Portfolio({ s, selected, onSelect }: { s: GameState; selected: string | null; onSelect: (id: string) => void }) {
  const p = s.portfolio;
  return (
    <Panel title="PORTFOLIO" aside={<span className="dim num">{p.open_markets} open · {p.resolved_markets} resolved · {p.trades} trades</span>}>
      <table className="tbl gm-port">
        <thead><tr><th>Mkt</th><th>Status</th><th className="r">Left</th><th className="r">Pos</th><th className="r">Risk</th><th className="r">P&amp;L</th></tr></thead>
        <tbody>
          {s.markets.map((m) => (
            <tr key={m.id} className={m.id === selected ? "row-sel" : m.status === "resolved" ? "off" : ""} onClick={() => onSelect(m.id)} style={{ cursor: "pointer" }}>
              <td>{m.id}</td>
              <td>{m.status === "shocked" ? <Chip tone="warn">shocked</Chip> : m.status === "paused" ? <Chip>paused</Chip> : m.status === "resolved" ? <span className="dim">resolved</span> : m.status === "upcoming" ? <span className="dim">opens in {m.opens_in}</span> : <span>active</span>}</td>
              <td className="r num">{m.status === "resolved" || m.status === "upcoming" ? "–" : m.remaining}</td>
              <td className={`r num ${(m.position ?? 0) > 0 ? "long" : (m.position ?? 0) < 0 ? "short" : ""}`}>{m.status === "resolved" || m.status === "upcoming" ? "–" : lots(m.position ?? 0)}</td>
              <td className="r num">{m.status === "resolved" || m.status === "upcoming" ? "–" : Math.round(m.risk ?? 0)}</td>
              <td className="r">{m.status === "upcoming" ? "–" : <Num v={m.status === "resolved" ? m.pnl ?? 0 : m.open_pnl ?? 0} f={credits} />}</td>
            </tr>))}
          <tr className="tot"><td colSpan={3}><strong>Total</strong></td><td className="r num">{lots(p.net_lots)}</td><td className="r num">{Math.round(p.risk_used)}</td><td className="r"><Num v={p.pnl_total} f={credits} /></td></tr>
        </tbody>
      </table>
      {p.risk_budget ? <Gauge value={p.risk_used} limit={p.risk_budget} label="Firm-wide risk budget (1σ credits)" f={(x) => String(Math.round(x))} /> : null}
      <p className="dim hint">Open P&amp;L marks positions at YOUR mid, not at any hidden fair value. Resolved markets show the final P&amp;L. Risk = lots × lot value × the uncertainty left in the question (1σ, credits).</p>
    </Panel>
  );
}
