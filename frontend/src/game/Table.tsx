import { Num } from "../components/ui";
import { Gauge } from "../components/ui";
import { credits, isDirty, plural } from "./derive";
import { Detail } from "./Detail";
import { MarketCard } from "./MarketCard";
import { Portfolio } from "./Portfolio";
import { Report } from "./Report";
import { useGame } from "./store";

/** The table: every open market as a card with its own quote, the selected market in full, the portfolio, and the report of the last round. */
export function Table() {
  const s = useGame();
  const st = s.state!;
  const busy = s.busy !== null;
  const dirty = st.markets.filter((m) => isDirty(m, s.drafts[m.id]));
  const live = st.markets.filter((m) => m.status !== "resolved" && m.status !== "upcoming");
  const coming = st.markets.filter((m) => m.status === "upcoming");
  const shocked = live.filter((m) => m.status === "shocked").length;
  const sel = st.markets.find((m) => m.id === s.selected);
  const anyPaused = live.some((m) => m.status === "paused");
  const anyUnpaused = live.some((m) => m.status !== "paused");
  const p = st.portfolio;
  const last = st.round + 1 === st.rounds;
  return (
    <div className="gm" data-testid="game-table">
      <div className="gm-top">
        <div className="tb-id"><span className="tb-level">L{st.level}</span><span className="tb-title">MARKET MAKING GAME</span><span className="dim">{st.level_name}</span></div>
        <div className="tb-cell"><span className="tb-k">ROUND</span><span className="tb-v tb-big num" aria-label="round">{st.round + 1} / {st.rounds}</span></div>
        <div className="tb-cell"><span className="tb-k">SETTLED P&amp;L</span><span className="tb-v tb-big"><Num v={p.pnl_settled} f={credits} /></span></div>
        <div className="tb-cell"><span className="tb-k">OPEN P&amp;L (AT YOUR MID)</span><span className="tb-v tb-big"><Num v={p.pnl_open} f={credits} /></span></div>
        <div className="tb-cell"><span className="tb-k">TOTAL</span><span className="tb-v tb-big" aria-label="total pnl"><Num v={p.pnl_total} f={credits} /></span></div>
        <div className="tb-cell"><span className="tb-k">NET / GROSS LOTS</span><span className="tb-v num">{p.net_lots > 0 ? "+" : ""}{p.net_lots} / {p.gross_lots}</span></div>
        {p.risk_budget ? <div className="tb-gauge"><Gauge value={p.risk_used} limit={p.risk_budget} label="Risk budget" f={(x) => String(Math.round(x))} compact /></div> : null}
        <span className="tb-spacer" />
        {anyUnpaused ? <button className="btn btn-sm" disabled={busy} onClick={() => void s.pauseAll(true)} title="pull every quote: nobody can trade, positions stay">Pause all</button> : null}
        {anyPaused ? <button className="btn btn-sm" disabled={busy} onClick={() => void s.pauseAll(false)}>Resume all</button> : null}
        <button className="btn btn-sm btn-ghost" onClick={s.leave} title="Leave the table. The game is saved and can be resumed from the lobby.">Leave</button>
        <button className="btn btn-commit" disabled={busy} onClick={() => void s.advance()} data-testid="advance"
          title={dirty.length ? `sends ${plural(dirty.length, "edited quote")}, then plays the round` : "play the round: bots look at your quotes"}>
          {s.busy === "advancing" ? "Playing…" : `${dirty.length ? `Send ${dirty.length} & ` : ""}${last ? "Play the final round" : `Play round ${st.round + 1}`} ▶`}
        </button>
      </div>
      {s.error ? <div className="alert gm-alert" role="alert">{s.error}</div> : null}
      {shocked ? <div className="banner gm-banner" role="status"><span><strong>{plural(shocked, "market")} shocked.</strong> The rules, the information or the way it settles changed. Read what changed (right), then re-quote or acknowledge.</span></div> : null}
      <div className="gm-main">
        <div className="gm-left">
        {coming.length ? <div className="gm-coming" aria-label="markets not open yet"><span className="dim">Opening later:</span>{coming.map((m) => <span key={m.id} className="chip">{m.id} in {plural(m.opens_in ?? 0, "round")}</span>)}</div> : null}
        <ul className="mk-grid" aria-label="markets">
          {st.markets.filter((m) => m.status !== "upcoming").map((m) => (
            <MarketCard key={m.id} m={m} draft={s.drafts[m.id]} selected={m.id === s.selected} busy={busy} sizeMax={st.size_max}
              onSelect={() => s.select(m.id)} onEdit={(patch) => s.edit(m.id, patch)} onSet={(d) => s.setDraft(m.id, d)} onDiscard={() => s.discardDraft(m.id)}
              onSend={() => void s.sendQuote(m.id)} onPause={(x) => void s.pause(m.id, x)} onAck={() => void s.ack(m.id)} />))}
        </ul>
        </div>
        <aside className="gm-side">
          <Detail m={sel} coach={st.coach} />
          <Portfolio s={st} selected={s.selected} onSelect={s.select} />
          <Report s={st} />
        </aside>
      </div>
    </div>
  );
}
