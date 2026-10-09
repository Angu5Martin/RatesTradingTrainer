import { Chip } from "../components/ui";
import { checkDraft, credits, draftFrom, fmtPrice, isDirty, lots, nudge, plural, STATUS_LABEL, tradeLine, type Draft } from "./derive";
import type { MarketView } from "./types";

interface Props {
  m: MarketView;
  draft: Draft | undefined;
  selected: boolean;
  busy: boolean;
  sizeMax: number;
  onSelect: () => void;
  onEdit: (patch: Partial<Draft>) => void;
  onSet: (d: Draft) => void;
  onDiscard: () => void;
  onSend: () => void;
  onPause: (paused: boolean) => void;
  onAck: () => void;
}

const TONE: Record<string, "neutral" | "accent" | "pos" | "neg" | "warn"> = { active: "accent", shocked: "warn", paused: "neutral", resolved: "pos", upcoming: "neutral" };

/** One market at the table: status, quote boxes, position and money, and the last trade. Everything shown is public; nothing here knows a fair value. */
export function MarketCard(p: Props) {
  const { m } = p;
  if (m.status === "upcoming") {
    return <li className="mk mk-upcoming" aria-label={`${m.id} not open yet`}><span className="mk-id">{m.id}</span><span className="dim">opens in {plural(m.opens_in ?? 0, "round")}</span><Chip>{STATUS_LABEL.upcoming}</Chip></li>;
  }
  if (m.status === "resolved") {
    const pnl = m.pnl ?? 0;
    return (
      <li className={`mk mk-resolved ${p.selected ? "sel" : ""}`} aria-label={`${m.id} resolved`}>
        <button className="mk-head" onClick={p.onSelect} aria-pressed={p.selected}><span className="mk-id">{m.id}</span><span className="mk-title">{m.title}</span><Chip tone="pos">RESOLVED</Chip></button>
        <div className="mk-result"><span className="dim">Settled</span> <strong className="num">{fmtPrice(m.settle ?? 0, m.decimals)}</strong> <span className="dim">{m.unit}</span>
          <span className="sep" /><span className="dim">Position at settlement</span> <span className="num">{lots(m.position_at_settlement ?? 0)}</span>
          <span className="sep" /><span className="dim">P&amp;L</span> <strong className={`num ${pnl > 0.5 ? "pos" : pnl < -0.5 ? "neg" : "zero"}`}>{credits(pnl)}</strong></div>
      </li>
    );
  }
  const d = p.draft ?? draftFrom(m);
  const dirty = isDirty(m, p.draft);
  const chk = checkDraft(m, d);
  const q = m.quote;
  const last = m.trades && m.trades.length ? m.trades[m.trades.length - 1] : null;
  const pos = m.position ?? 0;
  const pause = m.status === "paused";
  return (
    <li className={`mk mk-${m.status} ${p.selected ? "sel" : ""}`} aria-label={`${m.id} ${m.status}`}>
      <button className="mk-head" onClick={p.onSelect} aria-pressed={p.selected}>
        <span className="mk-id">{m.id}</span><span className="mk-title" title={m.title}>{m.title}</span>
        <Chip tone={TONE[m.status]}>{STATUS_LABEL[m.status]}</Chip>
      </button>
      <div className="mk-sub"><span className="dim">{m.kind === "world" ? m.category : m.category} · {m.unit || "value"}</span>
        <span className="mk-rem num" title="rounds until this market resolves">{m.remaining} {m.remaining === 1 ? "round" : "rounds"} left</span></div>
      {m.status === "shocked" ? <div className="mk-shock" role="status">A shock hit this market. Your quote is {q ? "unchanged" : "not posted"}: re-quote, or acknowledge to leave it.</div> : null}
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
          <button className="btn btn-sm" aria-label={`${m.id} widen`} disabled={p.busy} onClick={() => p.onSet(nudge(m, d, "width", 1))} title="widen the spread by a tick each side">◂▸ wider</button>
          <button className="btn btn-sm" aria-label={`${m.id} tighten`} disabled={p.busy} onClick={() => p.onSet(nudge(m, d, "width", -1))} title="tighten the spread by a tick each side">▸◂ tighter</button>
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
        <span className="dim mk-last">{last ? `R${last.round}: ${tradeLine(last, m.decimals)}` : "no trades yet"}</span>
      </div>
    </li>
  );
}
