import { useEffect, useState } from "react";
import { Chip, Num, Panel } from "../components/ui";
import { credits } from "./derive";
import { useGame } from "./store";
import type { GameSummary, LevelInfo } from "./types";

const MIX_LABEL: Record<string, string> = { mixed: "Mixed", probability: "Probability only", world: "World knowledge only" };

/** The lobby: pick a level, customise the table, start; or pick up an unfinished game. */
export function Setup({ onGuide }: { onGuide?: () => void }) {
  const s = useGame();
  const levels = s.list?.levels ?? [];
  const [level, setLevel] = useState(1);
  const [markets, setMarkets] = useState<number | null>(null);
  const [mix, setMix] = useState("mixed");
  const [seed, setSeed] = useState("");
  const [coach, setCoach] = useState<boolean | null>(null);
  useEffect(() => { void s.loadList(); }, []);                                    // eslint-disable-line react-hooks/exhaustive-deps
  const lv = levels.find((l) => l.level === level);
  const n = markets !== null && lv ? Math.min(Math.max(markets, lv.markets[0]), lv.markets[2]) : lv?.markets[1] ?? 3;
  const seedOk = seed.trim() === "" || /^\d{1,9}$/.test(seed.trim());
  const unfinished = (s.list?.games ?? []).filter((g) => !g.done);
  const finished = (s.list?.games ?? []).filter((g) => g.done);
  const go = () => void s.start({ level, markets: n, mix, seed: seed.trim() === "" ? null : Number(seed), coach: coach });

  return (
    <div className="gm-setup">
      <header className="gm-intro">
        <h1>MARKET MAKING GAME</h1>
        <p className="dim">Make markets against bots on several questions at once. Each market asks for a number: a probability puzzle (dice, coins, cards) or a fact about the world. You post a bid and an offer;
          bots trade against them; the market settles on the verified answer. Spread, skew and size are yours to manage across the whole table. Turn-based: nothing moves until you play the round.</p>
        {onGuide ? <div className="row-gap"><button className="btn btn-sm" onClick={onGuide}>How to play well: the guides</button><span className="dim"> overview · world markets · probability markets</span></div> : null}
      </header>
      {s.error ? <div className="alert" role="alert">{s.error}</div> : null}
      <div className="gm-levels" role="radiogroup" aria-label="difficulty level">
        {levels.map((l) => <LevelCard key={l.level} l={l} on={l.level === level} onPick={() => { setLevel(l.level); setMarkets(null); setCoach(null); }} />)}
      </div>
      {lv ? (
        <Panel title="THIS TABLE" aside={<span className="dim">{lv.name}</span>}>
          <div className="gm-opts">
            <label className="field"><span className="field-l">Markets at the table: <strong className="num">{n}</strong></span>
              <input type="range" aria-label="number of markets" min={lv.markets[0]} max={lv.markets[2]} value={n} onChange={(e) => setMarkets(Number(e.target.value))} /></label>
            <div className="field"><span className="field-l">Question mix</span>
              <div className="seg" role="radiogroup" aria-label="question mix">
                {(s.list?.mixes ?? ["mixed"]).map((m) => <button key={m} role="radio" aria-checked={mix === m} className={`seg-b ${mix === m ? "on" : ""}`} onClick={() => setMix(m)}>{MIX_LABEL[m] ?? m}</button>)}
              </div></div>
            <label className="field"><span className="field-l">Seed (optional: the same seed and choices give the same game)</span>
              <input className="in gm-seed" aria-label="seed" inputMode="numeric" placeholder="random" value={seed} onChange={(e) => setSeed(e.target.value)} aria-invalid={!seedOk} /></label>
            <label className="pick"><input type="checkbox" aria-label="coach" checked={coach ?? lv.coach} onChange={(e) => setCoach(e.target.checked)} />
              <span>Coach: show the edge of each trade against fair value as it happens (probability markets)</span></label>
          </div>
          <button className="btn btn-primary btn-wide" disabled={s.busy === "starting" || !seedOk} onClick={go}>Deal the table</button>
        </Panel>
      ) : <p className="dim">loading…</p>}
      {unfinished.length ? (
        <Panel title="IN PROGRESS" aside={<span className="dim">saved after every action</span>}>
          <ul className="gm-games">{unfinished.map((g) => <GameRow key={g.id} g={g} onOpen={() => void s.resume(g.id)} onDrop={() => void s.abandon(g.id)} />)}</ul>
        </Panel>
      ) : null}
      {finished.length ? (
        <Panel title="FINISHED" aside={<span className="dim">kept; open to read the debrief</span>}>
          <ul className="gm-games">{finished.slice(0, 8).map((g) => <GameRow key={g.id} g={g} onOpen={() => void s.resume(g.id)} />)}</ul>
        </Panel>
      ) : null}
    </div>
  );
}

function LevelCard({ l, on, onPick }: { l: LevelInfo; on: boolean; onPick: () => void }) {
  return (
    <button role="radio" aria-checked={on} className={`gm-level ${on ? "on" : ""}`} onClick={onPick}>
      <span className="gm-level-h"><Chip tone={on ? "accent" : "neutral"}>LEVEL {l.level}</Chip><strong>{l.name}</strong></span>
      <span className="dim gm-level-b">{l.blurb}</span>
      <span className="gm-level-f num">{l.markets[0]}–{l.markets[2]} markets · {l.rounds} rounds · limit ±{l.limit} lots · size ≤{l.size_max}{l.risk_budget ? ` · risk budget ${l.risk_budget}` : ""}</span>
    </button>
  );
}

function GameRow({ g, onOpen, onDrop }: { g: GameSummary; onOpen: () => void; onDrop?: () => void }) {
  return (
    <li className="gm-game">
      <span>L{g.level} {g.level_name}</span>
      <span className="dim num">{g.started.replace("T", " ")}</span>
      <span className="dim">{g.markets} markets · round {g.round}/{g.rounds}</span>
      {g.done ? <Num v={g.pnl} f={credits} /> : <Chip tone="warn">unfinished</Chip>}
      <span className="gm-game-a"><button className="btn btn-sm" onClick={onOpen}>{g.done ? "Debrief" : "Resume"}</button>
        {onDrop ? <button className="btn btn-sm btn-ghost" onClick={onDrop} aria-label={`abandon game ${g.id.slice(0, 6)}`}>Abandon</button> : null}</span>
    </li>
  );
}
