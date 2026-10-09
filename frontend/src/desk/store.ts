import { create } from "zustand";
import { ApiError, api } from "../api/client";
import type { DebriefView, DeskState, EncodedDecision, ObservationView, PendingState, StepResultView } from "../api/types";
import { type Draft, draftToDecision, initialDraft, rfqPass } from "./draft";
import { type DeskEvent, type Phase, transition } from "./machine";

export interface TranscriptEntry { observation: ObservationView; decision: EncodedDecision; result: StepResultView }

export interface DeskStore {
  phase: Phase;
  sessionId: string | null;
  observation: ObservationView | null;      // the current prompt (awaiting / armed / submitting only)
  pending: PendingState | null;             // the decision-time observation and its result (settled / continuing only)
  draft: Draft | null;
  armed: { decision: EncodedDecision; summary: string } | null;
  transcript: TranscriptEntry[];
  episode: DeskState["episode"] | null;
  error: string | null;
  debrief: DebriefView | null;
  debriefFull: DebriefView | null;
  loadingFull: boolean;

  start: (level: number, seed?: number) => Promise<void>;
  resume: (id: string) => Promise<void>;
  setDraft: (d: Draft) => void;
  arm: (pass?: boolean) => void;
  disarm: () => void;
  commit: () => Promise<void>;
  next: () => Promise<void>;
  loadDebrief: () => Promise<void>;
  /** Back to the level menu. Sends nothing: the session is left as the server holds it (resumable from the menu), and refused mid-request. */
  leave: () => boolean;
  reset: () => void;
}

const SESSION_KEY = "rates-desk.session";
const remember = (id: string | null) => { try { id ? sessionStorage.setItem(SESSION_KEY, id) : sessionStorage.removeItem(SESSION_KEY); } catch { /* storage unavailable */ } };
export const rememberedSession = (): string | null => { try { return sessionStorage.getItem(SESSION_KEY); } catch { return null; } };

const blank = {
  phase: "idle" as Phase, sessionId: null, observation: null, pending: null, draft: null, armed: null, transcript: [] as TranscriptEntry[],
  episode: null, error: null, debrief: null, debriefFull: null, loadingFull: false,
};

const message = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

export const useDesk = create<DeskStore>((set, get) => {
  /** Bumped whenever the screen is abandoned or restarted, so a slow start/resume that returns late cannot overwrite what is on screen now. */
  let epoch = 0;
  const go = (ev: DeskEvent): boolean => {
    const next = transition(get().phase, ev);
    if (next === null) return false;
    set({ phase: next });
    return true;
  };

  /** Take what the server says about the session as the truth and set the phase accordingly. */
  const adopt = (st: DeskState, ev: "STARTED" | "CONTINUED", prior: Partial<DeskStore> = {}) => {
    set({ ...prior, sessionId: st.id, episode: st.episode, error: null, pending: st.pending, observation: st.observation,
          draft: st.observation ? initialDraft(st.observation) : null });
    const target = st.phase === "awaiting" ? "AWAITING" : st.phase === "settled" ? "SETTLED" : "FINISHED";
    go(`${ev}_${target}` as DeskEvent);
  };

  return {
    ...blank,

    async start(level, seed) {
      const mine = ++epoch;
      set({ ...blank });
      go("START");
      try {
        const st = await api.start(level, seed);
        if (mine !== epoch) return;
        remember(st.id);
        adopt(st, "STARTED");
      } catch (e) { if (mine === epoch) { set({ error: message(e) }); go("FAIL"); } }
    },

    async resume(id) {
      const mine = ++epoch;
      set({ ...blank });
      go("START");
      try {
        const st = await api.state(id, true);
        if (mine !== epoch) return;
        remember(st.id);
        adopt(st, "STARTED", { transcript: st.transcript ?? [] });
      } catch (e) { if (mine === epoch) { remember(null); set({ error: message(e) }); go("FAIL"); } }
    },

    setDraft(d) {
      if (get().phase === "awaiting") set({ draft: d, error: null });
    },

    arm(pass = false) {
      const { observation, draft, phase } = get();
      if (phase !== "awaiting" || !observation || !draft) return;
      const r = pass && observation.kind === "rfq" ? rfqPass() : draftToDecision(observation, draft);
      if (!r.ok) { set({ error: r.error }); return; }
      if (go("ARM")) set({ armed: { decision: r.decision, summary: r.summary }, error: null });
    },

    disarm() {
      if (go("DISARM")) set({ armed: null });
    },

    async commit() {
      const { sessionId, armed, observation } = get();
      if (!sessionId || !armed || !observation || !go("COMMIT")) return;
      try {
        const { result, state } = await api.submit(sessionId, armed.decision);
        const entry: TranscriptEntry = { observation, decision: armed.decision, result };
        set({ transcript: [...get().transcript, entry], pending: state.pending, observation: null, armed: null });
        go("COMMITTED");
      } catch (e) {
        set({ error: message(e), armed: null });
        go("COMMIT_REFUSED");
      }
    },

    async next() {
      const { sessionId } = get();
      if (!sessionId || !go("CONTINUE")) return;
      try {
        const st = await api.next(sessionId);
        adopt(st, "CONTINUED", { pending: null });
        if (st.phase === "done") remember(null);
      } catch (e) { set({ error: message(e) }); go("FAIL"); }
    },

    async loadDebrief() {
      const { sessionId, phase } = get();
      if (!sessionId || phase !== "finished") return;
      try {
        const basic = await api.debrief(sessionId, false);
        set({ debrief: basic, loadingFull: true });
        const full = await api.debrief(sessionId, true);
        set({ debriefFull: full, loadingFull: false });
      } catch (e) { set({ error: message(e), loadingFull: false }); }
    },

    leave() {
      if (transition(get().phase, "RESET") === null) return false;
      get().reset();
      return true;
    },

    reset() {
      epoch++;
      remember(null);
      set({ ...blank });
    },
  };
});
