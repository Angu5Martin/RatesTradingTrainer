import type { ResultEvent } from "../api/types";
import { RatingChip } from "../components/ui";
import { eur } from "../lib/format";
import type { TranscriptEntry } from "./store";

const KIND = { quote: "quote", rfq: "price", checkpoint: "check", hedge: "hedge", position: "position", overnight: "overnight", rehedge: "re-hedge" } as const;

export function Tape({ transcript }: { transcript: TranscriptEntry[] }) {
  if (!transcript.length) return <footer className="tape dim">Decisions will appear here as you commit them.</footer>;
  return (
    <footer className="tape" aria-label="decision tape">
      {transcript.map((t, i) => {
        const pnl = t.result.events.find((e): e is Extract<ResultEvent, { type: "round_pnl" }> => e.type === "round_pnl");
        return (
          <span className="tape-item" key={i}>
            <span className="dim">R{t.observation.episode.round + 1}</span> {KIND[t.observation.kind]}
            {t.result.assessment ? <> <RatingChip rating={t.result.assessment.rating} /></> : t.result.grade ? <span className={t.result.grade.correct ? "pos" : "neg"}> {t.result.grade.correct ? "✓" : "✗"}</span> : null}
            {pnl ? <span className={`num ${pnl.round_pnl >= 0 ? "pos" : "neg"}`}> {eur(pnl.round_pnl)}</span> : null}
          </span>
        );
      })}
    </footer>
  );
}
