import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PracticeSaved, SavedSession } from "../api/types";
import { Num, Panel } from "../components/ui";

/** Placeholder for the analytical review area. It lists the finished episodes the server has saved (the record Review will be built on). */
export function Review() {
  const [rows, setRows] = useState<SavedSession[] | null>(null);
  const [practice, setPractice] = useState<PracticeSaved[]>([]);
  useEffect(() => { api.sessions().then(setRows).catch(() => setRows([])); api.trainHistory().then(setPractice).catch(() => undefined); }, []);
  return (
    <div className="page">
      <Panel title="REVIEW" aside={<span className="dim">analysis: later milestone</span>}>
        <p className="dim">Every finished Live Desk episode is saved locally with its transcript and replay record. Re-opened debriefs, question performance and weak areas will be built on these.</p>
        {rows === null ? <p className="dim">loading…</p> : rows.length === 0 ? <p className="dim">No finished episodes yet.</p> : (
          <table className="tbl">
            <thead><tr><th>Saved</th><th>Level</th><th className="r">Decisions</th><th>Sound / def / poor / err</th><th className="r">P&amp;L</th><th className="r">Luck</th></tr></thead>
            <tbody>{rows.map((s) => (
              <tr key={s.id}><td className="dim">{s.saved}</td><td>L{s.level}</td><td className="r num">{s.decisions}</td>
                <td className="num">{s.ratings.sound} / {s.ratings.defensible} / {s.ratings.poor} / {s.ratings.error}</td><td className="r"><Num v={s.pnl} /></td><td className="r"><Num v={s.luck} /></td></tr>))}</tbody>
          </table>
        )}
      </Panel>
      {practice.length ? (
        <Panel title="PRACTICE SESSIONS" aside={<span className="dim">every graded part is kept: what you submitted and how it was marked</span>}>
          <table className="tbl">
            <thead><tr><th>Started</th><th>Practice</th><th className="r">Questions</th><th className="r">Parts correct</th></tr></thead>
            <tbody>{practice.map((p) => (
              <tr key={p.id}><td className="dim num">{p.started.replace("T", " ")}</td><td>{p.label}{p.ended_early ? <span className="dim"> · ended early</span> : null}</td>
                <td className="r num">{p.questions}</td><td className="r num">{p.parts_correct} / {p.parts_total}</td></tr>))}</tbody>
          </table>
        </Panel>
      ) : null}
    </div>
  );
}
