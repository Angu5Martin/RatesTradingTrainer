import { useState } from "react";
import { api } from "../../api/client";
import type { ObservationView, SideWord } from "../../api/types";
import { Chip, Num, Panel } from "../../components/ui";
import { evalExpr } from "../../lib/calc";
import { eur, pct } from "../../lib/format";
import { type Leg, crossCost, legDv01, productLegCost, productLegDv01 } from "../../lib/ticket";
import { type Draft, legsFromTrades } from "../draft";

type HedgeDraft = Extract<Draft, { kind: "hedge" }>;
let LEG_ID = 1;
const MAX_LEGS = 4;

/** The hedge (levels 1-4) and position (level 5) ticket: a leg builder over the swap ladder and, where the episode has them, futures and the CTD bond.
 *  Per-leg DV01 and cost are arithmetic on the screen's own numbers; macros (a share of DV01, flatten, switch, keep, target) are resolved by the engine through
 *  `parse` and come back as ordinary legs. The ticket never shows what the hedge does to the book: that is revealed after the commit. */
export function HedgeTicket({ obs, sessionId, draft, setDraft, locked }: { obs: ObservationView; sessionId: string; draft: HedgeDraft; setDraft: (d: Draft) => void; locked: boolean }) {
  const ladder = obs.market?.ladder ?? [];
  const menu = obs.hedge_menu ?? ladder.map((r) => ({ tenor: r.tenor, dv01_per_m: r.dv01_per_m, cost_bp: r.cost_bp }));
  const products = obs.market?.products ?? [];
  const isPosition = obs.kind === "position";
  const [macroTenor, setMacroTenor] = useState<number>(obs.book?.focus_tenor ?? menu[0]?.tenor ?? 5);
  const [msg, setMsg] = useState<string | null>(null);
  const [target, setTarget] = useState("");
  const byTenor = (t: number) => menu.find((m) => m.tenor === t);
  const prod = (code: string) => products.find((p) => p.code === code);
  const full = draft.legs.length >= MAX_LEGS;
  const setLegs = (legs: Leg[]) => setDraft({ ...draft, legs, none: false, macro: null });
  const addLeg = (side: SideWord, tenor = macroTenor) => { setMacroTenor(tenor); setLegs([...draft.legs, { id: LEG_ID++, side, tenor, sizeM: "" }]); };
  const addProduct = (code: string, kind: "future" | "bond", side: SideWord) => setLegs([...draft.legs, { id: LEG_ID++, side, tenor: 0, sizeM: "", product: { code, kind } }]);
  const midOf = (t: number) => obs.market?.curve.find((c) => c.tenor === t)?.mid ?? ladder.find((r) => r.tenor === t)?.mid ?? null;
  const update = (id: number, patch: Partial<Leg>) => setLegs(draft.legs.map((l) => (l.id === id ? { ...l, ...patch } : l)));

  /** Ask the engine what typed text means; show the resolved trades as legs (or the engine's own empty decision for keep). */
  async function resolve(text: string, emptyMsg = "Nothing to trade at that size.") {
    setMsg(null);
    try {
      const r = await api.parse(sessionId, text);
      if (!r.ok) { setMsg(r.error); return; }
      const d = r.decision;
      if (d.type !== "hedge") return;
      if (d.trades.length === 0) {
        if (text === "keep") { setDraft({ kind: "hedge", legs: [], none: false, macro: { label: d.label, trades: [] } }); return; }
        setMsg(emptyMsg);
        return;
      }
      setDraft({ kind: "hedge", legs: legsFromTrades(d.trades, LEG_ID), none: false, macro: null });
      LEG_ID += d.trades.length;
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  }
  const noTrade = () => setDraft({ kind: "hedge", legs: [], none: !draft.none, macro: null });
  const keeping = draft.macro !== null && draft.legs.length === 0;
  const dv01 = obs.book?.dv01 ?? 0;
  const targetNum = target.trim() ? evalExpr(target) : null;
  const stepTarget = (d: number) => setTarget(String(Math.round(((targetNum ?? dv01) + d) / 1000) * 1000));

  return (
    <Panel title={isPosition ? "POSITION" : "HEDGE"} aside={<span className="dim">{products.length ? "swaps at the interdealer street; products per unit" : "interdealer: mid ± half the bid/offer"}</span>} className="ticket grow">
      {isPosition ? <p className="prompt-s dim">Decide the risk you want to run into the next step: keep it, cut it, or take more. Inventory is not the only reason.</p> : null}
      <table className={`tbl menu ${products.length || menu.length > 3 ? "compact" : ""}`}>
        <thead><tr><th>Swap</th><th className="r">Mid</th><th className="r">DV01 / €1m</th><th className="r">Cost to cross</th><th className="r">€100m: DV01</th><th className="r">€100m: cost</th><th /></tr></thead>
        <tbody>
          {menu.map((m) => (
            <tr key={m.tenor} className={m.tenor === macroTenor ? "row-sel" : ""} onClick={() => !locked && setMacroTenor(m.tenor)}>
              <td><strong>{m.tenor}Y</strong></td><td className="r">{midOf(m.tenor) === null ? "–" : pct(midOf(m.tenor)!, 3)}</td>
              <td className="r">{eur(m.dv01_per_m, false)}</td><td className="r">{m.cost_bp.toFixed(2)}bp</td>
              <td className="r">{eur(100 * m.dv01_per_m, false)}</td><td className="r">{eur(crossCost(100 * m.dv01_per_m, m.cost_bp), false)}</td>
              <td className="r nowrap"><button className="btn btn-sm" disabled={locked || full} onClick={(e) => { e.stopPropagation(); addLeg("pay", m.tenor); }}>Pay</button> <button className="btn btn-sm" disabled={locked || full} onClick={(e) => { e.stopPropagation(); addLeg("receive", m.tenor); }}>Rec</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {products.length ? (
        <table className="tbl menu compact products-menu">
          <thead><tr><th>Product</th><th className="r">DV01 / unit</th><th className="r">Cost / unit</th><th /></tr></thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.code}>
                <td><strong>{p.code}</strong> <span className="dim">{p.kind === "future" ? "per contract" : "per €1m face"}</span></td>
                <td className="r">{eur(p.dv01_per_unit, false)}</td><td className="r">{eur(p.cost_per_unit, false)}</td>
                <td className="r nowrap"><button className="btn btn-sm" disabled={locked || full} onClick={() => addProduct(p.code, p.kind, "pay")}>Sell</button> <button className="btn btn-sm" disabled={locked || full} onClick={() => addProduct(p.code, p.kind, "receive")}>Buy</button></td>
              </tr>))}
          </tbody>
        </table>
      ) : null}
      <div className={`legs legs-zone ${draft.legs.length || draft.none || keeping ? "" : "empty"}`}>
        {draft.legs.map((l) => {
          const m = byTenor(l.tenor);
          const n = Number(l.sizeM.replace(",", "."));
          const p = l.product ? prod(l.product.code) : undefined;
          const dv = l.product ? (p && n > 0 ? productLegDv01(l, p.dv01_per_unit) : null) : m && n > 0 ? legDv01(l.side, n * 1e6, m.dv01_per_m) : null;
          const cost = l.product ? (p && n > 0 ? productLegCost(l, p.cost_per_unit) : null) : dv !== null && m ? crossCost(dv, m.cost_bp) : null;
          return (
            <div className="leg" key={l.id}>
              <div className="seg" role="group" aria-label="side">
                <button className={`seg-b ${l.side === "pay" ? "on" : ""}`} disabled={locked} onClick={() => update(l.id, { side: "pay" })}>{l.product ? "Sell" : "Pay"}</button>
                <button className={`seg-b ${l.side === "receive" ? "on" : ""}`} disabled={locked} onClick={() => update(l.id, { side: "receive" })}>{l.product ? "Buy" : "Receive"}</button>
              </div>
              {l.product ? <strong className="leg-code">{l.product.code}</strong> : (
                <select className="in" value={l.tenor} disabled={locked} aria-label="tenor" onChange={(e) => update(l.id, { tenor: Number(e.target.value) })}>
                  {menu.map((mm) => <option key={mm.tenor} value={mm.tenor}>{mm.tenor}Y</option>)}
                </select>)}
              <input className="in num" inputMode="decimal" placeholder="size" value={l.sizeM} disabled={locked} aria-label={l.product?.kind === "future" ? "size, contracts" : l.product ? "size, EUR millions face" : "size, EUR millions"} onChange={(e) => update(l.id, { sizeM: e.target.value })} />
              <span className="dim">{l.product?.kind === "future" ? "contracts" : "€m"}</span>
              <span className="leg-info">{dv !== null && cost !== null ? <>leg DV01 <Num v={dv} /> <span className="dim">· indicative cost {eur(cost, false)}</span></> : <span className="dim">enter a size</span>}</span>
              <button className="btn btn-sm btn-ghost" disabled={locked} onClick={() => setLegs(draft.legs.filter((x) => x.id !== l.id))} aria-label="remove leg">✕</button>
            </div>
          );
        })}
        {draft.legs.length === 0 && !draft.none && !keeping ? <p className="dim legs-empty">Your {isPosition ? "trades" : "hedge legs"} appear here.<br />Add a leg from the tables, use a helper below, or choose {isPosition ? "Keep" : "No trade"}.</p> : null}
        {draft.none ? <p className="hint"><Chip tone="accent">No trade</Chip> you warehouse the book.</p> : null}
        {keeping ? <p className="hint"><Chip tone="accent">{draft.macro!.label}</Chip> no trade.</p> : null}
      </div>
      <div className="macro-row">
        <button className="btn btn-sm" disabled={locked || full} onClick={() => addLeg("pay")}>+ Pay leg</button>
        <button className="btn btn-sm" disabled={locked || full} onClick={() => addLeg("receive")}>+ Receive leg</button>
        <span className="sep" />
        <span className="dim">hedge as % of DV01 in {macroTenor}Y</span>
        {[25, 50, 100].map((p) => <button key={p} className="btn btn-sm" disabled={locked} onClick={() => void resolve(`${p}% ${macroTenor}y`, "Nothing to hedge at that size.")}>{p}%</button>)}
        {obs.input.can_flatten ? <button className="btn btn-sm" disabled={locked} title="level, slope and curvature: the engine chooses the legs" onClick={() => void resolve("flatten", "Nothing to flatten.")}>Flatten</button> : null}
        {obs.input.can_switch ? <button className="btn btn-sm" disabled={locked} title="close the futures and bond hedges and replace them with swaps" onClick={() => void resolve("switch", "Nothing to switch.")}>Switch to swaps</button> : null}
        {isPosition ? <button className={`btn btn-sm btn-notrade ${keeping ? "btn-on" : ""}`} disabled={locked} onClick={() => void resolve("keep")}>Keep <span className="kbd-inline">N</span></button>
          : <button className={`btn btn-sm btn-notrade ${draft.none ? "btn-on" : ""}`} disabled={locked} onClick={noTrade}>No trade <span className="kbd-inline">N</span></button>}
      </div>
      {obs.input.can_target ? (
        <div className="macro-row target-row">
          <span className="dim">run a DV01 of</span>
          <button className="btn btn-sm" disabled={locked} onClick={() => stepTarget(-50_000)} aria-label="target 50k lower">−50k</button>
          <input className="in num target-in" inputMode="decimal" placeholder={`now ${Math.round(dv01 / 1000)}k`} value={target} disabled={locked} aria-label="target DV01" onChange={(e) => setTarget(e.target.value)} />
          <button className="btn btn-sm" disabled={locked} onClick={() => stepTarget(50_000)} aria-label="target 50k higher">+50k</button>
          <button className="btn btn-sm" disabled={locked || targetNum === null} onClick={() => void resolve(`target ${targetNum}`, "That is where you already are.")}>Set</button>
          <button className="btn btn-sm" disabled={locked} onClick={() => void resolve("flat", "That is where you already are.")}>Flat</button>
          <span className="dim hint">{obs.book ? `limit ${eur(obs.book.limit_dv01, false)}` : ""} · done in the {obs.book?.focus_tenor}Y</span>
        </div>
      ) : null}
      {msg ? <p className="neg hint" role="alert">{msg}</p> : null}
    </Panel>
  );
}
