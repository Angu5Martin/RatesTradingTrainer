import type { Catalogue, DebriefView, DeskState, EncodedDecision, LiveSession, PartResult, PendingState, PracticeSaved, SavedSession, StepResultView, TrainStart, TrainState, TrainSummary } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch { /* keep status text */ }
    throw new ApiError(r.status, String(msg));
  }
  return r.json() as Promise<T>;
}

export const api = {
  catalogue: () => call<Catalogue>("GET", "/api/catalogue"),
  live: () => call<LiveSession[]>("GET", "/api/desk"),
  discard: (id: string) => call<{ deleted: string }>("DELETE", `/api/desk/${id}`),
  discardAll: () => call<{ deleted: string[] }>("DELETE", "/api/desk"),
  start: (level: number, seed?: number) => call<DeskState>("POST", "/api/desk/start", { level, seed: seed ?? null }),
  state: (id: string, transcript = false) => call<DeskState & { transcript?: PendingState[] }>("GET", `/api/desk/${id}?transcript=${transcript}`),
  parse: (id: string, text: string) => call<{ ok: true; decision: EncodedDecision } | { ok: false; error: string }>("POST", `/api/desk/${id}/parse`, { text }),
  submit: (id: string, decision: EncodedDecision) => call<{ result: StepResultView; state: DeskState }>("POST", `/api/desk/${id}/submit`, { decision }),
  next: (id: string) => call<DeskState>("POST", `/api/desk/${id}/continue`),
  debrief: (id: string, compare: boolean) => call<DebriefView>("GET", `/api/desk/${id}/debrief?compare=${compare}`),
  trainStart: (b: TrainStart) => call<TrainState>("POST", "/api/train/start", b),
  trainState: (id: string) => call<TrainState>("GET", `/api/train/${id}`),
  trainCheck: (id: string, text: string) => call<{ ok: true; read_as: string } | { ok: false; error: string }>("POST", `/api/train/${id}/check`, { text }),
  trainAnswer: (id: string, text: string, skip = false) => call<{ result: PartResult; state: TrainState }>("POST", `/api/train/${id}/answer`, { text, skip }),
  trainNext: (id: string) => call<TrainState>("POST", `/api/train/${id}/continue`),
  trainFinish: (id: string) => call<TrainSummary>("POST", `/api/train/${id}/finish`),
  trainSummary: (id: string) => call<TrainSummary>("GET", `/api/train/${id}/summary`),
  trainHistory: () => call<PracticeSaved[]>("GET", "/api/train/history"),
  sessions: () => call<SavedSession[]>("GET", "/api/review/sessions"),
};
