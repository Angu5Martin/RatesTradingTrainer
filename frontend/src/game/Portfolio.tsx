import { Chip, Num, Panel } from "../components/ui";
import { credits, lots } from "./derive";
import type { GameState } from "./types";

/** The whole table at a glance: status, rounds left, position, risk and P&L in every market, with the totals. Click a row to see that market. */
export function Portfolio({ s, selected, onSelect }: { s: GameState; selected: string | null; onSelect: (id: string) => void }) {
  const p = s.portfolio;
  return (
    <Panel title="PORTFOLIO" className="gm-port-panel" aside={<span className="dim num">{p.trades} trades</span>}>
      <table className="tbl gm-port">
        <thead><tr><th>Mkt</th><th>Status</th><th className="r" title="rounds left">Left</th><th className="r">Pos</th><th className="r" title="lots × lot value × the uncertainty left (1σ, credits)">Risk</th><th className="r" title="open markets at YOUR mid; settled markets final">P&amp;L</th></tr></thead>
        <tbody>
          {s.markets.map((m) => (
            <tr key={m.id} className={m.id === selected ? "row-sel" : m.status === "resolved" ? "off" : ""} onClick={() => onSelect(m.id)} style={{ cursor: "pointer" }}>
              <td>{m.id}</td>
              <td>{m.status === "shocked" ? <Chip tone="warn">shocked</Chip> : m.status === "paused" ? <Chip>paused</Chip> : m.status === "resolved" ? <span className="dim">settled</span> : m.status === "upcoming" ? <span className="dim">opens in {m.opens_in}</span> : <span>active</span>}</td>
              <td className="r num">{m.status === "resolved" || m.status === "upcoming" ? "–" : m.remaining}</td>
              <td className={`r num ${(m.position ?? 0) > 0 ? "long" : (m.position ?? 0) < 0 ? "short" : ""}`}>{m.status === "resolved" || m.status === "upcoming" ? "–" : lots(m.position ?? 0)}</td>
              <td className="r num">{m.status === "resolved" || m.status === "upcoming" ? "–" : Math.round(m.risk ?? 0)}</td>
              <td className="r">{m.status === "upcoming" ? "–" : <Num v={m.status === "resolved" ? m.pnl ?? 0 : m.open_pnl ?? 0} f={credits} />}</td>
            </tr>))}
          <tr className="tot"><td colSpan={3}><strong>Total</strong></td><td className="r num">{lots(p.net_lots)}</td>
            <td className="r num" title={p.risk_budget ? "used / firm-wide budget" : undefined}>{Math.round(p.risk_used)}{p.risk_budget ? <span className="dim">/{p.risk_budget}</span> : null}</td><td className="r"><Num v={p.pnl_total} f={credits} /></td></tr>
        </tbody>
      </table>
      <p className="dim hint">Open P&amp;L is at YOUR mid. Risk = lots × lot value × the uncertainty left (1σ, credits).</p>
    </Panel>
  );
}
