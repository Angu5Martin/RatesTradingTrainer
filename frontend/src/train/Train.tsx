import { useEffect } from "react";
import { Catalogue } from "./Catalogue";
import { Practice } from "./Practice";
import { Summary } from "./Summary";
import { rememberedPractice, useTrain } from "./store";
import type { TrainStart } from "../api/types";

/** TRAIN: the catalogue and practice builder, the one-problem practice screen, and the end-of-session summary. */
export function Train() {
  const s = useTrain();
  useEffect(() => {                                   // a reload lands back on the same part, and on its result if it was answered
    const id = rememberedPractice();
    if (id && useTrain.getState().state === null && !useTrain.getState().busy) void useTrain.getState().resume(id);
  }, []);
  const again = () => {
    const sel = (s.state?.selection ?? {}) as { tracks?: string[]; skills?: string[]; difficulty?: number | null; max_difficulty?: number | null; kind?: TrainStart["kind"]; count?: number };
    void s.start({ tracks: sel.tracks, skills: sel.skills, difficulty: sel.difficulty ?? null, max_difficulty: sel.max_difficulty ?? null, kind: sel.kind ?? null, count: sel.count ?? 10 });
  };
  if (s.state && s.state.phase === "done") {
    return <div className="page"><Summary state={s.state} summary={s.summary} busy={s.busy !== null} onAgain={again} onReplay={(ids) => void s.start({ ids, label: "Replay of missed questions" })} onCatalogue={s.reset} /></div>;
  }
  if (s.state && s.state.question) return <div className="page train-wide"><Practice onLeave={s.reset} /></div>;
  return <div className="page train-wide"><Catalogue busy={s.busy === "starting"} error={s.error} onStart={(b) => void s.start(b)} /></div>;
}
