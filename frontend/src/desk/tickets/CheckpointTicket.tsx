import type { ObservationView } from "../../api/types";
import { Panel } from "../../components/ui";
import { Scratchpad } from "../Scratchpad";
import type { Draft } from "../draft";

export function CheckpointTicket({ obs, draft, setDraft, locked }: { obs: ObservationView; draft: Extract<Draft, { kind: "checkpoint" }>; setDraft: (d: Draft) => void; locked: boolean }) {
  const unit = obs.input.unit ?? "";
  return (
    <Panel title="CALCULATION CHECK" aside={<span className="dim">{obs.checkpoint?.intro}</span>} className="ticket grow">
      <p className="prompt">{obs.prompt}</p>
      <div className="rfq-row">
        <input className="in in-lg num" autoFocus value={draft.text} disabled={locked} aria-label="your answer" placeholder="e.g. −11.6k" onChange={(e) => setDraft({ kind: "checkpoint", text: e.target.value })} />
        <span className="dim">{unit}</span>
      </div>
      <p className="hint dim">{obs.input.hint}. Accepts 125k, -1.2m, 1,348. {obs.checkpoint?.inquiry ? "Work from the request above and the book on the right." : "Work from the trade just done and the book on the right."}</p>
      <Scratchpad locked={locked} onUse={(v) => setDraft({ kind: "checkpoint", text: v })} />
    </Panel>
  );
}
