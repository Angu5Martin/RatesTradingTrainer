import { useCallback, useEffect, useMemo, useState } from "react";
import { rememberedSession, useDesk } from "./store";
import { curveHistory, focusOf, latest, pnlNow, seen } from "./derive";
import { StartPanel } from "./StartPanel";
import { TopBar } from "./TopBar";
import { Workflow } from "./Workflow";
import { Tape } from "./Tape";
import { Reference } from "./Reference";
import { LeaveDialog } from "./LeaveDialog";
import { Debrief } from "./Debrief";
import { GuideSheet } from "../guide/GuideSheet";
import { DESK_GUIDES } from "../guide/guides";
import { DecisionLayout, ResultLayout } from "./layouts";
import { type Exposures, noAdded, rowsFromEvents } from "./RiskPanel";
import { SKEW_BIG, SKEW_STEP, stepQuote } from "./tickets/QuoteTicket";
import { showsResult } from "./machine";
import type { ObservationView, StepResultView } from "../api/types";

/** DV01 once the decision has been carried out, from the assessment's own figure. A price that did not deal changed nothing, and the figure then
 *  describes the trade that did not happen, so it is not shown. */
export function dv01AfterDecision(result: StepResultView | undefined): number | null {
  const a = result?.assessment;
  if (!a || typeof a.metrics.dv01_after !== "number") return null;
  if (a.kind === "quote" || a.kind === "rfq") {
    const dealt = result!.events.some((e) => e.type === "fill" && e.filled);
    return dealt ? a.metrics.dv01_after : null;
  }
  return a.metrics.dv01_after;
}

/** The exposures the assessment reports for the decision just taken (level, slope, curvature, spreads), under the same rule as the DV01 above: a price that did
 *  not deal changed nothing, and the figure then describes the trade that did not happen. Null before a commit and for single-tenor books. */
export function exposuresAfterDecision(result: StepResultView | undefined): Exposures | null {
  const m = result?.assessment?.metrics as { x_after?: Exposures; exposures?: Exposures } | undefined;
  const x = m?.x_after ?? m?.exposures;
  if (!x || dv01AfterDecision(result) === null) return null;
  return x;
}

function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT");
}

export function LiveDesk({ onExit }: { onExit: () => void }) {
  const s = useDesk();
  const [showRef, setShowRef] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [showGuide, setShowGuide] = useState(false);              // the How To guide: an overlay, so the desk underneath keeps its state
  const closeGuide = useCallback(() => setShowGuide(false), []);

  useEffect(() => {                                   // a reload lands back in the session in progress (on its pending result, never past it)
    const id = rememberedSession();
    if (id && useDesk.getState().phase === "idle") void useDesk.getState().resume(id);
  }, []);
  useEffect(() => { if (s.phase === "finished") void s.loadDebrief(); }, [s.phase]); // eslint-disable-line react-hooks/exhaustive-deps

  const obs = s.observation;
  const decided = s.pending?.observation ?? null;
  const view: ObservationView | null = obs ?? decided;
  const all = useMemo(() => seen(s), [s.transcript, s.observation, s.pending]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const st = useDesk.getState();
      if (e.key === "Escape") { if (leaving) setLeaving(false); else if (showRef) setShowRef(false); else st.disarm(); return; }
      if (leaving || showRef || showGuide) return;    // a dialog is open: no key may arm, commit or continue behind it
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "Enter") {
        if (st.phase === "awaiting") { e.preventDefault(); st.arm(); }
        else if (st.phase === "armed") { e.preventDefault(); void st.commit(); }
        else if (st.phase === "settled") { e.preventDefault(); void st.next(); }
        return;
      }
      if (isTyping(e.target) || st.phase !== "awaiting" || !st.observation || !st.draft) return;
      const k = st.observation.kind;
      if ((e.key === "p" || e.key === "P") && k === "rfq") { st.arm(true); }
      if ((e.key === "n" || e.key === "N") && st.draft.kind === "hedge") {
        if (k === "position") st.setDraft({ kind: "hedge", legs: [], none: false, macro: st.draft.macro ? null : { label: "Keep the book as it is", trades: [] } });   // the position ticket's "Keep"
        else st.setDraft({ kind: "hedge", legs: [], none: !st.draft.none, macro: null });
      }
      const fq = focusOf(st.observation);
      if (k === "quote" && st.draft.kind === "quote" && fq) {
        const mid = fq.mid, big = e.shiftKey ? SKEW_BIG : SKEW_STEP;
        if (e.key === "[" || e.key === "{") st.setDraft(stepQuote(st.draft, mid, -big, 0));
        if (e.key === "]" || e.key === "}") st.setDraft(stepQuote(st.draft, mid, big, 0));
        if (e.key === "-") st.setDraft(stepQuote(st.draft, mid, 0, -2 * SKEW_STEP));
        if (e.key === "=" || e.key === "+") st.setDraft(stepQuote(st.draft, mid, 0, 2 * SKEW_STEP));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showRef, leaving, showGuide]);

  if (s.phase === "idle" || s.phase === "starting" || (s.phase === "error" && !s.sessionId)) {
    return (
      <>
        <StartPanel onStart={(l, sd) => void s.start(l, sd)} onResume={(id) => void s.resume(id)} busy={s.phase === "starting"} error={s.error} onGuide={() => setShowGuide(true)} />
        {showGuide ? <GuideSheet guides={DESK_GUIDES} onClose={closeGuide} /> : null}
      </>
    );
  }
  if (s.phase === "finished") return <Debrief onNewEpisode={s.reset} onExit={() => { s.reset(); onExit(); }} />;
  if (!view || !s.episode) return <div className="center dim">{s.error ?? "Loading…"}</div>;

  const book = latest(all, "book");
  const market = latest(all, "market");
  const conditions = latest(all, "conditions");
  const curves = curveHistory(all);
  const settled = showsResult(s.phase);
  const last = s.transcript[s.transcript.length - 1];
  const bookless = view.kind === "checkpoint" && !view.book;
  const banner = view.header.briefing || view.header.notes.length ? [view.header.briefing, ...view.header.notes].filter(Boolean).join(" ") : null;
  const bannerKey = `${view.episode.id}:${view.episode.round}:${view.kind}`;
  const draft = s.draft;

  return (
    <div className="desk">
      <TopBar episode={s.episode} round={view.episode.round} phase={s.phase} book={settled || bookless ? null : book} conditions={conditions} pnl={pnlNow(s)}
        onReference={() => setShowRef(true)} onLevels={() => setLeaving(true)} levelsLocked={s.phase === "submitting" || s.phase === "continuing"} />
      <Workflow phase={s.phase} kind={view.kind} onGuide={() => setShowGuide(true)} />
      {settled && s.pending ? (
        <ResultLayout pending={s.pending} book={book} market={market} curves={curves} transcript={s.transcript} dv01After={dv01AfterDecision(s.pending.result)} after={exposuresAfterDecision(s.pending.result)} pnlTotal={pnlNow(s)} busy={s.phase === "continuing"} onContinue={() => void s.next()} />
      ) : obs && draft && s.sessionId ? (
        <DecisionLayout obs={obs} draft={draft} sessionId={s.sessionId} phase={s.phase} locked={s.phase !== "awaiting"} market={market} curves={curves} book={book} conditions={conditions}
          banner={banner && dismissed !== bannerKey ? banner : null} error={s.error} armedSummary={s.armed?.summary ?? null} bookless={bookless}
          lastTrade={bookless && last ? rowsFromEvents(last.result.events, last.observation.episode.round) : noAdded}
          onDraft={s.setDraft} onArm={(pass) => s.arm(pass)} onDisarm={s.disarm} onCommit={() => void s.commit()} onDismissBanner={() => setDismissed(bannerKey)} />
      ) : <div className="center dim">{s.error ?? "…"}</div>}
      <Tape transcript={s.transcript} />
      {leaving ? <LeaveDialog episode={s.episode} round={view.episode.round} phase={s.phase} onStay={() => setLeaving(false)} onLeave={() => { setLeaving(false); s.leave(); }} /> : null}
      {showRef ? <Reference card={view.risk_card} onClose={() => setShowRef(false)} /> : null}
      {showGuide ? <GuideSheet guides={DESK_GUIDES} onClose={closeGuide} /> : null}
    </div>
  );
}
