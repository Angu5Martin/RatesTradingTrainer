import { create } from "zustand";
import { gameApi as realApi, type GameApi } from "./api";
import { checkDraft, draftFrom, isDirty, type Draft } from "./derive";
import type { Debrief, GameList, GameState, QuoteBody, StartBody } from "./types";

/** MARKET MAKING GAME state. The server's Game is the truth (positions, trades, what is hidden); this store holds the last state it sent, the quotes being typed
 *  (drafts, per market, only for markets the player has edited) and what is in flight. It never prices, settles or decides anything. */
export type Busy = "starting" | "quoting" | "advancing" | null;

export interface GameStore {
  id: string | null;
  state: GameState | null;
  debrief: Debrief | null;
  list: GameList | null;
  drafts: Record<string, Draft>;
  selected: string | null;
  busy: Busy;
  error: string | null;

  loadList: () => Promise<void>;
  start: (body: StartBody) => Promise<void>;
  resume: (id: string) => Promise<void>;
  select: (market: string) => void;
  edit: (market: string, patch: Partial<Draft>) => void;
  setDraft: (market: string, d: Draft) => void;
  discardDraft: (market: string) => void;
  sendQuote: (market: string) => Promise<void>;
  sendAll: () => Promise<boolean>;
  pause: (market: string, paused: boolean) => Promise<void>;
  pauseAll: (paused: boolean) => Promise<void>;
  ack: (market: string) => Promise<void>;
  advance: () => Promise<void>;
  loadDebrief: () => Promise<void>;
  abandon: (id: string) => Promise<void>;
  leave: () => void;
}

const KEY = "rates-game.id";
const remember = (id: string | null) => { try { id ? sessionStorage.setItem(KEY, id) : sessionStorage.removeItem(KEY); } catch { /* storage unavailable */ } };
export const rememberedGame = (): string | null => { try { return sessionStorage.getItem(KEY); } catch { return null; } };
const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));
const blank = { id: null, state: null, debrief: null, drafts: {} as Record<string, Draft>, selected: null, busy: null as Busy, error: null };

/** The first market the player can act on: the first that is shocked, else the first open one. */
export function defaultSelection(s: GameState): string | null {
  const live = s.markets.filter((m) => m.status !== "resolved" && m.status !== "upcoming");
  return (live.find((m) => m.status === "shocked") ?? live[0] ?? s.markets[0])?.id ?? null;
}

export function makeGameStore(api: GameApi = realApi) {
  return create<GameStore>((set, get) => {
    let epoch = 0;                         // bumped when the screen is left or restarted, so a late response cannot take it back

    const adopt = (st: GameState, keepDrafts = true) => {
      const sel = get().selected;
      const stillThere = sel && st.markets.some((m) => m.id === sel && m.status !== "upcoming");
      // a draft that now equals the live quote is no longer an edit
      const drafts = Object.fromEntries(Object.entries(keepDrafts ? get().drafts : {}).filter(([id, d]) => { const m = st.markets.find((x) => x.id === id); return m && m.status !== "resolved" && isDirty(m, d); }));
      set({ id: st.id, state: st, drafts, selected: stillThere ? sel : defaultSelection(st), busy: null, error: null });
      remember(st.phase === "done" ? null : st.id);
    };

    const run = async <T,>(kind: Busy, f: () => Promise<T>, then: (r: T) => void) => {
      const { busy, id } = get();
      if (busy || !id) return;
      const mine = epoch;
      set({ busy: kind, error: null });
      try { const r = await f(); if (mine === epoch) then(r); } catch (e) { if (mine === epoch) set({ busy: null, error: message(e) }); }
    };

    return {
      ...blank,
      list: null,

      async loadList() { try { set({ list: await api.list() }); } catch (e) { set({ error: message(e) }); } },

      async start(body) {
        const mine = ++epoch;
        set({ ...blank, busy: "starting" });
        try { const st = await api.start(body); if (mine === epoch) adopt(st, false); } catch (e) { if (mine === epoch) set({ ...blank, error: message(e) }); }
      },

      async resume(id) {
        const mine = ++epoch;
        set({ ...blank, busy: "starting" });
        try { const st = await api.state(id); if (mine === epoch) adopt(st, false); } catch { if (mine === epoch) { remember(null); set({ ...blank }); } }
      },

      select(market) { set({ selected: market }); },

      edit(market, patch) {
        const { state, drafts } = get();
        const m = state?.markets.find((x) => x.id === market);
        if (!m) return;
        set({ drafts: { ...drafts, [market]: { ...(drafts[market] ?? draftFrom(m)), ...patch } }, error: null });
      },
      setDraft(market, d) { set({ drafts: { ...get().drafts, [market]: d }, error: null }); },
      discardDraft(market) { const { [market]: _gone, ...rest } = get().drafts; set({ drafts: rest }); },

      async sendQuote(market) {
        const { state, drafts, id } = get();
        const m = state?.markets.find((x) => x.id === market);
        if (!state || !m || !id) return;
        const chk = checkDraft(m, drafts[market] ?? draftFrom(m));
        if (!chk.ok) { set({ error: `${market}: ${chk.why}` }); return; }
        await run("quoting", () => api.quote(id, chk.body), (st) => adopt(st));
      },

      /** Send every edited quote at once (all or nothing). Returns whether there is nothing left unsent. */
      async sendAll() {
        const { state, drafts, id, busy } = get();
        if (!state || !id || busy) return false;
        const bodies: QuoteBody[] = [];
        for (const m of state.markets) {
          const d = drafts[m.id];
          if (!d || !isDirty(m, d)) continue;
          const chk = checkDraft(m, d);
          if (!chk.ok) { set({ error: `${m.id}: ${chk.why}` }); return false; }
          bodies.push(chk.body);
        }
        if (!bodies.length) return true;
        let ok = false;
        await run("quoting", () => api.quotes(id, bodies), (st) => { adopt(st); ok = true; });
        return ok;
      },

      async pause(market, paused) {
        const { id } = get();
        if (id) await run("quoting", () => api.pause(id, market, paused), (st) => adopt(st));
      },

      async pauseAll(paused) {
        const { state, id } = get();
        if (!state || !id) return;
        const targets = state.markets.filter((m) => m.status !== "resolved" && m.status !== "upcoming" && (paused ? m.status !== "paused" : m.status === "paused"));
        for (const m of targets) {
          if (get().busy) break;
          await run("quoting", () => api.pause(id, m.id, paused), (st) => adopt(st));
        }
      },

      async ack(market) {
        const { id } = get();
        if (id) await run("quoting", () => api.ack(id, market), (st) => adopt(st));
      },

      /** Play the round. Edited quotes are sent first, as one all-or-nothing batch; if one is refused the round is not played. */
      async advance() {
        const { id, state, busy } = get();
        if (!id || !state || busy || state.phase === "done") return;
        if (!(await get().sendAll())) return;
        await run("advancing", () => api.advance(id), (r) => adopt(r.state));
      },

      async loadDebrief() {
        const { id, state } = get();
        if (!id || state?.phase !== "done") return;
        try { set({ debrief: await api.debrief(id) }); } catch (e) { set({ error: message(e) }); }
      },

      async abandon(id) {
        try { await api.abandon(id); } catch (e) { set({ error: message(e) }); }
        if (get().id === id) { epoch++; remember(null); set({ ...blank }); }
        await get().loadList();
      },

      leave() { epoch++; remember(null); set({ ...blank }); },
    };
  });
}

export const useGame = makeGameStore();
