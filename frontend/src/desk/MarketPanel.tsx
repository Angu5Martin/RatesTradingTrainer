import type { FocusQuote, Market, ProductLine } from "../api/types";
import { CurveChart } from "../components/charts";
import { Num, Panel } from "../components/ui";
import { bp, eur, pct } from "../lib/format";

type Pt = { tenor: number; mid: number };

function Street({ f }: { f: FocusQuote }) {
  return (
    <Panel title={`STREET · ${f.tenor}Y`} aside={<span className="dim">{((f.offer - f.bid) * 1e4).toFixed(1)}bp wide · DV01 {eur(f.dv01_per_m, false)}/€1m</span>} className="street">
      <div className="street-grid">
        <div className="st-cell"><span className="st-k bid">BID <span className="dim">you pay fixed</span></span><span className="st-v bid">{pct(f.bid)}</span></div>
        <div className="st-cell st-mid"><span className="st-k">MID <span className="dim">fair value</span></span><span className="st-v">{pct(f.mid)}</span></div>
        <div className="st-cell"><span className="st-k offer">OFFER <span className="dim">you receive</span></span><span className="st-v offer">{pct(f.offer)}</span></div>
      </div>
    </Panel>
  );
}

/** Futures and the CTD bond as the desk screen shows them: price (or yield and ASW), DV01 and cost of crossing per unit, and what the line says about itself. */
function ProductLines({ products }: { products: ProductLine[] }) {
  return (
    <Panel title="FUTURES AND BOND" aside={<span className="dim">DV01 and cost per unit</span>} className="products">
      <table className="tbl products-t">
        <tbody>
          {products.map((p) => (
            <tr key={p.code}>
              <td>
                <strong>{p.code}</strong>{" "}
                <span className="num">{p.kind === "future" ? (p.price ?? 0).toFixed(2) : `${(p.clean ?? 0).toFixed(2)} · ${((p.yield ?? 0) * 100).toFixed(2)}% · ASW ${bp(p.asw_bp ?? 0, 1)}`}</span>
                <div className="dim prod-info">{p.info}</div>
              </td>
              <td className="r num nw">DV01 {eur(p.dv01_per_unit, false)}<div className="dim">cost {eur(p.cost_per_unit, false)} per {p.kind === "future" ? "contract" : "€1m face"}</div></td>
            </tr>))}
        </tbody>
      </table>
    </Panel>
  );
}

/** The market, as stacked areas that share the column's height: the street quote in the tenor being asked about (large), the curve (takes what is left), and a
 *  tenor table with the change since the previous step and since the open. On a ladder (levels 3-5) the table also carries the street and the cost to cross each
 *  tenor, and any futures and bond lines follow. */
export function MarketPanel({ market, curves, focusTenor }: { market: Market; curves: Pt[][]; focusTenor?: number | null }) {
  const now = curves[curves.length - 1] ?? [];
  const prev = curves.length > 1 ? curves[curves.length - 2] : null;
  const open = curves.length > 2 ? curves[0] : null;
  const ladder = market.mode === "ladder";
  const row = ladder ? market.ladder.find((r) => r.tenor === focusTenor) : undefined;
  const f: FocusQuote | null = market.focus ?? (row ? { tenor: row.tenor, mid: row.mid, bid: row.bid, offer: row.offer, dv01_per_m: row.dv01_per_m } : null);
  const hl = f?.tenor ?? focusTenor ?? null;
  const d = (a: Pt[] | null, i: number) => (a && a.length === now.length ? (now[i].mid - a[i].mid) * 1e4 : null);
  return (
    <>
      {f ? <Street f={f} /> : null}
      <Panel title="CURVE" aside={<span className="legend"><span className="lg lg-now" />now <span className="lg lg-ghost" />previous <span className="lg lg-open" />open</span>} className="grow curve">
        <CurveChart curve={now} ghost={prev} open={open} />
      </Panel>
      <Panel title={ladder ? "SWAP LADDER" : "TENORS"} aside={<span className="dim">6M Euribor swaps{ladder ? " · interdealer" : ""}</span>}>
        <table className="tbl tenors">
          <thead><tr><th>Tenor</th><th className="r">Mid</th>{ladder ? <th className="r">Cost to cross</th> : null}<th className="r">{ladder ? "Δprev" : "Δ previous"}</th>{ladder ? null : <th className="r">Δ open</th>}</tr></thead>
          <tbody>{now.map((p, i) => {
            const lr = ladder ? market.ladder.find((r) => r.tenor === p.tenor) : undefined;
            return (
              <tr key={p.tenor} className={p.tenor === hl ? "row-sel" : ""}>
                <td>{p.tenor}Y</td><td className="r">{pct(p.mid, 3)}</td>
                {ladder ? <td className="r">{lr ? `${lr.cost_bp.toFixed(2)}bp` : "–"}</td> : null}
                <td className="r">{d(prev, i) === null ? <span className="dim">–</span> : <Num v={d(prev, i)!} f={(x) => bp(x, 1)} eps={0.05} />}</td>
                {ladder ? null : <td className="r">{d(open, i) === null ? <span className="dim">–</span> : <Num v={d(open, i)!} f={(x) => bp(x, 1)} eps={0.05} />}</td>}
              </tr>);
          })}</tbody>
        </table>
      </Panel>
      {market.products.length ? <ProductLines products={market.products} /> : null}
    </>
  );
}
