import { useEffect, useRef } from "react";
import type { EpisodeMeta } from "../api/types";
import type { Phase } from "./machine";

const WHERE: Partial<Record<Phase, string>> = {
  awaiting: "Nothing you have typed will be sent.",
  armed: "Your armed decision has not been committed and will not be sent.",
  settled: "Your last decision is already committed; its result stays in the session.",
};

/** Confirmation before abandoning an unfinished episode. Leaving sends nothing to the engine: no commit, no continue. */
export function LeaveDialog(p: { episode: EpisodeMeta; round: number; phase: Phase; onStay: () => void; onLeave: () => void }) {
  const stay = useRef<HTMLButtonElement>(null);
  useEffect(() => { stay.current?.focus(); }, []);
  return (
    <div className="overlay" role="alertdialog" aria-modal="true" aria-labelledby="leave-h" aria-describedby="leave-b" onClick={p.onStay}>
      <div className="sheet confirm" onClick={(e) => e.stopPropagation()}>
        <header className="sheet-h"><h2 id="leave-h">LEAVE THIS EPISODE?</h2></header>
        <div className="sheet-b" id="leave-b">
          <p>Level {p.episode.level} is unfinished (round {Math.min(p.round + 1, p.episode.rounds)} of {p.episode.rounds}) and will not be debriefed or saved to your history.</p>
          <p className="dim">{WHERE[p.phase] ?? ""} It stays open on this server so you can pick it up from the level menu under IN PROGRESS, until the server restarts.</p>
          <div className="confirm-actions">
            <button ref={stay} className="btn btn-primary" onClick={p.onStay}>Keep playing <span className="kbd-inline">Esc</span></button>
            <button className="btn" onClick={p.onLeave}>Leave to levels</button>
          </div>
        </div>
      </div>
    </div>
  );
}
