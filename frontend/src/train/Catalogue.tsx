import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Catalogue as Cat, CatalogueSkill, PracticeSaved, QKind, TrainStart } from "../api/types";
import { Chip, Panel } from "../components/ui";

const DIFF = [{ v: 0, label: "All" }, { v: 1, label: "1", title: "single concept" }, { v: 2, label: "2", title: "concept and calculation" }, { v: 3, label: "3", title: "multi-step trading situation" }];
const KIND: { v: QKind | ""; label: string }[] = [{ v: "", label: "All" }, { v: "conceptual", label: "Conceptual" }, { v: "calculation", label: "Calculation" }];
const COUNTS = [5, 10, 20];

function Seg<T extends string | number>({ value, options, onChange, label }: { value: T; options: { v: T; label: string; title?: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => <button key={String(o.v)} title={o.title} className={`seg-b ${o.v === value ? "on" : ""}`} aria-pressed={o.v === value} onClick={() => onChange(o.v)}>{o.label}</button>)}
    </div>
  );
}

export function Catalogue({ busy, error, onStart }: { busy: boolean; error: string | null; onStart: (b: TrainStart) => void }) {
  const [cat, setCat] = useState<Cat["train"] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [tracks, setTracks] = useState<Set<string>>(new Set());
  const [skills, setSkills] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [difficulty, setDifficulty] = useState(0);
  const [kind, setKind] = useState<QKind | "">("");
  const [count, setCount] = useState(10);
  const [qid, setQid] = useState("");
  const [recent, setRecent] = useState<PracticeSaved[]>([]);
  useEffect(() => { api.catalogue().then((r) => setCat(r.train)).catch((e) => setLoadErr(String(e.message ?? e))); api.trainHistory().then((h) => setRecent(h.slice(0, 5))).catch(() => undefined); }, []);

  const toggle = (set: Set<string>, id: string) => { const n = new Set(set); n.has(id) ? n.delete(id) : n.add(id); return n; };
  const pickTrack = (id: string, skillIds: string[]) => { setTracks(toggle(tracks, id)); setSkills(new Set([...skills].filter((s) => !skillIds.includes(s)))); };
  const pickSkill = (s: CatalogueSkill, track: string) => { setSkills(toggle(skills, s.id)); if (tracks.has(track)) setTracks(toggle(tracks, track)); };

  const pool = useMemo(() => {
    if (!cat) return 0;
    let n = 0;
    for (const t of cat.tracks) for (const s of t.skills) {
      if ((tracks.size || skills.size) && !tracks.has(t.id) && !skills.has(s.id)) continue;
      n += s.items.filter((i) => (!difficulty || i.difficulty === difficulty) && (!kind || i.kind === kind)).length;
    }
    return n;
  }, [cat, tracks, skills, difficulty, kind]);

  const selected = tracks.size + skills.size;
  const mode = selected === 1 ? "focused" : "mixed";
  const names = cat ? [...tracks].map((t) => cat.tracks.find((x) => x.id === t)?.title).concat([...skills].map((k) => cat.tracks.flatMap((t) => t.skills).find((s) => s.id === k)?.title)) : [];
  const what = selected === 0 ? "everything" : names.join(" · ");
  const start = () => onStart({ tracks: [...tracks], skills: [...skills], difficulty: difficulty || null, kind: kind || null, count });
  const idOk = /^[\w.]+#\d+$/.test(qid.trim());

  return (
    <div className="train-cat">
      <header className="train-intro">
        <h1>Practise a skill</h1>
        <p className="dim">One question at a time, graded by the same engine as the Live Desk. Pick a track or skills, or leave everything unselected for a mix. {cat ? `${cat.sources} question sources in ${cat.tracks.length} tracks.` : ""}</p>
      </header>
      {loadErr ? <p className="neg" role="alert">Could not load the catalogue: {loadErr}</p> : null}
      <div className="train-cat-grid">
        <div className="tracks" aria-label="Tracks and skills">
          {!cat && !loadErr ? <p className="dim">loading catalogue…</p> : null}
          {cat?.tracks.map((t) => {
            const skillIds = t.skills.map((s) => s.id);
            return (
              <section className={`track ${tracks.has(t.id) ? "picked" : ""}`} key={t.id}>
                <header className="track-h">
                  <label className="pick"><input type="checkbox" checked={tracks.has(t.id)} disabled={t.sources === 0} onChange={() => pickTrack(t.id, skillIds)} aria-label={`practise the ${t.title} track`} />
                    <h2>{t.title}</h2></label>
                  <span className="dim num">{t.sources} {t.sources === 1 ? "source" : "sources"}</span>
                </header>
                <ul className="skills">
                  {t.skills.map((s) => {
                    const none = s.sources === 0;
                    return (
                      <li key={s.id} className={`skill ${skills.has(s.id) ? "picked" : ""} ${none ? "none" : ""}`}>
                        <div className="skill-row">
                          <label className="pick"><input type="checkbox" disabled={none} checked={skills.has(s.id) || tracks.has(t.id)} onChange={() => pickSkill(s, t.id)} aria-label={`practise ${s.title}`} />
                            <span className="skill-t">{s.title}</span></label>
                          <span className="skill-meta">
                            {s.planned ? <Chip title="on the roadmap, no questions yet">planned</Chip> : none ? <Chip title="practised in the Live Desk episodes">no standalone questions</Chip> : (
                              <>
                                <span className="num dim lv" title="questions at level 1, 2, 3">{[1, 2, 3].filter((d) => s.difficulties[String(d)]).map((d) => `L${d}×${s.difficulties[String(d)]}`).join(" ")}</span>
                                {s.kinds.conceptual ? <Chip title="conceptual: choose between options">{s.kinds.conceptual} concept</Chip> : null}{s.kinds.calculation ? <Chip tone="accent" title="calculation: work out a number">{s.kinds.calculation} calc</Chip> : null}
                                <button className="btn btn-sm btn-ghost" aria-expanded={open === s.id} onClick={() => setOpen(open === s.id ? null : s.id)}>{open === s.id ? "hide" : "questions"}</button>
                              </>)}
                          </span>
                        </div>
                        {open === s.id ? (
                          <ul className="items">
                            {s.items.map((i) => (
                              <li key={i.id}>
                                <span className="num id">{i.id}</span>
                                <Chip title={DIFF[i.difficulty].title}>level {i.difficulty}</Chip>
                                <Chip tone={i.kind === "calculation" ? "accent" : "neutral"}>{i.kind}</Chip>
                                {i.curated ? <Chip title="hand-written">curated</Chip> : <Chip title="numbers generated from the engine on every run">generated</Chip>}
                                <button className="btn btn-sm" disabled={busy} onClick={() => onStart({ template_id: i.id })}>Practise this one</button>
                              </li>))}
                          </ul>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
        </div>

        <aside className="builder">
          <Panel title="YOUR PRACTICE" aside={<Chip tone="accent">{mode}</Chip>}>
            <p className="what"><span className="dim">Topics: </span>{what}</p>
            <div className="field"><span className="field-l">Difficulty</span><Seg label="difficulty" value={difficulty} options={DIFF} onChange={setDifficulty} /></div>
            <div className="field"><span className="field-l">Type</span><Seg label="question type" value={kind} options={KIND} onChange={setKind} /></div>
            <div className="field"><span className="field-l">Questions</span><Seg label="number of questions" value={count} options={COUNTS.map((c) => ({ v: c, label: String(c) }))} onChange={setCount} /></div>
            <p className="dim hint">{pool} {pool === 1 ? "source matches" : "sources match"}. Generated questions get fresh numbers each time; a hand-written one appears once per session.</p>
            <button className="btn btn-primary btn-wide" disabled={busy || pool === 0 || !cat} onClick={start}>{busy ? "Starting…" : `Start ${mode} practice`}</button>
            {pool === 0 && cat ? <p className="neg hint" role="status">Nothing matches these filters.</p> : null}
            {error ? <p className="neg" role="alert">{error}</p> : null}
            <h3>Replay an exact question</h3>
            <div className="row-gap">
              <input className="in num" aria-label="question id" placeholder="swaps.dv01_pnl#4821" value={qid} onChange={(e) => setQid(e.target.value)} />
              <button className="btn" disabled={busy || !idOk} onClick={() => onStart({ ids: [qid.trim()], label: "Replay" })}>Replay</button>
            </div>
          </Panel>
          {recent.length ? (
            <Panel title="RECENT PRACTICE" aside={<span className="dim">saved locally</span>}>
              <table className="tbl">
                <tbody>{recent.map((r) => (
                  <tr key={r.id}><td className="dim num">{r.started.slice(5, 16).replace("T", " ")}</td><td>{r.label}</td>
                    <td className="r num">{r.parts_correct}/{r.parts_total}{r.ended_early ? <span className="dim"> · ended early</span> : null}</td></tr>))}</tbody>
              </table>
            </Panel>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
