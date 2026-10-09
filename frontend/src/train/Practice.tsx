import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { DonePart, PartResult, PartView, QuestionView, TrainState } from "../api/types";
import { Chip, Panel } from "../components/ui";
import { Scratchpad } from "../desk/Scratchpad";
import { Stem } from "./Stem";
import { useTrain } from "./store";

const letter = (i: number) => String.fromCharCode(65 + i);
const isTyping = (t: EventTarget | null) => { const el = t as HTMLElement | null; return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT"); };

/** What an entry was read as, asked of the grader's own parser (never re-implemented here). */
function useReadAs(sessionId: string, part: PartView | null, draft: string) {
  const [r, setR] = useState<{ ok: true; read_as: string } | { ok: false; error: string } | null>(null);
  const tok = useRef(0);
  useEffect(() => {
    const mine = ++tok.current;
    if (!part || part.kind !== "numeric" || draft.trim() === "") { setR(null); return; }
    const h = setTimeout(() => { api.trainCheck(sessionId, draft).then((x) => { if (mine === tok.current) setR(x); }).catch(() => { if (mine === tok.current) setR(null); }); }, 200);
    return () => clearTimeout(h);
  }, [sessionId, part, draft]);
  return r;
}

const answerText = (p: PartView, submitted: string) => (p.kind === "choice" && submitted ? `${submitted.toUpperCase()}. ${p.options[submitted.toUpperCase().charCodeAt(0) - 65] ?? ""}` : submitted || "—");

function Verdict({ r }: { r: PartResult }) {
  const [glyph, cls, word] = r.status === "correct" ? ["✓", "pos", "CORRECT"] : r.status === "skipped" ? ["↷", "warn", "SKIPPED"] : ["✕", "neg", "NOT CORRECT"];
  return <div className={`verdict-line ${cls}`}><span aria-hidden>{glyph}</span> <strong>{word}</strong>{r.status !== "skipped" && r.feedback !== "Correct." ? <span className="dim"> {r.feedback}</span> : null}</div>;
}

/** The part just answered: what was submitted, how it was marked, the expected answer, the working and the rationale, as separate rows. */
function ResultBlock({ part }: { part: DonePart }) {
  const r = part.result;
  return (
    <div className="result" data-status={r.status} aria-live="polite">
      <Verdict r={r} />
      <dl className="rows">
        <dt>Your answer</dt><dd className="num">{answerText(part, part.submitted)}</dd>
        <dt>Expected</dt><dd className="num">{r.expected}</dd>
        {r.detail ? <><dt>Working</dt><dd className="detail">{r.detail.split(" | ").map((l, i) => <div key={i}>{l}</div>)}</dd></> : null}
        {r.why ? <><dt>Why</dt><dd>{r.why}</dd></> : null}
      </dl>
    </div>
  );
}

function Stepper({ q, answering }: { q: QuestionView; answering: boolean }) {
  if (q.parts_total < 2) return null;
  return (
    <ol className="stepper-parts" aria-label="parts">
      {Array.from({ length: q.parts_total }, (_, i) => {
        const d = q.parts_done[i];
        const state = d ? d.result.status : answering && q.current?.index === i ? "now" : "todo";
        return <li key={i} className={`sp sp-${state}`} aria-current={state === "now" ? "step" : undefined}>
          <span className="sp-n">{i + 1}</span>{state === "correct" ? "✓" : state === "incorrect" ? "✕" : state === "skipped" ? "↷" : ""}</li>;
      })}
    </ol>
  );
}

export function Practice({ onLeave }: { onLeave: () => void }) {
  const s = useTrain();
  const st = s.state as TrainState;
  const q = st.question as QuestionView;
  const [leaving, setLeaving] = useState(false);
  const answering = st.phase === "answering";
  const cur = answering ? q.current : null;
  const justDone = !answering ? q.parts_done[q.parts_done.length - 1] : undefined;
  const earlier = answering ? q.parts_done : q.parts_done.slice(0, -1);
  const lastPart = q.parts_done.length === q.parts_total;
  const lastQuestion = st.index + 1 >= st.total;
  const readAs = useReadAs(st.id, cur, s.draft);
  const unreadable = readAs !== null && !readAs.ok;
  const numRef = useRef<HTMLInputElement>(null);
  const busy = s.busy !== null;

  useEffect(() => { if (cur?.kind === "numeric") numRef.current?.focus(); }, [cur?.index, q.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = useTrain.getState();
      if (e.key === "Escape") { if (leaving) setLeaving(false); return; }
      if (leaving || e.metaKey || e.ctrlKey || e.altKey) return;               // a dialog is open: no key may answer or continue behind it
      const el = e.target as HTMLElement;
      if (e.key === "Enter" && el.tagName === "BUTTON" && !el.classList.contains("opt")) return;   // a focused button handles its own Enter
      if (e.key === "Enter") {
        if (t.state?.phase === "answering") { e.preventDefault(); void t.submit(); }
        else if (t.state?.phase === "feedback") { e.preventDefault(); void t.next(); }
        return;
      }
      const part = t.state?.question?.current;
      if (t.state?.phase === "answering" && part?.kind === "choice" && !isTyping(e.target)) {
        const k = e.key.toUpperCase();
        const i = /^[A-Z]$/.test(k) ? k.charCodeAt(0) - 65 : /^[1-9]$/.test(k) ? Number(k) - 1 : -1;
        if (i >= 0 && i < part.options.length) t.setDraft(letter(i));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [leaving]);

  const asked = st.parts_answered;
  const leave = () => { if (asked > 0 && st.phase !== "done") setLeaving(true); else onLeave(); };

  return (
    <div className="train-q">
      <header className="tq-head">
        <button className="btn btn-ghost tq-back" onClick={leave}>‹ Catalogue</button>
        <div className="tq-crumb"><span className="dim">{q.track_title}</span> <span className="dim">›</span> <strong>{q.skill_title}</strong></div>
        <div className="tq-prog num" aria-label="progress"><span>Question {st.index + 1} <span className="dim">of {st.total}</span></span>
          <span className="dim"> · {st.parts_correct}/{st.parts_answered} parts</span></div>
        <div className="tq-bar" aria-hidden><span style={{ width: `${(st.index / st.total) * 100}%` }} /></div>
      </header>

      <div className="tq-body">
        <section className="tq-problem" aria-label="problem">
          <div className="tq-tags">
            <Chip title={q.difficulty_label}>level {q.difficulty} · {q.difficulty_label}</Chip>
            <Chip tone={q.kind === "calculation" ? "accent" : "neutral"}>{q.kind}</Chip>
            {q.curated ? <Chip title="hand-written question">curated</Chip> : <Chip title="numbers generated from the engine">generated</Chip>}
          </div>
          <Stem text={q.stem} />
          <Stepper q={q} answering={answering} />
          <div className="tq-foot dim"><span>Question id</span> <span className="num">{q.id}</span> <span>replays exactly this question</span></div>
          {earlier.length ? (
            <ol className="earlier" aria-label="earlier parts">
              {earlier.map((p) => (
                <li key={p.index} className={`ep ep-${p.result.status}`}>
                  <span className="ep-n">{p.index + 1}</span>
                  <div><div className="ep-q">{p.prompt}</div>
                    <div className="ep-a num">{answerText(p, p.submitted)}{p.result.correct ? null : <span className="dim"> · expected {p.result.expected}</span>}</div></div>
                  <span className="ep-s" aria-label={p.result.status}>{p.result.status === "correct" ? "✓" : p.result.status === "skipped" ? "↷" : "✕"}</span>
                </li>))}
            </ol>
          ) : null}
        </section>

        <section className="tq-work" aria-label="answer">
          {answering && cur ? (
            <Panel title={q.parts_total > 1 ? `PART ${cur.index + 1} OF ${q.parts_total}` : "YOUR ANSWER"} aside={cur.kind === "numeric" ? <span className="dim">{cur.unit_label}</span> : <span className="dim">choose one</span>}>
              <p className="prompt">{cur.prompt}</p>
              {cur.kind === "choice" ? (
                <div className="options" role="radiogroup" aria-label="options">
                  {cur.options.map((o, i) => (
                    <button key={i} role="radio" aria-checked={s.draft === letter(i)} className={`opt ${s.draft === letter(i) ? "on" : ""}`} disabled={busy} onClick={() => s.setDraft(letter(i))}>
                      <span className="opt-k num">{letter(i)}</span><span>{o}</span>
                    </button>))}
                </div>
              ) : (
                <>
                  <div className="num-entry">
                    <input ref={numRef} className="in in-lg num" inputMode="decimal" autoComplete="off" spellCheck={false} aria-label="your answer" value={s.draft} disabled={busy}
                      aria-invalid={unreadable} placeholder={cur.note ? cur.note.replace(/^e\.g\.\s*/, "e.g. ") : ""} onChange={(e) => s.setDraft(e.target.value)} />
                    <span className="unit num">{cur.unit}</span>
                  </div>
                  <div className="read-as" aria-live="polite">
                    {readAs === null ? <span className="dim">{cur.entry_hint}</span>
                      : readAs.ok ? <span>read as <strong className="num">{readAs.read_as}</strong></span>
                        : <span className="neg">{readAs.error}</span>}
                  </div>
                  <Scratchpad locked={busy} onUse={(v) => s.setDraft(v)} />
                </>
              )}
              {s.error ? <p className="neg" role="alert">{s.error} <span className="dim">Nothing was marked.</span></p> : null}
              <div className="tq-actions">
                <button className="btn btn-primary" disabled={busy || s.draft.trim() === "" || unreadable} onClick={() => void s.submit()}>Submit answer <span className="kbd-inline">⏎</span></button>
                <button className="btn btn-ghost" disabled={busy} onClick={() => void s.skip()}>Skip</button>
                {cur.kind === "choice" ? <span className="dim hint">press A–{letter(cur.options.length - 1)} to choose, Enter to submit</span> : null}
              </div>
            </Panel>
          ) : justDone ? (
            <>
              <Panel title={q.parts_total > 1 ? `PART ${justDone.index + 1} OF ${q.parts_total} · RESULT` : "RESULT"}>
                <p className="prompt dim">{justDone.prompt}</p>
                <ResultBlock part={justDone} />
              </Panel>
              {lastPart && q.solution ? (
                <Panel title="WORKED SOLUTION" aside={<span className="dim">{q.question_correct ? "all parts correct" : "some parts missed"}</span>}>
                  <ul className="solution">{q.solution.map((l, i) => <li key={i}>{l}</li>)}</ul>
                </Panel>
              ) : null}
              <div className="tq-actions">
                <button className="btn btn-primary" autoFocus disabled={busy} onClick={() => void s.next()}>
                  {!lastPart ? "Next part" : lastQuestion ? "Finish session" : "Next question"} <span className="kbd-inline">⏎</span></button>
                {s.error ? <span className="neg" role="alert">{s.error}</span> : null}
              </div>
            </>
          ) : null}
        </section>
      </div>

      {leaving ? (
        <div className="overlay" role="alertdialog" aria-modal="true" aria-labelledby="end-h" onClick={() => setLeaving(false)}>
          <div className="sheet confirm" onClick={(e) => e.stopPropagation()}>
            <header className="sheet-h"><h2 id="end-h">END THIS SESSION?</h2></header>
            <div className="sheet-b">
              <p>You have answered {st.parts_answered} {st.parts_answered === 1 ? "part" : "parts"} ({st.parts_correct} correct). They are kept in your practice history; the remaining questions are not asked.</p>
              <div className="confirm-actions">
                <button className="btn btn-primary" autoFocus onClick={() => setLeaving(false)}>Keep practising <span className="kbd-inline">Esc</span></button>
                <button className="btn" onClick={() => { setLeaving(false); void s.finish(); }}>End session</button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
