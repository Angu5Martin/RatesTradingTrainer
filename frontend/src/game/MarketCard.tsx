import { Chip } from "../components/ui";
import { checkDraft, credits, draftFrom, fmtPrice, isDirty, lots, nudge, plural, STATUS_LABEL, tradeLine, type Draft } from "./derive";
import type { MarketView } from "./types";

/** How much room each card gets, from the number of markets live at the table: roomy (1-2), standard (3-4), dense (5+). See Table. */
export type Density = "roomy" | "standard" | "dense";

interface Props {
  m: MarketView;
  draft: Draft | undefined;
  selected: boolean;
  busy: boolean;
  sizeMax: number;
  density: Density;
  onSelect: () => void;
  onEdit: (patch: Partial<Draft>) => void;
  onSet: (d: Draft) => void;
  onDiscard: () => void;
  onSend: () => void;
  onPause: (paused: boolean) => void;
  onAck: () => void;
}

const TONE: Record<string, "neutral" | "accent" | "pos" | "neg" | "warn"> = { active: "accent", shocked: "warn", paused: "neutral", resolved: "pos", upcoming: "neutral" };
const CAT_TONE = { experiment: "warn", information: "accent", resolution: "neg" } as const;

/** The lines of the rules in force that matter for pricing at a glance: for a probability market all of them (what is still to roll, with which faces, and what
 *  is already known); for a world market the confirmed clues, plus the settlement definition when there is room. */
export function cardInfo(m: MarketView, density: Density): string[] {
  const rules = m.rules ?? [];
  if (m.kind === "world") return density === "roomy" ? rules : rules.slice(1);
  return rules;
}

/** A settled market, kept small: what it settled at, the position held and the P&L. Selecting it shows the full detail. */
export function SettledRow({ m, selected, onSelect }: { m: MarketView; selected: boolean; onSelect: () => void }) {
  const pnl = m.pnl ?? 0;
  return (
    <li className={`mk mk-resolved ${selected ? "sel" : ""}`} aria-label={`${m.id} resolved`}>
      <button className="mk-head" onClick={onSelect} aria-pressed={selected}><span className="mk-id">{m.id}</span><span className="mk-title" title={m.title}>{m.title}</span></button>
      <div className="mk-result"><span className="dim">Settled</span> <strong className="num">{fmtPrice(m.settle ?? 0, m.decimals)}</strong> <span className="dim">{m.unit}</span>
        <span className="sep" /><span className="dim">Position</span> <span className="num">{lots(m.position_at_settlement ?? 0)}</span>
        <span className="sep" /><span className="dim">P&amp;L</span> <strong className={`num ${pnl > 0.5 ? "pos" : pnl < -0.5 ? "neg" : "zero"}`}>{credits(pnl)}</strong></div>
    </li>
  );
}

/** One live market at the table: status, what is in force, quote boxes, position and money, and the last trades. Everything shown is public; nothing here
 *  knows a fair value. The card's content grows with the room it has (density) but its controls are the same at every size. */
export function MarketCard(p: Props) {
  const { m, density } = p;
  if (m.status === "upcoming") {
    return <li className="mk mk-upcoming" aria-label={`${m.id} not open yet`}><span className="mk-id">{m.id}</span><span className="dim">opens in {plural(m.opens_in ?? 0, "round")}</span><Chip>{STATUS_LABEL.upcoming}</Chip></li>;
  }
  if (m.status === "resolved") return <SettledRow m={m} selected={p.selected} onSelect={p.onSelect} />;
  const d = p.draft ?? draftFrom(m);
  const dirty = isDirty(m, p.draft);
  const chk = checkDraft(m, d);
  const q = m.quote;
  const trades = m.trades ?? [];
  const last = trades.length ? trades[trades.length - 1] : null;
  const pos = m.position ?? 0;
  const pause = m.status === "paused";
  const info = cardInfo(m, density);
  const shock = m.status === "shocked" ? m.notes[m.notes.length - 1] : undefined;
  const roomy = density === "roomy";
  const recent = (n: number) => (
    <div className="mk-recent" aria-label={`${m.id} recent trades`}>
      <span className="mk-recent-h">Recent trades <span className="dim">{trades.length}</span></span>
      {trades.length ? <ul>{trades.slice(-n).reverse().map((t) => <li key={t.n} className={t.phase === "B" ? "ev-fast" : ""}><span className="dim num">R{t.round}{t.phase === "B" ? "⚡" : ""}</span> {tradeLine(t, m.decimals)}</li>)}</ul>
        : <p className="dim">no trades yet</p>}
    </div>
  );
  const infoList = info.length ? <ul className="mk-info" aria-label={`${m.id} rules in force`}>{info.map((r, i) => <li key={i} title={r}>{r}</li>)}</ul> : null;
  return (
    <li className={`mk mk-${m.status} ${p.selected ? "sel" : ""}`} aria-label={`${m.id} ${m.status}`}>
      <button className="mk-head" onClick={p.onSelect} aria-pressed={p.selected}>
        <span className="mk-id">{m.id}</span><span className="mk-title" title={m.question ?? m.title}>{m.title}</span>
        <Chip tone={TONE[m.status]}>{STATUS_LABEL[m.status]}</Chip>
      </button>
      <div className="mk-sub"><span className="dim mk-cat" title={`${m.category} · ${m.unit || "value"}${m.possible ? ` · possible ${m.possible[0]}–${m.possible[1]}` : ""}`}>{m.category} · {m.unit || "value"}{m.possible ? <> · possible <span className="num">{m.possible[0]}–{m.possible[1]}</span></> : null}</span>
        <span className="mk-rem num" title="rounds until this market resolves">{m.remaining} {m.remaining === 1 ? "round" : "rounds"} left</span></div>
      {shock ? (
        <div className="mk-shock" role="status">
          <span><Chip tone={CAT_TONE[shock.category]}>{shock.headline}</Chip> <span className="dim">R{shock.round}</span></span>
          <span className="mk-shock-t" title={shock.text}>{shock.text}</span>
          <span className="mk-shock-h">{q ? "Quote unchanged: re-quote, or Acknowledge to keep it." : "No quote posted yet."}</span>
        </div>
      ) : null}
      {!roomy ? infoList : null}
      <div className="mk-body">
        <div className="mk-main">
          <form className="mk-quote" onSubmit={(e) => { e.preventDefault(); p.onSend(); }}>
            <label className="mk-f bid"><span>Bid</span><input className="in num" aria-label={`${m.id} bid`} inputMode="decimal" value={d.bid} placeholder="–" onChange={(e) => p.onEdit({ bid: e.target.value })} disabled={p.busy} /></label>
            <label className="mk-f offer"><span>Offer</span><input className="in num" aria-label={`${m.id} offer`} inputMode="decimal" value={d.offer} placeholder="–" onChange={(e) => p.onEdit({ offer: e.target.value })} disabled={p.busy} /></label>
            <label className="mk-f size"><span>Size</span>
              <select className="in" aria-label={`${m.id} size`} value={d.size} onChange={(e) => p.onEdit({ size: Number(e.target.value) })} disabled={p.busy}>
                {Array.from({ length: p.sizeMax }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
            <button type="submit" className={`btn ${dirty ? "btn-primary" : ""}`} disabled={p.busy || !dirty || !chk.ok} title={!dirty ? "no change" : chk.ok ? "post this market" : chk.why}>{q ? "Re-quote" : "Quote"}</button>
          </form>
          <div className="mk-tools">
            <span className="mk-nudge" role="group" aria-label={`${m.id} adjust`}>
              <button className="btn btn-sm" aria-label={`${m.id} lower both`} disabled={p.busy} onClick={() => p.onSet(nudge(m, d, "shift", -1))} title="move the whole market down one tick (skew to sell)">◀</button>
              <button className="btn btn-sm" aria-label={`${m.id} raise both`} disabled={p.busy} onClick={() => p.onSet(nudge(m, d, "shift", 1))} title="move the whole market up one tick (skew to buy)">▶</button>
              <button className="btn btn-sm" aria-label={`${m.id} widen`} disabled={p.busy} onClick={() => p.onSet(nudge(m, d, "width", 1))} title="widen the spread by a tick each side">◂▸<span className="mk-nl"> wider</span></button>
              <button className="btn btn-sm" aria-label={`${m.id} tighten`} disabled={p.busy} onClick={() => p.onSet(nudge(m, d, "width", -1))} title="tighten the spread by a tick each side">▸◂<span className="mk-nl"> tighter</span></button>
            </span>
            <span className="mk-acts">
              {dirty ? <button className="btn btn-sm btn-ghost" onClick={p.onDiscard} aria-label={`${m.id} revert`}>Revert</button> : null}
              {m.status === "shocked" ? <button className="btn btn-sm" onClick={p.onAck} disabled={p.busy}>Acknowledge</button> : null}
              <button className="btn btn-sm" onClick={() => p.onPause(!pause)} disabled={p.busy || (!q && !pause)}>{pause ? "Resume" : "Pause"}</button>
            </span>
          </div>
          {dirty && !chk.ok ? <div className="mk-warn">{chk.why}</div> : null}
          <dl className="mk-stats">
            <div><dt>Position</dt><dd className={`num ${pos > 0 ? "long" : pos < 0 ? "short" : ""}`}>{lots(pos)} <span className="dim">/ ±{m.limit}</span></dd></div>
            <div><dt>Avg</dt><dd className="num">{m.avg_price == null ? "–" : fmtPrice(m.avg_price, m.decimals)}</dd></div>
            <div><dt>Cash</dt><dd className="num">{credits(m.cash ?? 0)}</dd></div>
            <div><dt>Open P&amp;L</dt><dd className={`num ${(m.open_pnl ?? 0) > 0.5 ? "pos" : (m.open_pnl ?? 0) < -0.5 ? "neg" : "zero"}`}>{credits(m.open_pnl ?? 0)}</dd></div>
          </dl>
          <div className="mk-foot">
            {m.closed?.bid ? <Chip tone="warn" title="at your position limit: nobody can sell to you">BID CLOSED</Chip> : null}
            {m.closed?.offer ? <Chip tone="warn" title="at your position limit: nobody can buy from you">OFFER CLOSED</Chip> : null}
            {q?.stale ? <Chip tone="warn" title="this quote was set before the latest shock">STALE</Chip> : null}
            {density === "dense" ? <span className="dim mk-last">{last ? `R${last.round}: ${tradeLine(last, m.decimals)}` : "no trades yet"}</span> : null}
          </div>
          {density === "standard" ? recent(3) : null}
        </div>
        {roomy ? (
          <div className="mk-more">
            {m.kind === "world" && m.question && m.question !== m.title ? <p className="mk-q">{m.question}</p> : null}
            {m.kind === "probability" && m.question ? <p className="mk-q">{m.question}</p> : null}
            {infoList}
            {recent(4)}
          </div>
        ) : null}
      </div>
    </li>
  );
}
