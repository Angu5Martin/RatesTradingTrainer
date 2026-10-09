import { Num, Panel, RatingChip } from "../components/ui";
import { describeDecision } from "../lib/ticket";
import type { ResultEvent } from "../api/types";
import type { TranscriptEntry } from "./store";

/** Every decision committed so far in this session, with its judgement and the P&L it carried. Only things already revealed. */
export function Blotter({ transcript }: { transcript: TranscriptEntry[] }) {
  return (
    <Panel title="SESSION" aside={<span className="dim">{transcript.length} decision{transcript.length === 1 ? "" : "s"} committed</span>} className="grow blotter">
      <table className="tbl">
        <thead><tr><th>Rd</th><th>Step</th><th>Decision</th><th>Judged</th><th className="r">Round P&amp;L</th></tr></thead>
        <tbody>
          {transcript.map((t, i) => {
            const pnl = t.result.events.find((e): e is Extract<ResultEvent, { type: "round_pnl" }> => e.type === "round_pnl");
            return (
              <tr key={i}>
                <td className="dim">{t.observation.episode.round + 1}</td><td className="dim">{t.observation.kind}</td><td>{describeDecision(t.decision)}</td>
                <td>{t.result.assessment ? <RatingChip rating={t.result.assessment.rating} /> : t.result.grade ? <span className={t.result.grade.correct ? "pos" : "neg"}>{t.result.grade.correct ? "✓ correct" : "✗ missed"}</span> : null}</td>
                <td className="r">{pnl ? <Num v={pnl.round_pnl} /> : <span className="dim">–</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}
