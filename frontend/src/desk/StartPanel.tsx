import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { LiveSession, SavedSession } from "../api/types";
import { Chip, Panel } from "../components/ui";
import { eur } from "../lib/format";

const LEVELS = [
  { level: 1, title: "One client, one trade", text: "Quote a two-way market, see whether the client deals, decide how much risk to keep, watch the market move.", ready: true },
  { level: 2, title: "Inventory loop", text: "Five client requests carrying your book and P&L: skew your price to your inventory, hedge or warehouse.", ready: true },
  { level: 3, title: "The curve book", text: "Price by whole-book risk across 2/5/10/30Y; level, slope and curvature.", ready: true },
  { level: 4, title: "Products and the overnight", text: "Hedge with futures and bonds late in the day, carry risk overnight.", ready: true },
  { level: 5, title: "Information and views", text: "Named clients, a research view, a data release, a limit cut.", ready: true },
] as const;

export function StartPanel(p: { onStart: (level: number, seed?: number) => void; onResume: (id: string) => void; busy: boolean; error: string | null }) {
  const [seed, setSeed] = useState("");
  const [live, setLive] = useState<LiveSession[]>([]);
  const [confirm, setConfirm] = useState<string | null>(null);                       // a session id, or "all", awaiting a second click
  const [working, setWorking] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [recent, setRecent] = useState<SavedSession[]>([]);
  const refresh = () => api.live().then(setLive).catch(() => undefined);
  useEffect(() => { void refresh(); api.sessions().then((r) => setRecent(r.slice(0, 5))).catch(() => undefined); }, []);
  const discard = async (target: LiveSession | "all") => {
    setWorking(true);
    try {
      if (target === "all") { const r = await api.discardAll(); setNote({ ok: true, text: `Deleted ${r.deleted.length} unfinished session${r.deleted.length === 1 ? "" : "s"}.` }); }
      else { await api.discard(target.id); setNote({ ok: true, text: `Deleted the L${target.episode.level} session ${target.id.slice(0, 6)}.` }); }
    } catch (e) {
      setNote({ ok: false, text: `Could not delete: ${e instanceof ApiError || e instanceof Error ? e.message : String(e)}` });
    } finally { setConfirm(null); setWorking(false); await refresh(); }              // the list always reflects what the server now holds
  };
  const seedNum = seed.trim() === "" ? undefined : Number(seed);
  const seedBad = seedNum !== undefined && !Number.isInteger(seedNum);
  return (
    <div className="start">
      <Panel title="LIVE DESK" aside={<span className="dim">choose a level</span>}>
        <table className="tbl levels">
          <tbody>
            {LEVELS.map((l) => (
              <tr key={l.level} className={l.ready ? "" : "off"}>
                <td className="lv">L{l.level}</td>
                <td><strong>{l.title}</strong><div className="dim">{l.text}</div></td>
                <td className="r">{l.ready ? <button className="btn btn-primary btn-sm" disabled={p.busy || seedBad} onClick={() => p.onStart(l.level, seedNum)}>Start</button> : <Chip>not in this build</Chip>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="seed-row"><label className="dim" htmlFor="seed">Seed (optional, replays the same clients and market)</label>
          <input id="seed" className="in num" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="random" aria-invalid={seedBad} /></div>
        {p.error ? <p className="neg">{p.error}</p> : null}
      </Panel>
      {live.length ? (
        <Panel title="IN PROGRESS" aside={<span className="dim">unfinished · kept on this server until it restarts</span>}>
          <table className="tbl sessions">
            <thead><tr><th>Level</th><th>Session</th><th>Started</th><th>Where it stands</th><th /></tr></thead>
            <tbody>{live.map((s) => (
              <tr key={s.id}>
                <td><strong>L{s.episode.level}</strong> <span className="dim">{s.episode.title.replace(/^Level \d: /, "")}</span></td>
                <td className="num dim">{s.id.slice(0, 6)}</td>
                <td className="num dim">{s.started.slice(5, 16).replace("T", " ")}</td>
                <td>round {Math.min(s.episode.round + 1, s.episode.rounds)}/{s.episode.rounds} · {s.phase === "settled" ? "result waiting" : "awaiting decision"}
                  {s.in_history ? <span className="dim"> · already in history</span> : null}</td>
                <td className="r nowrap">
                  {confirm === s.id ? (
                    <span className="confirm-inline" role="group" aria-label={`delete session ${s.id.slice(0, 6)}?`}>
                      <span className="neg">Delete for good?</span>{" "}
                      <button className="btn btn-sm btn-danger" disabled={working} onClick={() => void discard(s)}>Delete</button>{" "}
                      <button className="btn btn-sm btn-ghost" disabled={working} onClick={() => setConfirm(null)}>Cancel</button>
                    </span>
                  ) : (
                    <><button className="btn btn-sm" onClick={() => p.onResume(s.id)}>Resume</button>{" "}
                      <button className="btn btn-sm btn-ghost" disabled={working} aria-label={`delete session ${s.id.slice(0, 6)}`} onClick={() => { setNote(null); setConfirm(s.id); }}>Delete</button></>
                  )}
                </td>
              </tr>))}</tbody>
          </table>
          {live.length > 1 ? (
            <div className="sessions-foot">
              {confirm === "all" ? (
                <span className="confirm-inline" role="group" aria-label="delete all unfinished sessions?"><span className="neg">Delete all {live.length} unfinished sessions for good?</span>{" "}
                  <button className="btn btn-sm btn-danger" disabled={working} onClick={() => void discard("all")}>Delete all</button>{" "}
                  <button className="btn btn-sm btn-ghost" disabled={working} onClick={() => setConfirm(null)}>Cancel</button></span>
              ) : <button className="btn btn-sm btn-ghost" disabled={working} onClick={() => { setNote(null); setConfirm("all"); }}>Delete all unfinished…</button>}
              <span className="dim"> Finished episodes are kept for Review and are not affected.</span>
            </div>
          ) : null}
        </Panel>
      ) : null}
      {note ? <p className={note.ok ? "pos" : "neg"} role={note.ok ? "status" : "alert"}>{note.text}</p> : null}
      {recent.length ? (
        <Panel title="RECENT" aside={<span className="dim">saved locally</span>}>
          <table className="tbl"><tbody>{recent.map((s) => (
            <tr key={s.id}><td>L{s.level}</td><td className="dim">{s.saved.slice(0, 8)}</td><td>{s.ratings.sound} sound · {s.ratings.defensible} def · {s.ratings.poor + s.ratings.error} poor/err</td><td className="r num">{eur(s.pnl)}</td></tr>))}</tbody></table>
        </Panel>
      ) : null}
    </div>
  );
}
