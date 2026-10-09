import type { TrainState, TrainSummary } from "../api/types";
import { Chip, Panel } from "../components/ui";

const PHRASE = { focused: "Focused practice", mixed: "Mixed practice", single: "Single question", replay: "Replay" } as const;

export function Summary({ state, summary, busy, onAgain, onReplay, onCatalogue }: {
  state: TrainState; summary: TrainSummary | null; busy: boolean; onAgain: () => void; onReplay: (ids: string[]) => void; onCatalogue: () => void;
}) {
  if (!summary) return <div className="center dim">Summing up…</div>;
  const pct = summary.parts_total ? Math.round((100 * summary.parts_correct) / summary.parts_total) : 0;
  const repeatable = state.mode === "focused" || state.mode === "mixed";
  return (
    <div className="train-sum">
      <header className="train-intro">
        <h1>{summary.ended_early ? "Session ended early" : "Session complete"}</h1>
        <p className="dim">{PHRASE[state.mode]}{state.mode === "focused" || state.mode === "mixed" ? ` · ${state.label}` : ""} · {summary.questions.length} of {summary.questions_planned} questions answered. Saved to your practice history.</p>
      </header>
      <div className="sum-score">
        <div className="card"><div className="card-k">PARTS CORRECT</div><div className="card-v big num">{summary.parts_correct}<span className="dim"> / {summary.parts_total}</span></div><div className="card-s dim">{pct}% · each part of a multi-part question counts</div></div>
        <div className="card"><div className="card-k">TO REPLAY</div><div className="card-v big num">{summary.missed.length}</div><div className="card-s dim">{summary.missed.length ? "questions with a missed or skipped part" : "nothing missed"}</div></div>
      </div>
      <Panel title="BY SKILL">
        <table className="tbl">
          <thead><tr><th>Skill</th><th className="r">Parts correct</th></tr></thead>
          <tbody>{summary.by_skill.map((k) => (
            <tr key={k.skill}><td>{k.title} <span className="dim num">{k.skill}</span></td><td className="r num">{k.correct} / {k.total}</td></tr>))}</tbody>
        </table>
      </Panel>
      <Panel title="QUESTIONS">
        <table className="tbl">
          <thead><tr><th /><th>Question</th><th>Type</th><th className="r">Parts</th></tr></thead>
          <tbody>{summary.questions.map((q) => (
            <tr key={q.id}><td className={q.correct ? "pos" : "neg"} aria-label={q.correct ? "correct" : "missed"}>{q.correct ? "✓" : "✕"}</td>
              <td>{q.skill_title}<div className="dim num">{q.id}</div></td>
              <td><Chip>level {q.difficulty}</Chip> <Chip tone={q.kind === "calculation" ? "accent" : "neutral"}>{q.kind}</Chip></td>
              <td className="r num">{q.parts_correct} / {q.parts_answered}{q.parts_answered < q.parts_total ? <span className="dim"> of {q.parts_total}</span> : null}</td></tr>))}</tbody>
        </table>
      </Panel>
      <div className="tq-actions">
        {summary.missed.length ? <button className="btn btn-primary" disabled={busy} onClick={() => onReplay(summary.missed)}>Replay what you missed ({summary.missed.length})</button> : null}
        {repeatable ? <button className="btn" disabled={busy} onClick={onAgain}>Same selection, new questions</button> : null}
        <button className="btn btn-ghost" onClick={onCatalogue}>‹ Back to the catalogue</button>
      </div>
    </div>
  );
}
