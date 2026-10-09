import { useEffect, useState } from "react";
import { Gauge, Num } from "../components/ui";
import { credits, isDirty, lots, plural } from "./derive";
import { Detail } from "./Detail";
import { type Density, MarketCard, SettledRow } from "./MarketCard";
import { Portfolio } from "./Portfolio";
import { Report } from "./Report";
import { useGame } from "./store";

/** Card density from the number of LIVE markets (active, shocked or paused): few markets get room for their rules and recent trades, many get a denser grid.
 *  A deterministic function of the game state, so the layout only changes when a market opens or resolves, never while quoting. */
export function densityFor(live: number): Density {
  return live <= 2 ? "roomy" : live <= 4 ? "standard" : "dense";
}

type SideTab = "market" | "report";

/** The table: a summary strip; every live market as a card with its own quote; settled markets kept small below; on the side, the portfolio and a tabbed panel
 *  with the selected market in full or the report of the last round. */
export function Table({ onGuide }: { onGuide?: () => void }) {
  const s = useGame();
  const st = s.state!;
  const busy = s.busy !== null;
  const [tab, setTab] = useState<SideTab>("market");
  const lastRound = st.last_report?.round ?? 0;
  useEffect(() => { if (lastRound > 0) setTab("report"); }, [lastRound]);      // a round was just played: show what happened in it
  const dirty = st.markets.filter((m) => isDirty(m, s.drafts[m.id]));
  const live = st.markets.filter((m) => m.status === "active" || m.status === "shocked" || m.status === "paused");
  const settled = st.markets.filter((m) => m.status === "resolved");
  const coming = st.markets.filter((m) => m.status === "upcoming");
  const shocked = live.filter((m) => m.status === "shocked");
  const paused = live.filter((m) => m.status === "paused").length;
  const sel = st.markets.find((m) => m.id === s.selected);
  const select = (id: string) => { s.select(id); setTab("market"); };
  const p = st.portfolio;
  const last = st.round + 1 === st.rounds;
  const density = densityFor(live.length);
  return (
    <div className="gm" data-testid="game-table">
      <div className="gm-top">
        <div className="tb-id" title="MARKET MAKING GAME"><span className="tb-level">L{st.level}</span><span className="tb-title">{st.level_name}</span></div>
        <div className="tb-cell"><span className="tb-k">ROUND</span><span className="tb-v tb-big num" aria-label="round">{st.round + 1} / {st.rounds}</span></div>
        <div className="tb-cell gm-pnl"><span className="tb-k">P&amp;L</span>
          <span className="tb-v"><span className="tb-big" aria-label="total pnl"><Num v={p.pnl_total} f={credits} /></span>
            <span className="gm-split dim" title="Settled: final P&L of resolved markets. Open: the rest marked at YOUR mid, not at any hidden fair value.">settled <Num v={p.pnl_settled} f={credits} plain /> · open <Num v={p.pnl_open} f={credits} plain /></span></span></div>
        <div className="tb-cell"><span className="tb-k">MARKETS</span>
          <span className="tb-v gm-split"><span className="num">{live.length}</span> live{settled.length ? <> · <span className="num">{settled.length}</span> settled</> : null}{coming.length ? <> · <span className="num">{coming.length}</span> opening</> : null}
            {shocked.length ? <> · <span className="warn num">{shocked.length} shocked</span></> : null}{paused ? <> · <span className="num">{paused}</span> paused</> : null}</span></div>
        <div className="tb-cell"><span className="tb-k">INVENTORY</span><span className="tb-v gm-split" title="net and gross lots across open markets"><span className="num">{lots(p.net_lots)}</span> net · <span className="num">{p.gross_lots}</span> gross</span></div>
        {p.risk_budget ? <div className="tb-gauge"><Gauge value={p.risk_used} limit={p.risk_budget} label="Risk budget" f={(x) => String(Math.round(x))} compact /></div> : null}
        <span className="gm-actions">
        {onGuide ? <button className="btn btn-sm btn-ghost" onClick={onGuide} title="How to play well: overview, world markets, probability markets">How to</button> : null}
        {live.some((m) => m.status !== "paused") ? <button className="btn btn-sm" disabled={busy} onClick={() => void s.pauseAll(true)} title="pull every quote: nobody can trade, positions stay">Pause all</button> : null}
        {paused ? <button className="btn btn-sm" disabled={busy} onClick={() => void s.pauseAll(false)}>Resume all</button> : null}
        <button className="btn btn-sm btn-ghost" onClick={s.leave} title="Leave the table. The game is saved and can be resumed from the lobby.">Leave</button>
        <button className="btn btn-commit" disabled={busy} onClick={() => void s.advance()} data-testid="advance"
          title={dirty.length ? `sends ${plural(dirty.length, "edited quote")}, then plays the round` : "play the round: bots look at your quotes"}>
          {s.busy === "advancing" ? "Playing…" : `${dirty.length ? `Send ${dirty.length} & ` : ""}${last ? "Play the final round" : `Play round ${st.round + 1}`} ▶`}
        </button>
        </span>
      </div>
      {s.error ? <div className="alert gm-alert" role="alert">{s.error}</div> : null}
      {shocked.length ? (
        <div className="banner gm-banner" role="status">
          <span><strong>{plural(shocked.length, "market")} shocked.</strong> The rules, the information or the way it settles changed: read what changed, then re-quote or acknowledge.</span>
          <span className="gm-banner-ids">{shocked.map((m) => <button key={m.id} className="btn btn-sm" onClick={() => select(m.id)} aria-label={`show ${m.id}`}>{m.id}</button>)}</span>
        </div>
      ) : null}
      <div className="gm-main" data-density={density}>
        <div className="gm-left">
          {coming.length ? <div className="gm-coming" aria-label="markets not open yet"><span className="dim">Opening later:</span>{coming.map((m) => <span key={m.id} className="chip">{m.id} in {plural(m.opens_in ?? 0, "round")}</span>)}</div> : null}
          <ul className="mk-grid" aria-label="markets" data-density={density} data-count={live.length}>
            {live.map((m) => (
              <MarketCard key={m.id} m={m} draft={s.drafts[m.id]} selected={m.id === s.selected} busy={busy} sizeMax={st.size_max} density={density}
                onSelect={() => select(m.id)} onEdit={(patch) => s.edit(m.id, patch)} onSet={(d) => s.setDraft(m.id, d)} onDiscard={() => s.discardDraft(m.id)}
                onSend={() => void s.sendQuote(m.id)} onPause={(x) => void s.pause(m.id, x)} onAck={() => void s.ack(m.id)} />))}
          </ul>
          {settled.length ? (
            <section className="gm-settled" aria-label="settled markets">
              <h3 className="gm-sec">SETTLED <span className="dim num">{settled.length}</span></h3>
              <ul className="mk-settled">{settled.map((m) => <SettledRow key={m.id} m={m} selected={m.id === s.selected} onSelect={() => select(m.id)} />)}</ul>
            </section>
          ) : null}
        </div>
        <aside className="gm-side">
          <Portfolio s={st} selected={s.selected} onSelect={select} />
          <div className="gm-tabbed">
          <div className="gm-tabs" role="tablist" aria-label="details">
            <button role="tab" id="gm-tab-market" aria-selected={tab === "market"} aria-controls="gm-tabpanel" className={`seg-b ${tab === "market" ? "on" : ""}`} onClick={() => setTab("market")}>
              {sel ? `Market ${sel.id}` : "Market"}</button>
            <button role="tab" id="gm-tab-report" aria-selected={tab === "report"} aria-controls="gm-tabpanel" className={`seg-b ${tab === "report" ? "on" : ""}`} onClick={() => setTab("report")}>
              {st.last_report ? `Round ${st.last_report.round}` : "Round report"}{st.last_report?.events.length ? <span className="dim"> · {st.last_report.events.length}</span> : null}</button>
          </div>
          <div id="gm-tabpanel" role="tabpanel" aria-label={tab === "market" ? "Market detail" : "Report"}>
            {tab === "market" ? <Detail key={sel?.id ?? "none"} m={sel} coach={st.coach} /> : <Report s={st} onSelect={select} />}
          </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
