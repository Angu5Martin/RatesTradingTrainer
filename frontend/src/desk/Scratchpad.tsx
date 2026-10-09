import { useState } from "react";
import { evalExpr } from "../lib/calc";
import { num } from "../lib/format";

/** A scratch calculator beside a calculation check: type an expression, Enter keeps the line, a kept result can be put into the answer. */
export function Scratchpad({ onUse, locked }: { onUse: (v: string) => void; locked: boolean }) {
  const [text, setText] = useState("");
  const [lines, setLines] = useState<{ expr: string; v: number }[]>([]);
  const v = text.trim() ? evalExpr(text) : null;
  const keep = () => { if (v !== null) { setLines((l) => [...l.slice(-7), { expr: text.trim(), v }]); setText(""); } };
  return (
    <div className="scratch">
      <div className="scratch-h dim">SCRATCHPAD <span>arithmetic only: + − × ÷ ( ), 625m, 456, 1.2k</span></div>
      <div className="scratch-lines">
        {lines.map((l, i) => (
          <div className="scratch-line" key={i}><span className="dim">{l.expr}</span><span className="num">= {num(l.v, Math.abs(l.v) < 100 ? 2 : 0)}</span>
            <button className="btn btn-sm btn-ghost" disabled={locked} onClick={() => onUse(String(Math.round(l.v * 100) / 100))}>use as answer</button></div>
        ))}
      </div>
      <div className="scratch-in">
        <input className="in num" value={text} disabled={locked} placeholder="e.g. 625 * 456 / 1000 − 250.3k" aria-label="scratchpad" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); keep(); } }} />
        <span className="num scratch-v">{v === null ? (text.trim() ? "…" : "") : `= ${num(v, Math.abs(v) < 100 ? 2 : 0)}`}</span>
      </div>
    </div>
  );
}
