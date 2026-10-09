import type { Book, Conditions, EpisodeMeta } from "../api/types";
import { Chip, Gauge, Num } from "../components/ui";
import type { Phase } from "./machine";

const PHASE_LABEL: Partial<Record<Phase, string>> = { awaiting: "AWAITING DECISION", armed: "ARMED", submitting: "COMMITTING", settled: "DECISION SUBMITTED", continuing: "…", finished: "SESSION COMPLETE" };

export function TopBar(p: { episode: EpisodeMeta; round: number; phase: Phase; book: Book | null; conditions: Conditions | null; pnl: number; onReference: () => void; onLevels: () => void; levelsLocked: boolean }) {
  const { episode: e, book: b, conditions: c } = p;
  return (
    <header className="topbar">
      <button className="btn btn-ghost tb-back" onClick={p.onLevels} disabled={p.levelsLocked}
        title={p.levelsLocked ? "Wait for the request in flight to finish" : "Leave this episode and choose a level"}>‹ Levels</button>
      <div className="tb-id">
        <span className="tb-level">L{e.level}</span>
        <span className="tb-title" title={e.title}>{e.title.replace(/^Level \d: /, "")}</span>
      </div>
      <div className="tb-cell"><span className="tb-k">ROUND</span><span className="tb-v num">{Math.min(p.round + 1, e.rounds)}<span className="dim">/{e.rounds}</span></span></div>
      <div className="tb-cell"><span className="tb-k">STATE</span><span className={`tb-v tb-phase tb-${p.phase}`}>{PHASE_LABEL[p.phase] ?? p.phase.toUpperCase()}</span></div>
      {c ? <div className="tb-cell"><span className="tb-k">CONDITIONS</span><span className="tb-v"><Chip>vol {c.volatility.split(" ")[0]}</Chip> <Chip>liq {c.liquidity.split(" ")[0]}</Chip>{c.calendar ? <> <Chip tone="warn" title="a data release lands in the next step">release ×{c.calendar.vol_mult.toFixed(0)}</Chip></> : null}</span></div> : null}
      <div className="tb-spacer" />
      <div className="tb-cell"><span className="tb-k">P&amp;L</span><span className="tb-v tb-big"><Num v={p.pnl} /></span></div>
      {c?.research ? <div className="tb-cell" title={c.research.text}><span className="tb-k">VIEW</span><span className="tb-v num">{c.research.remaining_bp >= 0 ? "↑" : "↓"}{Math.abs(c.research.remaining_bp).toFixed(1)}bp <span className="dim">· {Math.round(c.research.reliability * 100)}%</span></span></div> : null}
      {b ? <div className="tb-gauge"><Gauge label="DV01" value={b.dv01} limit={b.limit_dv01} compact={!!b.slope} /></div> : null}
      {b?.slope ? <div className="tb-gauge"><Gauge label="slope" value={b.slope.exposure} limit={b.slope.limit} compact /></div> : null}
      <button className="btn btn-ghost" onClick={p.onReference} title="Conventions and training assumptions">Ref</button>
    </header>
  );
}
