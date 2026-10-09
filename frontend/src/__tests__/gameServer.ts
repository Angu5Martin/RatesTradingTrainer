// A stand-in for the /api/mmgame endpoints that replays a REAL recorded game (fixtures/game_l1.json, dumped from the Python app by scripts/dump_game_fixtures.py).
// It keeps the server's rules where the UI depends on them: nothing before the start, one advance per round, the debrief only after the last round.
import type { Debrief, GameList, GameState, QuoteBody, Report } from "../game/types";

export interface GameFixture {
  list: GameList; start: GameState; quotes_sent: QuoteBody[]; quoted: GameState; steps: { report: Report; state: GameState }[]; debrief: Debrief;
}

export function gameServer(fx: GameFixture, opts: { refuseQuotes?: RegExp } = {}) {
  let i = -1;                                     // index of the last advance played
  let quoted = false;
  const log: string[] = [];
  const state = (): GameState => (i < 0 ? (quoted ? fx.quoted : fx.start) : fx.steps[i].state);
  return {
    log,
    api: {
      list: async () => fx.list,
      start: async (b: unknown) => { log.push(`start:${JSON.stringify(b)}`); i = -1; quoted = false; return fx.start; },
      state: async () => state(),
      quote: async (_id: string, q: QuoteBody) => {
        log.push(`quote:${JSON.stringify(q)}`);
        if (opts.refuseQuotes?.test(String(q.bid))) throw new Error("bid must be a multiple of the tick");
        quoted = true; return state();
      },
      quotes: async (_id: string, qs: QuoteBody[]) => { log.push(`quotes:${JSON.stringify(qs)}`); quoted = true; return state(); },
      pause: async (_id: string, market: string, paused: boolean) => { log.push(`pause:${market}:${paused}`); return state(); },
      ack: async (_id: string, market: string) => { log.push(`ack:${market}`); return state(); },
      advance: async () => {
        if (i + 1 >= fx.steps.length) throw new Error("the game is over");
        i += 1; log.push(`advance:${i + 1}`); return fx.steps[i];
      },
      debrief: async () => {
        if (state().phase !== "done") throw new Error("the debrief opens after the last market has resolved");
        log.push("debrief"); return fx.debrief;
      },
      abandon: async (id: string) => { log.push(`abandon:${id}`); return { deleted: id }; },
    },
  };
}
