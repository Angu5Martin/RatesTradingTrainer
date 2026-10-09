// The two compositions of the Live Desk. Each fills the whole space under the top bar; they are different arrangements, not one screen with more added.
//   DecisionLayout: market | action (client, ticket, commit) | book and risk        -- while a decision is being taken
//   ResultLayout:   what moved and what it made | what you did and how it was judged | position after and the P&L path   -- once it is committed
import type { Book, Conditions, Market, ObservationView, PendingState } from "../api/types";
import { PnlPath } from "../components/charts";
import { Kbd, Panel } from "../components/ui";
import { Blotter } from "./Blotter";
import { ConditionsPanel, RoomPanel, hasRoom } from "./ConditionsPanel";
import type { Draft } from "./draft";
import { focusOf, pnlPoints } from "./derive";
import type { Phase } from "./machine";
import { MarketPanel } from "./MarketPanel";
import { AssessmentBlock, CarryBlock, MoveBlock, OutcomeBlock, PnlBlock, WhatHappened, marketEvent, pnlEvent } from "./ResultPanel";
import { type Added, CurveRisk, type Exposures, PositionsPanel, RiskSummary, rowsFromEvents } from "./RiskPanel";
import type { TranscriptEntry } from "./store";
import { CheckpointTicket } from "./tickets/CheckpointTicket";
import { HedgeTicket } from "./tickets/HedgeTicket";
import { QuoteTicket } from "./tickets/QuoteTicket";
import { RfqTicket } from "./tickets/RfqTicket";
import { Num } from "../components/ui";
import { bp, eurM } from "../lib/format";

export interface DecisionProps {
  obs: ObservationView; draft: Draft; sessionId: string; phase: Phase; locked: boolean;
  market: Market | null; curves: { tenor: number; mid: number }[][]; book: Book | null; conditions: Conditions | null;
  banner: string | null; error: string | null; armedSummary: string | null; bookless: boolean; lastTrade: Added;
  onDraft: (d: Draft) => void; onArm: (pass?: boolean) => void; onDisarm: () => void; onCommit: () => void; onDismissBanner: () => void;
}

function ClientCard({ obs, conditions }: { obs: ObservationView; conditions: Conditions | null }) {
  const q = obs.inquiry!;
  const history = q.name ? conditions?.named_clients.find((c) => c.name === q.name) : undefined;
  return (
    <Panel title="CLIENT REQUEST" aside={<span className={`chip ${q.action === "pays" ? "chip-offer" : "chip-bid"}`}>{q.action === "pays" ? "YOU RECEIVE FIXED · OFFER" : "YOU PAY FIXED · BID"}</span>} className="client-card">
      <div className="client">
        <div className="client-name">{q.name ? <strong>{q.name}</strong> : null} <span className="dim">{q.short}</span></div>
        <div className="client-trade">
          <span className="client-side">{q.action === "pays" ? "PAYS" : "RECEIVES"} fixed</span>
          <span className="num client-size">{eurM(q.notional)} {q.tenor}Y</span>
          <span className="dim">own DV01</span> <Num v={q.dv01} />
        </div>
        {q.name ? (
          <div className="client-history dim">
            {history ? <>Seen today: {history.observations.map((o, i) => <span key={i}>{i ? "; " : ""}{o.side} fixed, then rates <span className={`num ${o.move_bp > 0.05 ? "pos" : o.move_bp < -0.05 ? "neg" : "zero"}`}>{bp(o.move_bp, 1)}</span></span>)}.</> : "Not seen before today."}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

/** The request a slope check refers to: the client has not been priced yet, and the check is graded after the price. */
function CheckpointRequest({ obs }: { obs: ObservationView }) {
  const i = obs.checkpoint?.inquiry;
  if (!i) return null;
  const slope = obs.risk_card.factors.find((f) => f.name === "slope");
  return (
    <Panel title="THE REQUEST" aside={<span className="dim">not priced yet</span>} className="client-card">
      <div className="client-trade">
        <span className="client-side">{i.action === "pays" ? "PAYS" : "RECEIVES"} fixed</span>
        <span className="num client-size">{eurM(i.notional)} {i.tenor}Y</span>
      </div>
      {slope?.loadings ? <p className="hint dim">Slope loading of each tenor (bp per unit of slope): {slope.loadings.map((l, k) => <span key={l.tenor}>{k ? " · " : ""}{l.tenor}Y <span className="num">{l.bp_per_unit >= 0 ? "+" : "−"}{Math.abs(l.bp_per_unit).toFixed(2)}</span></span>)}.</p> : null}
    </Panel>
  );
}

function focusTenorOf(o: ObservationView): number | null {
  return o.inquiry?.tenor ?? o.checkpoint?.inquiry?.tenor ?? (o.kind === "quote" ? o.book?.focus_tenor ?? null : null);
}

function ArmBar(p: { obs: ObservationView; phase: Phase; summary: string | null; onArm: () => void; onDisarm: () => void; onCommit: () => void }) {
  const hours = p.obs.next_step?.trading_hours;
  const idle = p.obs.kind === "checkpoint" ? "Answer from the book and the trade just done, then review."
    : hours != null ? `The market moves for about ${hours < 0.9 ? `${Math.round(hours * 60)} minutes` : `${Math.round(hours)} hour${hours >= 1.5 ? "s" : ""}`} after your decision.` : p.obs.prompt;
  return (
    <div className="armbar">
      <div className="arm-summary">{p.phase === "armed" && p.summary ? <><span className="dim">COMMIT</span> <strong>{p.summary}</strong></> : <span className="dim">{idle}</span>}</div>
      {p.phase === "awaiting" ? <button className="btn btn-primary" onClick={p.onArm}>Review <Kbd>⏎</Kbd></button> : null}
      {p.phase === "armed" ? <><button className="btn" onClick={p.onDisarm}>Edit <Kbd>Esc</Kbd></button><button className="btn btn-commit" onClick={p.onCommit} autoFocus>Commit <Kbd>⏎</Kbd></button></> : null}
      {p.phase === "submitting" ? <span className="dim">committing…</span> : null}
    </div>
  );
}

export function DecisionLayout(p: DecisionProps) {
  const { obs, draft } = p;
  const room = hasRoom(p.conditions);                                   // level 5: research view and named-client evidence sit beside the market
  const curve = !!p.book?.buckets;                                      // a book that is a curve (levels 3-5): bucket risk instead of the single-DV01 thermometer
  return (
    <div className="desk-main is-decision">
      <div className="col col-market">{p.market ? <MarketPanel market={p.market} curves={p.curves} focusTenor={focusTenorOf(obs)} /> : null}{room && p.conditions ? <RoomPanel c={p.conditions} highlight={obs.inquiry?.name} /> : null}</div>
      <div className="col col-action">
        {p.banner ? <div className="banner"><span>{p.banner}</span><button className="btn btn-ghost btn-sm" onClick={p.onDismissBanner}>dismiss</button></div> : null}
        {p.error ? <div className="alert" role="alert">{p.error}</div> : null}
        {obs.kind === "rfq" && obs.inquiry ? <ClientCard obs={obs} conditions={p.conditions} /> : null}
        {obs.kind === "checkpoint" ? <CheckpointRequest obs={obs} /> : null}
        {obs.kind === "overnight" && obs.overnight ? (
          <Panel title="THE CLOSE" aside={<span className="dim">what you carry overnight</span>} className="client-card">
            <div className="client-trade"><span className="client-side">CARRY, ROLL-DOWN AND FUNDING</span><Num v={obs.overnight.time_pnl} /></div>
            <p className="hint dim">For the book as it stands, on an unchanged curve. The next move is the overnight one.</p>
          </Panel>
        ) : null}
        {obs.kind === "quote" && obs.clients_today.length ? <Panel title="CLIENTS TODAY" className="clients-today"><p>{obs.clients_today.join(" · ")}</p></Panel> : null}
        {obs.kind === "quote" && draft.kind === "quote" && focusOf(obs) ? <QuoteTicket obs={obs} draft={draft} setDraft={p.onDraft} locked={p.locked} /> : null}
        {obs.kind === "rfq" && draft.kind === "rfq" && obs.inquiry && focusOf(obs) ? <RfqTicket obs={obs} draft={draft} setDraft={p.onDraft} locked={p.locked} onPass={() => p.onArm(true)} /> : null}
        {obs.kind === "checkpoint" && draft.kind === "checkpoint" ? <CheckpointTicket obs={obs} draft={draft} setDraft={p.onDraft} locked={p.locked} /> : null}
        {draft.kind === "hedge" ? <HedgeTicket obs={obs} sessionId={p.sessionId} draft={draft} setDraft={p.onDraft} locked={p.locked} /> : null}
        {obs.last_inquiry ? <p className="dim hint last-inq">Last inquiry: {obs.last_inquiry.short} wanted to {obs.last_inquiry.action === "pays" ? "pay" : "receive"} fixed on {eurM(obs.last_inquiry.notional)} {obs.last_inquiry.tenor}Y; {obs.last_inquiry.outcome}.</p> : null}
        <ArmBar obs={obs} phase={p.phase} summary={p.armedSummary} onArm={() => p.onArm()} onDisarm={p.onDisarm} onCommit={p.onCommit} />
      </div>
      <div className="col col-book">
        {p.book && !p.bookless ? (curve ? <CurveRisk book={p.book} /> : <RiskSummary book={p.book} />) : null}
        {p.book ? <PositionsPanel book={p.book} added={p.bookless ? p.lastTrade : undefined} grow={p.bookless} shrink={curve && !p.bookless} /> : null}
        {p.conditions ? <ConditionsPanel c={p.conditions} shrink={curve} omitRoom={room} /> : null}
      </div>
    </div>
  );
}

export interface ResultProps {
  pending: PendingState; book: Book | null; market: Market | null; curves: { tenor: number; mid: number }[][]; transcript: TranscriptEntry[];
  dv01After: number | null; after: Exposures | null; pnlTotal: number; busy: boolean; onContinue: () => void;
}

export function ResultLayout(p: ResultProps) {
  const r = p.pending.result;
  const market = marketEvent(r), pnl = pnlEvent(r);
  const added = rowsFromEvents(r.events, p.pending.observation.episode.round);
  const points = pnlPoints(p.transcript);
  const o = p.pending.observation;
  const ladder = o.market?.mode === "ladder";
  const curve = !!p.book?.buckets;
  return (
    <div className="desk-main is-result">
      <div className={`col col-move ${market ? "" : "dimmed"}`}>
        {market ? <><MoveBlock market={market} ladder={ladder} /><CarryBlock r={r} /><PnlBlock market={market} pnl={pnl} />{points.length ? <Panel title="P&L THROUGH THE EPISODE" className="grow pnl-path"><PnlPath points={points} /></Panel> : null}</> : (
          <><OutcomeBlock r={r} />{p.market ? <MarketPanel market={p.market} curves={p.curves} /> : null}</>
        )}
      </div>
      <div className="col col-analysis">
        <WhatHappened pending={p.pending} />
        {r.assessment ? <AssessmentBlock a={r.assessment} /> : null}
        <Blotter transcript={p.transcript} />
        <div className="continue-row">
          <button className="btn btn-primary" onClick={p.onContinue} disabled={p.busy} autoFocus>{r.done ? "Open the debrief" : "Continue"} <Kbd>⏎</Kbd></button>
          <span className="dim">{r.done ? "The episode is over. The debrief compares your decisions with other policies on the same path." : "The next screen shows the market after this move."}</span>
        </div>
      </div>
      <div className="col col-book">
        {p.book ? (curve ? <CurveRisk book={p.book} asAt after={p.after} /> : <RiskSummary book={p.book} asAt dv01After={p.dv01After} />) : null}
        {p.book ? <PositionsPanel book={p.book} added={added} asAt shrink={curve} /> : null}
      </div>
    </div>
  );
}
