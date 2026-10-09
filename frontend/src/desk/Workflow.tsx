import type { Kind } from "../api/types";
import type { Phase } from "./machine";

const STAGES = ["Market", "Fair value", "Quote", "Client trade", "Position", "Risk", "Hedge", "Move", "P&L"] as const;
type Stage = (typeof STAGES)[number];

/** Which stage of the loop the screen is at. Purely a function of the phase and the kind of prompt. */
export function activeStage(phase: Phase, kind: Kind | null): Stage {
  if (phase === "settled" || phase === "continuing" || phase === "finished") return "P&L";
  switch (kind) {
    case "quote": return "Quote";
    case "rfq": return "Quote";
    case "checkpoint": return "Position";
    case "hedge": case "rehedge": case "overnight": case "position": return "Hedge";
    default: return "Market";
  }
}

export function Workflow({ phase, kind, onGuide }: { phase: Phase; kind: Kind | null; onGuide?: () => void }) {
  const at = STAGES.indexOf(activeStage(phase, kind));
  return (
    <nav className="workflow" aria-label="Trading loop">
      {STAGES.map((s, i) => (
        <span key={s} className={`wf-step ${i === at ? "wf-now" : i < at ? "wf-done" : ""}`} aria-current={i === at ? "step" : undefined}>{s}</span>
      ))}
      {onGuide ? <button className="wf-help" onClick={onGuide} title="How to trade the desk: decision process, quoting, risk and hedging, worked examples">How to</button> : null}
    </nav>
  );
}
