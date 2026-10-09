import { create } from "zustand";
import { ApiError, api } from "../api/client";
import type { TrainStart, TrainState, TrainSummary } from "../api/types";

/** TRAIN practice state. The server's QuestionSession is the truth about where the trainee is (which part, whether its result has been given);
 *  this store holds that state, the entry being typed, and what is in flight. It never grades and never holds an answer. */
export type Busy = "starting" | "submitting" | "continuing" | "finishing" | null;

export interface TrainStore {
  sessionId: string | null;
  state: TrainState | null;
  summary: TrainSummary | null;
  draft: string;
  busy: Busy;
  error: string | null;                    // a refused entry or a failed request; never a marked answer

  start: (body: TrainStart) => Promise<void>;
  resume: (id: string) => Promise<void>;
  setDraft: (t: string) => void;
  submit: () => Promise<void>;
  skip: () => Promise<void>;
  next: () => Promise<void>;
  finish: () => Promise<void>;
  /** Back to the catalogue. An unfinished session with answers is ended first so what was answered is kept (see finish); this only clears the screen. */
  reset: () => void;
}

const KEY = "rates-train.session";
const remember = (id: string | null) => { try { id ? sessionStorage.setItem(KEY, id) : sessionStorage.removeItem(KEY); } catch { /* storage unavailable */ } };
export const rememberedPractice = (): string | null => { try { return sessionStorage.getItem(KEY); } catch { return null; } };
const message = (e: unknown): string => (e instanceof ApiError || e instanceof Error ? e.message : String(e));
const blank = { sessionId: null, state: null, summary: null, draft: "", busy: null as Busy, error: null };

export const useTrain = create<TrainStore>((set, get) => {
  let epoch = 0;                           // bumped when the screen is left or restarted, so a late response cannot take the screen back

  const adopt = async (st: TrainState, mine: number) => {
    set({ sessionId: st.id, state: st, draft: "", error: null, busy: null });
    if (st.phase === "done") {
      try { const s = await api.trainSummary(st.id); if (mine === epoch) set({ summary: s }); } catch (e) { if (mine === epoch) set({ error: message(e) }); }
      remember(null);
    }
  };

  return {
    ...blank,

    async start(body) {
      const mine = ++epoch;
      set({ ...blank, busy: "starting" });
      try {
        const st = await api.trainStart(body);
        if (mine !== epoch) return;
        remember(st.id);
        await adopt(st, mine);
      } catch (e) { if (mine === epoch) set({ ...blank, error: message(e) }); }
    },

    async resume(id) {
      const mine = ++epoch;
      set({ ...blank, busy: "starting" });
      try {
        const st = await api.trainState(id);
        if (mine !== epoch) return;
        remember(st.id);
        await adopt(st, mine);
      } catch (e) { if (mine === epoch) { remember(null); set({ ...blank }); } }
    },

    setDraft(t) {
      const { state, busy } = get();
      if (state?.phase === "answering" && !busy) set({ draft: t, error: null });
    },

    async submit() {
      const { sessionId, state, draft, busy } = get();
      if (!sessionId || state?.phase !== "answering" || busy || draft.trim() === "") return;
      const mine = epoch;
      set({ busy: "submitting", error: null });
      try {
        const r = await api.trainAnswer(sessionId, draft.trim());
        if (mine !== epoch) return;
        set({ state: r.state, busy: null });
      } catch (e) { if (mine === epoch) set({ busy: null, error: message(e) }); }          // an unreadable entry is refused: nothing was marked, the same prompt stays
    },

    async skip() {
      const { sessionId, state, busy } = get();
      if (!sessionId || state?.phase !== "answering" || busy) return;
      const mine = epoch;
      set({ busy: "submitting", error: null });
      try {
        const r = await api.trainAnswer(sessionId, "", true);
        if (mine !== epoch) return;
        set({ state: r.state, busy: null });
      } catch (e) { if (mine === epoch) set({ busy: null, error: message(e) }); }
    },

    async next() {
      const { sessionId, state, busy } = get();
      if (!sessionId || state?.phase !== "feedback" || busy) return;
      const mine = epoch;
      set({ busy: "continuing", error: null });
      try {
        const st = await api.trainNext(sessionId);
        if (mine !== epoch) return;
        await adopt(st, mine);
      } catch (e) { if (mine === epoch) set({ busy: null, error: message(e) }); }
    },

    async finish() {
      const { sessionId, state, busy } = get();
      if (!sessionId || !state || busy) return;
      const mine = epoch;
      set({ busy: "finishing", error: null });
      try {
        const s = await api.trainFinish(sessionId);
        if (mine !== epoch) return;
        remember(null);
        set({ summary: s, busy: null, state: { ...state, phase: "done", ended_early: true, question: null } });
      } catch (e) { if (mine === epoch) set({ busy: null, error: message(e) }); }
    },

    reset() {
      epoch++;
      remember(null);
      set({ ...blank });
    },
  };
});
