import { useEffect, useState } from "react";
import { LiveDesk } from "../desk/LiveDesk";
import { Review } from "../review/Review";
import { Train } from "../train/Train";

export type Area = "train" | "desk" | "review";
const AREAS: { id: Area; label: string; hint: string }[] = [
  { id: "train", label: "TRAIN", hint: "focused practice" },
  { id: "desk", label: "LIVE DESK", hint: "market making" },
  { id: "review", label: "REVIEW", hint: "history and debriefs" },
];

const fromHash = (): Area => { const h = window.location.hash.replace("#/", ""); return h === "train" || h === "review" ? h : "desk"; };

export function App() {
  const [area, setArea] = useState<Area>(fromHash());
  useEffect(() => { const f = () => setArea(fromHash()); window.addEventListener("hashchange", f); return () => window.removeEventListener("hashchange", f); }, []);
  const go = (a: Area) => { window.location.hash = `#/${a}`; };
  return (
    <div className={`shell mode-${area}`}>
      <nav className="rail" aria-label="Areas">
        <div className="brand">EUR RATES<span className="dim"> desk</span></div>
        {AREAS.map((a) => (
          <button key={a.id} className={`rail-item ${area === a.id ? "on" : ""}`} onClick={() => go(a.id)} aria-current={area === a.id ? "page" : undefined}>
            <span className="rail-l">{a.label}</span><span className="rail-h">{a.hint}</span>
          </button>
        ))}
      </nav>
      <main className="content">
        {area === "train" ? <Train /> : null}
        {area === "desk" ? <LiveDesk onExit={() => go("review")} /> : null}
        {area === "review" ? <Review /> : null}
      </main>
    </div>
  );
}
