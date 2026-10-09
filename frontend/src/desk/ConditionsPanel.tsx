import { Fragment } from "react";
import type { Conditions, Research } from "../api/types";
import { Chip, Panel } from "../components/ui";
import { bp } from "../lib/format";

/** The research view as the desk gives it: its text and stated reliability, and what is left of it (the engine's own figures; nothing here says whether it is right). */
export function ResearchStrip({ r }: { r: Research }) {
  const way = r.remaining_bp > 0 ? "rise" : "fall";
  return (
    <div className="research" aria-label="research view">
      <div className="sub-h"><span>RESEARCH VIEW</span><Chip title="stated reliability: the share of this desk's calls that carried real information">{Math.round(r.reliability * 100)}% reliable</Chip></div>
      <p>{r.text}</p>
      <p className="dim">What is left of the view: about {Math.abs(r.remaining_bp).toFixed(1)}bp {way} over the {r.steps_left} step{r.steps_left === 1 ? "" : "s"} still to come ({Math.abs(r.per_step_bp).toFixed(2)}bp a step); at {Math.round(r.reliability * 100)}% reliability expect about {Math.abs(r.expected_per_step_bp).toFixed(2)}bp of it next step.</p>
    </div>
  );
}

/** What each named client has done today and what the market did next (the level of rates over the step after their request). Evidence only: no verdict on any client. */
export function EvidenceTable({ clients, highlight }: { clients: Conditions["named_clients"]; highlight?: string | null }) {
  if (!clients.length) return null;
  return (
    <div className="evidence" aria-label="named clients today">
      <div className="sub-h"><span>NAMED CLIENTS TODAY</span><span className="dim">what the market did next</span></div>
      <table className="tbl">
        <tbody>
          {clients.map((c) => (
            <tr key={c.name} className={c.name === highlight ? "row-sel" : ""}>
              <td><strong>{c.name}</strong><div className="dim">{c.description}</div></td>
              <td>{c.observations.map((o, i) => <div key={i}>{o.side} fixed, then rates <span className={`num ${o.move_bp > 0.05 ? "pos" : o.move_bp < -0.05 ? "neg" : "zero"}`}>{bp(o.move_bp, 1)}</span></div>)}</td>
            </tr>))}
        </tbody>
      </table>
    </div>
  );
}

/** Level 5's "read the room": the research view and the named clients' record today, kept beside the market because they are read together with it. */
export function RoomPanel({ c, highlight }: { c: Conditions; highlight?: string | null }) {
  return (
    <Panel title="READ THE ROOM" aside={<span className="dim">evidence, not verdicts</span>} className="room shrink">
      {c.research ? <ResearchStrip r={c.research} /> : null}
      <EvidenceTable clients={c.named_clients} highlight={highlight} />
      {!c.named_clients.length ? <p className="dim hint">No named client has traded yet today.</p> : null}
    </Panel>
  );
}

export function hasRoom(c: Conditions | null): boolean { return !!c && (!!c.research || c.named_clients.length > 0); }

export function ConditionsPanel({ c, shrink, highlight, omitRoom }: { c: Conditions; shrink?: boolean; highlight?: string | null; omitRoom?: boolean }) {
  const sc = c.swap_cost;
  return (
    <Panel title="CONDITIONS" className={`conditions ${shrink ? "shrink" : ""}`}>
      <dl className="dl">
        <dt>Volatility</dt><dd>{c.volatility}</dd>
        <dt>Liquidity</dt><dd>{c.liquidity}</dd>
        <dt>Flow</dt><dd>{c.flow}</dd>
        {sc ? <><dt>Swap costs</dt><dd>about {sc.multiplier.toFixed(1)}× their usual spread{sc.depth_dv01 ? `, and size moves the market: a swap hedge of D DV01 costs (1 + D / ${Math.round(sc.depth_dv01 / 1e3)}k) times that` : ""}. Futures still trade tight.</dd></> : null}
        {c.desk_expectation ? (<><dt>Desk</dt><dd>{c.desk_expectation}</dd></>) : null}
        {c.calendar ? <><dt>Calendar</dt><dd><Chip tone="warn">data release</Chip> lands in the next step: expect moves about {c.calendar.vol_mult.toFixed(0)}× normal.</dd></> : null}
        {c.extra_lines.map((l, i) => <Fragment key={i}><dt>Note</dt><dd>{l}</dd></Fragment>)}
      </dl>
      {omitRoom ? null : <>{c.research ? <ResearchStrip r={c.research} /> : null}<EvidenceTable clients={c.named_clients} highlight={highlight} /></>}
    </Panel>
  );
}
