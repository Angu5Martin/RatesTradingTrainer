import type { RiskCard } from "../api/types";

/** Conventions and the training assumptions, once, on demand: the definitions that used to repeat on every screen. */
export function Reference({ card, onClose }: { card: RiskCard | null; onClose: () => void }) {
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label="Reference" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <header className="sheet-h"><h2>REFERENCE</h2><button className="btn btn-ghost" onClick={onClose}>Close <span className="kbd-inline">Esc</span></button></header>
        <div className="sheet-b">
          <h3>Conventions</h3>
          <ul className="plain">
            <li><strong>DV01</strong> is the P&amp;L for a 1bp <em>fall</em> in rates. Receiving fixed is long duration (+); paying fixed is short (−).</li>
            <li><strong>Bid</strong>: you pay fixed. <strong>Offer</strong>: you receive fixed. A client who <em>pays</em> fixed deals at your offer.</li>
            <li><strong>Slope</strong> exposure is the P&amp;L for a 1bp <em>flattening</em> of a 2s30s twist about the 10Y. <strong>Curvature</strong> is the P&amp;L for a 1bp fall of the belly (5Y) against the wings.</li>
            <li>Spread exposures (when present): swap spread per bp of ASW <em>tightening</em>; futures basis per tick of futures <em>richening</em>.</li>
          </ul>
          {card ? (
            <>
              <h3>Training assumptions</h3>
              <p className="dim">{card.title}. Today&apos;s volatility is ×{card.regime_vol} of normal; a step&apos;s move scales with the square root of its length in days.</p>
              <table className="tbl">
                <thead><tr><th>Factor</th><th className="r">Normal daily vol</th><th className="r">2Y</th><th className="r">5Y</th><th className="r">10Y</th><th className="r">30Y</th></tr></thead>
                <tbody>
                  {card.factors.map((f) => (
                    <tr key={f.name}><td>{f.label}</td><td className="r num">{f.normal_daily_vol}{f.vol_unit.startsWith(" ") ? f.vol_unit : f.vol_unit}</td>
                      {[2, 5, 10, 30].map((t) => <td key={t} className="r num">{f.loadings ? (f.loadings.find((l) => l.tenor === t)?.bp_per_unit ?? 0).toFixed(3).replace(/\.?0+$/, "") : "–"}</td>)}</tr>
                  ))}
                </tbody>
              </table>
              <p className="hint dim">Loadings: bp move of each par rate for +1 of the factor. These are the exercise&apos;s model, not market estimates.</p>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
