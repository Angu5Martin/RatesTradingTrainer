import type { Debrief, GameList, GameState, QuoteBody, Report, StartBody } from "./types";

export class GameApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : msg; } catch { /* keep the status text */ }
    throw new GameApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

const base = "/api/mmgame";
export const gameApi = {
  list: () => call<GameList>("GET", base),
  start: (b: StartBody) => call<GameState>("POST", `${base}/start`, b),
  state: (id: string) => call<GameState>("GET", `${base}/${id}`),
  quote: (id: string, q: QuoteBody) => call<GameState>("POST", `${base}/${id}/quote`, q),
  quotes: (id: string, quotes: QuoteBody[]) => call<GameState>("POST", `${base}/${id}/quotes`, { quotes }),
  pause: (id: string, market: string, paused: boolean) => call<GameState>("POST", `${base}/${id}/pause`, { market, paused }),
  ack: (id: string, market: string) => call<GameState>("POST", `${base}/${id}/ack`, { market }),
  advance: (id: string) => call<{ report: Report; state: GameState }>("POST", `${base}/${id}/advance`),
  debrief: (id: string) => call<Debrief>("GET", `${base}/${id}/debrief`),
  abandon: (id: string) => call<{ deleted: string }>("DELETE", `${base}/${id}`),
};
export type GameApi = typeof gameApi;
