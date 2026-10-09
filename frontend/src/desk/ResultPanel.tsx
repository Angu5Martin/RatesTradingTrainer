import type { AssessmentView, PendingState, ResultEvent, StepResultView } from "../api/types";
import { SignedBars } from "../components/charts";
import { Num, Panel, RatingChip } from "../components/ui";
import { bp, eur, eurM, num, pct } from "../lib/format";
import { describeDecision } from "../lib/ticket";

const FACTOR_NAME: Record<string, string> = { level: "Level", slope: "Slope", curvature: "Curvature", swap_spread: "Swap spread", fut_basis: "Futures basis" };

export function EventLine({ e }: { e: ResultEvent }) {
  switch (e.type) {
    case "client_arrives":
      return <li>{e.name ? <strong>{e.name}</strong> : null} <span className="dim">{e.short}</span> wants to <strong>{e.action === "pays" ? "pay" : "receive"}</strong> fixed on {eurM(e.notional)}. Your {e.action === "pays" ? "offer" : "bid"} <span className="num">{pct(e.your_rate)}</span> vs street <span className="num">{pct(e.street_rate)}</span>.</li>;
    case "passed": return <li>You passed. The client dealt elsewhere.</li>;
    case "fill": return e.filled
      ? <li className="ev-fill"><strong>DONE</strong> — client {e.action === "pays" ? "pays" : "receives"} fixed {eurM(e.notional)} {e.tenor}Y at <span className="num">{pct(e.rate)}</span> with you <span className="dim">(chance {num(e.p_win * 100)}%)</span>. You {e.dealer_side} fixed. Edge against mid <Num v={e.edge} />.</li>
      : <li>The client dealt elsewhere <span className="dim">(your chance of winning it was {num(e.p_win * 100)}%)</span>.</li>;
    case "flat_book": return <li className="dim">Your book is flat: nothing to hedge.</li>;
    case "hedge_trade":
      if (e.kind === "swap") return <li>Hedged: you <strong>{e.side}</strong> fixed {eurM(e.notional)} {e.tenor}Y at <span className="num">{pct(e.rate)}</span> · cost <Num v={e.cost} />.</li>;
      return <li>Done: you {(e.kind === "future" ? e.contracts : e.face) > 0 ? "bought" : "sold"} {e.kind === "future" ? `${num(Math.abs(e.contracts))} ${e.code}` : `${eurM(Math.abs(e.face))} ${e.code}`} · cost <Num v={e.cost} />.</li>;
    case "skipped_trade": return <li className="dim">Not traded: {e.description} is too small to matter (under {e.threshold_pct}% of your DV01 limit).</li>;
    case "no_trade": return <li>No trade: you keep the book as it is.</li>;
    case "checkpoint_recorded": return <li>Answer recorded: it is checked after you price the request.</li>;
    case "checkpoint_grade": return <li className={e.correct ? "pos" : "neg"}>{e.label ? `${e.label}: ` : ""}{e.correct ? "✓" : "✗"} {e.feedback}{e.correct ? "" : ` The answer is ${e.expected}.`}</li>;
    case "overnight": return <li>Overnight on an unchanged curve: {e.causes.map((c, i) => <span key={i}>{i ? " · " : ""}{c.name.replace("time: ", "")} <Num v={c.amount} /></span>)}.</li>;
    default: return null;
  }
}

type MarketEvent = Extract<ResultEvent, { type: "market" }>;
type PnlEvent = Extract<ResultEvent, { type: "round_pnl" }>;
export const marketEvent = (r: StepResultView): MarketEvent | undefined => r.events.find((e): e is MarketEvent => e.type === "market");
export const pnlEvent = (r: StepResultView): PnlEvent | undefined => r.events.find((e): e is PnlEvent => e.type === "round_pnl");

/** What the decision did: the fill or the trades, in order. */
export function WhatHappened({ pending }: { pending: PendingState }) {
  const happened = pending.result.events.filter((e) => e.type !== "market" && e.type !== "round_pnl" && e.type !== "overnight");     // the overnight carry has its own block beside the move
  return (
    <Panel title="DECISION SUBMITTED" aside={<span className="dim">{describeDecision(pending.decision)}</span>} className="result">
      <ul className="events">{happened.map((e, i) => <EventLine key={i} e={e} />)}</ul>
    </Panel>
  );
}

/** The market move: the move in the traded tenor as the headline, then each factor's move. On a ladder (levels 3-5) the par change at each tenor leads, so
 *  parallel, steepening, flattening and a twist of the belly read straight off the bars, and the factor moves follow on one line. */
export function MoveBlock({ market, ladder }: { market: MarketEvent | undefined; ladder?: boolean }) {
  if (!market) return <Panel title="MARKET MOVE" className="result move"><p className="dim">No market move in this step.</p></Panel>;
  const unit = (n: string) => (n === "fut_basis" ? "tick" : "bp");
  return (
    <Panel title="MARKET MOVE" aside={<span className="dim">{market.release ? "the data release" : "the next step"}</span>} className="result move">
      <div className="hero"><span className="hero-v"><Num v={market.move_bp} f={(x) => bp(x, 1)} eps={0.05} /></span><span className="hero-k dim">{market.focus_tenor}Y swap rate</span></div>
      {ladder && market.tenor_moves?.length ? (
        <>
          <div className="sub-h"><span>PAR CHANGE BY TENOR</span><span className="dim">bp</span></div>
          <SignedBars labelWidth={34} minScale={0.5} eps={0.05} f={(x) => bp(x, 2)} rows={market.tenor_moves.map((t) => ({ label: `${t.tenor}Y`, value: t.bp }))} />
          <p className="factor-line dim">{market.factor_moves.map((m, i) => <span key={m.name}>{i ? " · " : ""}{(FACTOR_NAME[m.name] ?? m.name).toLowerCase()} <span className="num">{m.value >= 0 ? "+" : "−"}{Math.abs(m.value).toFixed(1)}{unit(m.name)}</span></span>)}</p>
        </>
      ) : (
        <table className="tbl">
          <thead><tr><th>Factor</th><th className="r">Move</th></tr></thead>
          <tbody>{market.factor_moves.map((m) => (
            <tr key={m.name}><td>{FACTOR_NAME[m.name] ?? m.name}</td><td className="r num">{m.value >= 0 ? "+" : "−"}{Math.abs(m.value).toFixed(1)}{m.name === "fut_basis" ? " tick" : "bp"}</td></tr>))}</tbody>
        </table>
      )}
    </Panel>
  );
}

/** Overnight, on an unchanged curve: what time alone did to the book, by cause (swap carry and roll-down, futures convergence, bond accrual, funding). */
export function CarryBlock({ r }: { r: StepResultView }) {
  const ev = r.events.find((e): e is Extract<ResultEvent, { type: "overnight" }> => e.type === "overnight");
  if (!ev) return null;
  const total = ev.causes.reduce((a, c) => a + c.amount, 0);
  return (
    <Panel title="OVERNIGHT: CARRY, ROLL AND FUNDING" aside={<span className="dim">curve unchanged</span>} className="result carry">
      <SignedBars labelWidth={118} rows={ev.causes.map((c) => ({ label: c.name.replace("time: ", "").replace("funding (repo)", "funding"), value: c.amount }))} />
      <div className="kv"><span className="dim">time alone</span><Num v={total} /></div>
    </Panel>
  );
}

/** For steps with no market move yet (a price, a quote, a calculation check): what the step itself produced, as the headline. */
export function OutcomeBlock({ r }: { r: StepResultView }) {
  const fill = r.events.find((e): e is Extract<ResultEvent, { type: "fill" }> => e.type === "fill");
  const passed = r.events.some((e) => e.type === "passed");
  const grade = r.events.find((e): e is Extract<ResultEvent, { type: "checkpoint_grade" }> => e.type === "checkpoint_grade");
  const hedged = r.events.filter((e) => e.type === "hedge_trade" || e.type === "no_trade").length > 0;
  return (
    <Panel title={grade ? "CALCULATION CHECK" : "OUTCOME"} className="result move">
      {grade ? (
        <div className="hero"><span className={`hero-v ${grade.correct ? "pos" : "neg"}`}>{grade.correct ? "✓ correct" : "✗ missed"}</span>{grade.correct ? null : <span className="hero-k dim">the answer is {grade.expected}</span>}</div>
      ) : fill && fill.filled ? (
        <>
          <div className="hero"><span className="hero-v pos">DONE</span><span className="hero-k dim">{eurM(fill.notional)} {fill.tenor}Y at {pct(fill.rate)}</span></div>
          <div className="kv"><span className="dim">edge against mid</span><Num v={fill.edge} /></div>
          <div className="kv"><span className="dim">chance of winning it</span><span className="num">{num(fill.p_win * 100)}%</span></div>
        </>
      ) : fill ? (
        <>
          <div className="hero"><span className="hero-v">dealt elsewhere</span><span className="hero-k dim">chance of winning it was {num(fill.p_win * 100)}%</span></div>
        </>
      ) : passed ? <div className="hero"><span className="hero-v">passed</span><span className="hero-k dim">the client dealt elsewhere</span></div>
      : hedged ? <div className="hero"><span className="hero-v">hedge placed</span></div> : <p className="dim">Recorded.</p>}
    </Panel>
  );
}

/** Where this step's P&L came from, by factor, and the round and running totals. */
export function PnlBlock({ market, pnl }: { market: MarketEvent | undefined; pnl: PnlEvent | undefined }) {
  return (
    <Panel title="P&L ATTRIBUTION" aside={<span className="dim">first order, by factor</span>} className="result pnl-block">
      <div className="pnl-hero">
        <div><span className="hero-k dim">ROUND P&amp;L</span><span className="hero-v">{pnl ? <Num v={pnl.round_pnl} /> : "–"}</span></div>
        <div><span className="hero-k dim">TOTAL</span><span className="hero-v">{pnl ? <Num v={pnl.total_pnl} /> : "–"}</span></div>
      </div>
      {market ? (
        <>
          <SignedBars labelWidth={104} rows={market.first_order.map((f) => ({ label: FACTOR_NAME[f.name] ?? f.name, value: f.pnl }))} />
          <div className="kv"><span className="dim">full revaluation <span title="first-order P&L plus convexity and cross terms">ⓘ</span></span><span><Num v={market.full_revaluation} /> <span className="dim">· convexity/cross {eur(market.convexity_cross)}</span></span></div>
        </>
      ) : null}
    </Panel>
  );
}

export function AssessmentBlock({ a }: { a: AssessmentView }) {
  const m = a.metrics;
  const drivers = (m as { decomposition?: { inventory: number; information: number; view: number } }).decomposition ?? null;
  return (
    <Panel title="ASSESSMENT" aside={<span className="dim">judged on what you knew when you committed</span>} className="result assessment">
      <div className="assess-head"><RatingChip rating={a.rating} />
        {typeof m.dv01_before === "number" && typeof m.dv01_after === "number" ? <span className="dim">DV01 <Num v={m.dv01_before} /> → <Num v={m.dv01_after} />{typeof m.cost === "number" ? <> · cost {eur(m.cost)}</> : null}</span> : null}
      </div>
      <ul className="reasons">{a.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
      {drivers ? (
        <div className="drivers">
          <div className="sub-h"><span>WHAT MOVES THE PRICE</span><span className="dim">reference charge, bp</span></div>
          <SignedBars labelWidth={92} minScale={0.2} eps={0.005} f={(x) => bp(x, 2)} rows={[{ label: "inventory", value: drivers.inventory }, { label: "information", value: drivers.information }, { label: "view", value: drivers.view }]} />
        </div>
      ) : null}
      {a.table.length ? (
        <details open={a.table.length <= 8}>
          <summary>Benchmark alternatives <span className="dim">(revealed now that you have committed)</span></summary>
          <table className="tbl">
            <thead><tr><th>Alternative</th><th className="r">E[P&amp;L]</th><th className="r">Risk (σ)</th><th>View</th></tr></thead>
            <tbody>{a.table.map((t) => (<tr key={t.label}><td>{t.label}</td><td className="r"><Num v={t.expected} /></td><td className="r num">{eur(t.sigma, false)}</td><td><RatingChip rating={t.rating} /></td></tr>))}</tbody>
          </table>
          <p className="hint dim">E = expected P&amp;L to the next mark (hedge cost now, the cost of exiting what you keep later net of expected client flow, expected drift); σ = risk over the next step.</p>
        </details>
      ) : null}
    </Panel>
  );
}
