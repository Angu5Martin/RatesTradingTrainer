import { useEffect, useState } from "react";
import { Chip, Num, Panel } from "../components/ui";
import { credits, fmtPrice } from "./derive";
import { useGame } from "./store";
import type { Debrief as D, DebriefMarket } from "./types";

const dp = (m: DebriefMarket) => Math.max(0, Math.min(4, (String(m.lot_value).length > 3 ? 2 : 1)));
const CAUSE: Record<string, string> = { good: "good trades", luck: "unlucky (price was fair)", lucky: "lucky (price was poor)", stale: "stale quote", mispriced: "mispriced quote", informed: "lost to an informed trader", "informed-priced": "informed trader, but spread paid for it" };

/** The debrief: the answers, every trade, and where the P&L came from. Opened only after the last market has resolved; it names the hidden things. */
export function Debrief({ onGuide }: { onGuide?: () => void }) {
  const s = useGame();
  const d = s.debrief;
  useEffect(() => { if (!d) void s.loadDebrief(); }, [d]);                           // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return <div className="gm-debrief"><p className="dim">Loading the debrief…</p>{s.error ? <div className="alert">{s.error}</div> : null}</div>;
  const t = d.totals;
  return (
    <div className="gm-debrief" data-testid="game-debrief">
      <header className="gm-intro">
        <h1>DEBRIEF</h1>
        <p className="dim">Level {d.level} · seed <span className="num">{d.seed}</span> (replays this exact table) · {d.markets.length} markets · {d.game.trades} trades</p>
        <div className="row-gap"><button className="btn btn-primary" onClick={s.leave}>Back to the lobby</button>{onGuide ? <> <button className="btn" onClick={onGuide}>How to read this debrief</button></> : null}</div>
      </header>

      <Panel title="WHERE THE P&L CAME FROM" aside={<span className="dim">credits</span>}>
        <div className="gm-hero"><div><span className="hero-k dim">Total P&amp;L</span><span className="hero-v num" aria-label="final pnl"><Num v={t.pnl} f={credits} /></span></div>
          <div><span className="hero-k dim">Decision result</span><span className="hero-v num"><Num v={t.decision_result} f={credits} /></span></div>
          <div><span className="hero-k dim">Luck</span><span className="hero-v num"><Num v={t.luck} f={credits} /></span></div></div>
        <table className="tbl gm-attr">
          <tbody>
            <tr><td>Spread capture</td><td className="r"><Num v={t.spread_capture} f={credits} /></td><td className="dim">half your quoted spread on each lot traded</td></tr>
            <tr><td>Mispricing</td><td className="r"><Num v={t.mispricing} f={credits} /></td><td className="dim">how far your mid was from fair value, on the side that was traded (negative when it sat on the wrong side)</td></tr>
            <tr className="tot"><td><strong>Edge</strong></td><td className="r"><Num v={t.decision_edge} f={credits} /></td><td className="dim">what your trades were worth against fair value when they happened</td></tr>
            <tr><td>Adverse selection</td><td className="r"><Num v={t.adverse_selection} f={credits} /></td><td className="dim">what informed counterparties took after trading with you: the cost the spread is there to cover</td></tr>
            <tr className="tot"><td><strong>Decision result</strong></td><td className="r"><Num v={t.decision_result} f={credits} /></td><td className="dim">edge + adverse selection: what your quoting achieved given who you traded with</td></tr>
            <tr><td>News drift</td><td className="r"><Num v={t.news_drift} f={credits} /></td><td className="dim">fair value moving after you traded (shocks, clues), against uninformed traders: luck</td></tr>
            <tr><td>Settlement luck</td><td className="r"><Num v={t.settlement_luck} f={credits} /></td><td className="dim">the answer falling above or below its expectation: luck</td></tr>
            <tr className="tot"><td><strong>Total</strong></td><td className="r"><Num v={t.pnl} f={credits} /></td><td className="dim">= decision result + luck, exactly</td></tr>
          </tbody>
        </table>
        <p className="dim hint">Fair value = the exact expectation of the answer given everything that had been announced (for world questions: the crowd&apos;s belief, which you may have beaten with your own knowledge: that shows up as luck here).</p>
      </Panel>

      <div className="gm-two">
        <Panel title="KEY DECISIONS">
          {d.decisions.length ? <ul className="plain gm-decisions">{d.decisions.map((x, i) => <li key={i}><Chip tone={x.kind === "good" ? "pos" : "warn"}>{x.kind}</Chip> <span className="mk-id">{x.market}</span> <span className="dim">R{x.round}</span> {x.text}</li>)}</ul> : <p className="dim">No standout decisions: a quiet game.</p>}
          <h3>Every trade, sorted</h3>
          <ul className="gm-causes">{Object.entries(d.trade_causes).map(([k, n]) => <li key={k}><span className="num">{n}</span> {CAUSE[k] ?? k}</li>)}</ul>
        </Panel>
        <Panel title="COUNTERPARTIES REVEALED">
          <table className="tbl"><thead><tr><th>CP</th><th>Who</th><th className="r">Trades</th><th className="r">Edge you got</th><th className="r">Your result</th></tr></thead>
            <tbody>{d.counterparties.map((c) => <tr key={c.id} title={c.description}><td>{c.id}</td><td>{c.label}</td><td className="r num">{c.trades}</td><td className="r"><Num v={c.edge_given} f={credits} /></td><td className="r"><Num v={c.my_result} f={credits} /></td></tr>)}</tbody></table>
          <p className="dim hint">Edge you got = measured against fair value when you traded. Your result = what the trades finally made. A big gap means they knew something.</p>
        </Panel>
      </div>

      {d.markets.map((m) => <MarketDebrief key={m.id} m={m} d={d} />)}

      <Panel title="CONVENTIONS"><pre className="gm-conv">{d.convention}</pre></Panel>
    </div>
  );
}

function MarketDebrief({ m, d }: { m: DebriefMarket; d: D }) {
  const [open, setOpen] = useState(false);
  const places = dp(m);
  return (
    <Panel title={`${m.id} · ${m.title}`} aside={<span><Num v={m.pnl.total} f={credits} /> <button className="btn btn-sm btn-ghost" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} detail</button></span>}>
      <p className="gm-q">{m.question}</p>
      <p className="dim">Answer: <strong className="num" style={{ color: "var(--text-1)" }}>{m.settle_text}</strong>{m.unit ? ` (${m.unit})` : ""}{m.source ? ` · source: ${m.source}${m.as_of ? ` (as of ${m.as_of})` : ""}` : ""} · resolved after round {m.resolved_round} · position at settlement <span className="num">{m.position_at_settlement}</span> · fair value just before: <span className="num">{fmtPrice(m.final_fair, 2)}</span></p>
      <div className="gm-mini">
        <span>Spread <Num v={m.pnl.spread_capture} f={credits} /></span><span>Mispricing <Num v={m.pnl.mispricing} f={credits} /></span>
        <span>Adverse sel. <Num v={m.pnl.adverse_selection} f={credits} /></span><span>News <Num v={m.pnl.news_drift} f={credits} /></span><span>Settlement <Num v={m.pnl.settlement_luck} f={credits} /></span>
      </div>
      {m.shocks.length ? (
        <table className="tbl"><thead><tr><th>Shock</th><th>What changed</th><th className="r">Fair moved</th><th className="r">Your quote was off by</th><th>Re-quoted at once?</th></tr></thead>
          <tbody>{m.shocks.map((x) => <tr key={x.id}><td><Chip>{x.headline}</Chip> <span className="dim">R{x.round}</span></td><td>{x.text}</td><td className="r num">{x.fair_moved_sd.toFixed(2)}σ</td>
            <td className="r num">{x.quote_was_off_by_sd === null ? "no quote" : `${x.quote_was_off_by_sd.toFixed(2)}σ`}</td><td>{x.requoted_at_once ? <span className="pos">yes</span> : <span className="neg">no</span>}</td></tr>)}</tbody></table>
      ) : <p className="dim">No shock hit this market.</p>}
      {open ? (
        <>
          <h3>Trades against fair value</h3>
          <table className="tbl gm-trades"><thead><tr><th>Rd</th><th>CP</th><th>I</th><th className="r">Lots</th><th className="r">Price</th><th className="r">Fair then</th><th className="r">Edge</th><th className="r">Result</th><th>Verdict</th></tr></thead>
            <tbody>{m.trades.map((t) => <tr key={t.n}><td className="num">{t.round}{t.phase === "B" ? "⚡" : ""}</td><td>{t.bot}{t.informed ? <span className="neg" title="informed"> ◆</span> : null}</td><td className={t.me === "buy" ? "bid" : "offer"}>{t.me === "buy" ? "bought" : "sold"}</td>
              <td className="r">{t.qty}</td><td className="r">{fmtPrice(t.price, places)}</td><td className="r">{fmtPrice(t.fair, 2)}</td><td className="r"><Num v={t.edge} f={credits} /></td><td className="r"><Num v={t.result} f={credits} /></td><td className="dim">{t.verdict}</td></tr>)}</tbody></table>
          <h3>Your quotes against fair value</h3>
          <table className="tbl"><thead><tr><th>For rd</th><th className="r">Bid</th><th className="r">Offer</th><th className="r">Size</th><th className="r">Fair</th><th className="r">Mid − fair</th><th className="r">Half-spread</th><th className="r">Pos</th><th>Verdict</th></tr></thead>
            <tbody>{m.quotes.map((q, i) => <tr key={i}><td className="num">{q.round}</td><td className="r">{fmtPrice(q.bid, places)}</td><td className="r">{fmtPrice(q.offer, places)}</td><td className="r">{q.size}</td><td className="r">{fmtPrice(q.fair, 2)}</td>
              <td className="r num">{q.error_sd.toFixed(2)}σ</td><td className="r num">{q.half_spread_sd.toFixed(2)}σ <span className="dim">{q.spread}</span></td><td className="r">{q.position}</td><td className="dim">{q.verdict}</td></tr>)}</tbody></table>
          <p className="dim hint">σ = the uncertainty left in the question when you quoted. ◆ marks an informed counterparty. ⚡ marks a trade just after a shock. Shocks planned for this game: {d.shock_plan.length}.</p>
        </>
      ) : null}
    </Panel>
  );
}
