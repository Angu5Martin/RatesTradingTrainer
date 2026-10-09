import type { DebriefView, Rating, ResultEvent } from "../api/types";
import { Distribution, PnlPath, SignedBars } from "../components/charts";
import { Num, Panel, RatingChip } from "../components/ui";
import { eur, eurM, num } from "../lib/format";
import { describeDecision } from "../lib/ticket";
import { pnlPoints } from "./derive";
import { EventLine } from "./ResultPanel";
import { useDesk } from "./store";

const ORDER: Rating[] = ["sound", "defensible", "poor", "error"];
const LETTER: Record<Rating, string> = { sound: "S", defensible: "D", poor: "P", error: "E" };
export const RatingStrip = ({ ratings }: { ratings: Rating[] }) => <span className="strip">{ratings.map((r, i) => <span key={i} className={`rs rs-${r}`} title={r}>{LETTER[r]}</span>)}</span>;

export function verdictLine(d: DebriefView): string | null {
  const bad = d.decisions.some((x) => x.rating === "poor" || x.rating === "error");
  const total = d.outcome.total;
  if (!bad && total < 0 && d.luck.luck < 0) return "Sound decisions, an unlucky result: the loss is mostly what the market and the fills did, not what you decided.";
  if (bad && total > 0 && d.luck.luck > 0) return "At least one poor decision, and a result that came out ahead of expectation: do not read the profit as skill.";
  if (!bad && total > 0 && d.luck.luck > 0) return "Sound decisions, and the result also ran ahead of expectation: some of the profit is luck.";
  if (bad && total < 0) return "A poor decision and a loss: here the result and the decision point the same way.";
  return null;
}

export function Debrief({ onNewEpisode, onExit }: { onNewEpisode: () => void; onExit: () => void }) {
  const { transcript, debrief: d, debriefFull: full, loadingFull, episode } = useDesk();
  if (!d) return <div className="center dim">Preparing the debrief…</div>;
  const counts = Object.fromEntries(ORDER.map((r) => [r, d.decisions.filter((x) => x.rating === r).length])) as Record<Rating, number>;
  const assessed = transcript.filter((t) => t.result.assessment);
  const path = pnlPoints(transcript);
  const cf = full?.counterfactuals;
  const paths = full?.market_paths ?? null;
  const isLevel5 = d.evidence_vs_truth !== null && d.view_truth !== null;     // the level whose debrief carries a research view
  const verdict = verdictLine(d);
  return (
    <div className="debrief">
      <header className="debrief-h">
        <div><span className="tb-level">L{episode?.level}</span> <strong>DEBRIEF</strong> <span className="dim">{episode?.title}</span></div>
        <div className="row-gap"><button className="btn" onClick={onNewEpisode}>‹ Back to Levels</button><button className="btn btn-ghost" onClick={onExit}>Back to shell</button></div>
      </header>

      <div className="strip4">
        <div className="card"><div className="card-k">DECISION QUALITY <span className="dim">ex ante</span></div>
          <div className="card-v">{ORDER.map((r) => counts[r] ? <span key={r} className="count"><span className={`rs rs-${r}`}>{LETTER[r]}</span> {counts[r]} <span className="dim count-l">{r}</span></span> : null)}</div>
          <div className="card-s dim">{d.decisions.length} decisions judged on what you knew{d.calculation_checks.length ? ` · checks ${d.calculation_checks.filter((c) => c.correct).length}/${d.calculation_checks.length}` : ""}</div></div>
        <div className="card"><div className="card-k">REALISED OUTCOME <span className="dim">this path</span></div>
          <div className="card-v big"><Num v={d.outcome.total} /></div><div className="card-s dim">risk left: DV01 <Num v={d.outcome.risk_left.dv01} /></div></div>
        <div className="card"><div className="card-k">LUCK <span className="dim">realised − expected</span></div>
          <div className="card-v big"><Num v={d.luck.luck} /></div>
          <div className="card-s dim">{d.luck.label} <Num v={d.luck.expected_pnl} /></div>
          {d.luck.sigma_units != null ? <div className="card-s dim">{d.luck.sigma_units >= 0 ? "+" : "−"}{Math.abs(d.luck.sigma_units).toFixed(1)}σ of the uncertainty your decisions left</div> : null}</div>
        <div className="card"><div className="card-k">SAME PATH <span className="dim">other policies</span></div>
          {cf ? <><div className="card-v big">{cf.policies.filter((p) => p.pnl > cf.you).length} <span className="dim">of {cf.policies.length} beat you</span></div>
            <div className="card-s dim">best <Num v={Math.max(...cf.policies.map((p) => p.pnl))} /> · worst <Num v={Math.min(...cf.policies.map((p) => p.pnl))} /></div></>
            : <div className="skeleton" aria-busy>{loadingFull ? "running the alternatives on your path…" : ""}</div>}</div>
      </div>
      {verdict ? <p className="verdict">{verdict}</p> : null}

      <div className="debrief-grid">
        <div className="debrief-col">
          <Panel title="ROUND BY ROUND" aside={<span className="dim">decision → risk → assessment → outcome</span>}>
            {transcript.map((t, i) => {
              const a = t.result.assessment;
              const idx = a ? assessed.indexOf(t) : -1;
              const reasons = idx >= 0 ? d.decisions[idx]?.reasons ?? a!.reasons : [];
              const pnl = t.result.events.find((e): e is Extract<ResultEvent, { type: "round_pnl" }> => e.type === "round_pnl");
              return (
                <details className="round" key={i} open={!!a && a.rating !== "sound"}>
                  <summary>
                    <span className="dim">R{t.observation.episode.round + 1}</span> <span className="rk">{t.observation.kind}</span> {describeDecision(t.decision)}
                    {a ? <RatingChip rating={a.rating} /> : t.result.grade ? <span className={t.result.grade.correct ? "pos" : "neg"}>{t.result.grade.correct ? "✓ correct" : "✗ missed"}</span> : null}
                    {pnl ? <span className="r"><Num v={pnl.round_pnl} /></span> : null}
                  </summary>
                  <div className="round-b">
                    <div className="rb-k">OUTCOME</div><ul className="events">{t.result.events.filter((e) => e.type !== "round_pnl" && e.type !== "market").map((e, j) => <EventLine key={j} e={e} />)}</ul>
                    {a ? <><div className="rb-k">RISK</div><div className="dim">DV01 {typeof a.metrics.dv01_before === "number" ? <Num v={a.metrics.dv01_before} /> : "–"} → {typeof a.metrics.dv01_after === "number" ? <Num v={a.metrics.dv01_after} /> : "–"}</div>
                      <div className="rb-k">ASSESSMENT</div><ul className="reasons">{reasons.map((r, j) => <li key={j}>{r}</li>)}</ul></> : null}
                  </div>
                </details>
              );
            })}
          </Panel>
        </div>
        <div className="debrief-col">
          <Panel title="P&amp;L THROUGH THE EPISODE"><PnlPath points={path} /></Panel>
          <Panel title="WHERE THE P&amp;L CAME FROM" aside={<span className="dim">by cause</span>}>
            <SignedBars rows={d.outcome.by_cause.map((c) => ({ label: c.cause.replace("market: ", "").replace("time: ", "").replace("_", " "), value: c.amount }))} labelWidth={118} />
            {d.outcome.spread_note ? <p className="hint dim">Your hedges carried spread risk: swap spread {eur(d.outcome.spread_note.swap_spread)}, futures basis {eur(d.outcome.spread_note.fut_basis)}.</p> : null}
          </Panel>
          {d.outcome.exposures_by_round ? (
            <Panel title="LEVEL AND SLOPE BY ROUND" aside={<span className="dim">after each decision: did you run curve risk on purpose?</span>}>
              <table className="tbl">
                <thead><tr><th>Round</th><th className="r">Level (DV01)</th><th className="r">Slope</th></tr></thead>
                <tbody>{d.outcome.exposures_by_round.map((x) => (<tr key={x.round}><td className="dim">R{x.round + 1}</td><td className="r"><Num v={x.level} /></td><td className="r"><Num v={x.slope} /></td></tr>))}</tbody>
              </table>
            </Panel>
          ) : null}
          {(d.evidence_vs_truth && d.evidence_vs_truth.length) || d.view_truth ? (
            <Panel title="INFORMATION, NOW REVEALED" aside={<span className="dim">what the desk could not see</span>}>
              {d.view_truth ? <p>The research view <strong className={d.view_truth.right ? "pos" : "neg"}>{d.view_truth.right ? "carried real information" : "was noise"}</strong> this time (stated reliability {Math.round(d.view_truth.reliability * 100)}%). A call is judged by its expected value at the stated reliability, not by how it turned out.</p> : null}
              {d.evidence_vs_truth && d.evidence_vs_truth.length ? (
                <table className="tbl">
                  <thead><tr><th>Client</th><th>Truth</th><th className="r">Model's P(informed), request by request</th></tr></thead>
                  <tbody>{d.evidence_vs_truth.map((e) => (
                    <tr key={e.name}><td>{e.name}</td><td className={e.informed ? "neg" : "pos"}>{e.informed ? "informed" : "not informed"}</td><td className="r num">{e.posteriors.map((p) => `${Math.round(p * 100)}%`).join(" → ")}</td></tr>))}</tbody>
                </table>
              ) : null}
              <p className="hint dim">The probabilities are the model's, computed from what you had seen at each request (the same evidence you were shown). They were hidden while you traded.</p>
            </Panel>
          ) : null}
          {paths ? (
            <Panel title="OUTCOME ACROSS SIMULATED MARKET PATHS" aside={<span className="dim">{paths.n} paths, your decisions and fills</span>}>
              <Distribution yours={paths.yours.samples} reference={paths.reference?.samples ?? null} realised={d.outcome.total} />
              <p className="hint dim">{paths.label}. The 5th to 95th percentile runs from {eur(paths.yours.p05)} to {eur(paths.yours.p95)}; your realised result sits at the {Math.round(paths.rank * 100)}th percentile. The dashed outline is the reference desk's policy on the same paths. One path is one draw: judge the decision by the distribution, the result by the luck.</p>
            </Panel>
          ) : isLevel5 && loadingFull ? <div className="skeleton" aria-busy>running the simulated market paths…</div> : null}
          <Panel title="SAME CLIENTS, SAME MARKET PATH" aside={<span className="dim">other policies</span>}>
            {cf ? (
              <table className="tbl">
                <thead><tr><th>Policy</th><th className="r">P&amp;L</th><th>Decisions</th></tr></thead>
                <tbody>
                  {cf.policies.map((p) => (<tr key={p.name}><td>{p.name}</td><td className="r"><Num v={p.pnl} /></td><td><RatingStrip ratings={p.ratings} /></td></tr>))}
                  <tr className="you"><td><strong>you</strong></td><td className="r"><Num v={cf.you} /></td><td><RatingStrip ratings={d.decisions.map((x) => x.rating)} /></td></tr>
                </tbody>
              </table>
            ) : <div className="skeleton" aria-busy>{loadingFull ? "running the alternatives on your path…" : ""}</div>}
            <p className="hint dim">A higher P&amp;L on this path is not a better decision: look at the ratings, which are judged on what was known at the time.</p>
          </Panel>
          <Panel title="CLIENTS, NOW REVEALED">
            <table className="tbl"><tbody>{d.clients.map((c) => (
              <tr key={c.round}><td className="dim">R{c.round + 1}</td><td>{c.name ?? c.ctype.replace("_", " ")}</td><td>{c.action === "pays" ? "pays" : "receives"} {eurM(c.notional)}</td>
                <td>{c.informed ? "informed" : "not informed"}</td><td className="dim">{c.traded ? "traded with you" : "did not trade"}</td></tr>))}</tbody></table>
          </Panel>
        </div>
      </div>
      <p className="hint dim center">{num(d.decisions.length)} decisions · saved locally for Review.</p>
    </div>
  );
}
