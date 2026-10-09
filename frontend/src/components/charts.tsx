// Small hand-built SVG charts. They draw numbers the engine produced; they compute nothing but axis positions and differences of public values.
import { Fragment, useRef } from "react";
import { useSize } from "../hooks/useSize";
import { bp, eur, pct } from "../lib/format";

type Pt = { tenor: number; mid: number };

export function CurveChart({ curve, ghost, open }: { curve: Pt[]; ghost?: Pt[] | null; open?: Pt[] | null }) {
  const box = useRef<HTMLDivElement>(null);
  const { w: W, h: H } = useSize(box, { w: 300, h: 180 });
  const L = 44, R = 16, T = 14, B = 26;
  const series = [curve, ghost ?? [], open ?? []].filter((s) => s.length);
  const ys = series.flat().map((p) => p.mid * 100);
  let lo = Math.min(...ys), hi = Math.max(...ys);
  if (hi - lo < 0.04) { const c = (hi + lo) / 2; lo = c - 0.02; hi = c + 0.02; }
  const pad = (hi - lo) * 0.2; lo -= pad; hi += pad;
  const x = (i: number) => L + (i * (W - L - R)) / Math.max(1, curve.length - 1);
  const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B);
  const path = (s: Pt[]) => s.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.mid * 100).toFixed(1)}`).join(" ");
  const ticks = [lo + pad, (lo + hi) / 2, hi - pad];
  return (
    <div className="chart-box" ref={box}>
      <svg className="chart" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="EUR swap curve">
        {ticks.map((t, i) => (<Fragment key={i}><line className="grid" x1={L} x2={W - R} y1={y(t)} y2={y(t)} /><text className="axis" x={L - 6} y={y(t) + 3} textAnchor="end">{t.toFixed(2)}%</text></Fragment>))}
        {curve.map((p, i) => (<line key={`v${p.tenor}`} className="grid" x1={x(i)} x2={x(i)} y1={T} y2={H - B} />))}
        {open && open.length === curve.length ? <path className="curve-open" d={path(open)} /> : null}
        {ghost && ghost.length === curve.length ? <path className="curve-ghost" d={path(ghost)} /> : null}
        <path className="curve-now" d={path(curve)} />
        {curve.map((p, i) => (<Fragment key={p.tenor}><circle className="curve-pt" cx={x(i)} cy={y(p.mid * 100)} r={3.2} /><text className="axis axis-t" x={x(i)} y={H - 8} textAnchor="middle">{p.tenor}Y</text></Fragment>))}
      </svg>
    </div>
  );
}

/** The change in each tenor since the previous observation, in bp: steepening, flattening or parallel reads straight off the row. */
export function CurveDelta({ curve, prev }: { curve: Pt[]; prev: Pt[] | null }) {
  if (!prev || prev.length !== curve.length) return null;
  return (
    <div className="delta-row" aria-label="change since the previous step">
      {curve.map((p, i) => { const d = (p.mid - prev[i].mid) * 1e4; return (<div key={p.tenor}><span className="dim">{p.tenor}Y</span><span className={`num ${d > 0.05 ? "pos" : d < -0.05 ? "neg" : "zero"}`}>{bp(d, 1)}</span></div>); })}
    </div>
  );
}

/** Horizontal signed bars with labels and values (P&L by factor, P&L by cause). */
export function SignedBars({ rows, f = eur, labelWidth = 130, minScale = 1, eps = 0.5 }: { rows: { label: string; value: number }[]; f?: (x: number) => string; labelWidth?: number; minScale?: number; eps?: number }) {
  const max = Math.max(minScale, ...rows.map((r) => Math.abs(r.value)));
  return (
    <div className="bars">
      {rows.map((r) => (
        <div className="bars-row" key={r.label} style={{ gridTemplateColumns: `${labelWidth}px 1fr 78px` }}>
          <span className="bars-label">{r.label}</span>
          <span className="bars-track"><span className="bars-mid" />
            <span className={`bars-fill ${r.value >= 0 ? "pos" : "neg"}`} style={r.value >= 0 ? { left: "50%", width: `${(Math.abs(r.value) / max) * 50}%` } : { right: "50%", width: `${(Math.abs(r.value) / max) * 50}%` }} />
          </span>
          <span className={`num ${r.value > eps ? "pos" : r.value < -eps ? "neg" : "zero"}`}>{f(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

/** Cumulative P&L through the episode, one point per settled decision. */
export function PnlPath({ points }: { points: { label: string; total: number }[] }) {
  const box = useRef<HTMLDivElement>(null);
  const { w: W, h: H } = useSize(box, { w: 300, h: 120 });
  const L = 46, R = 12, T = 12, B = 22;
  if (points.length < 1) return null;
  const vals = [0, ...points.map((p) => p.total)];
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1) { hi += 1; lo -= 1; }
  const x = (i: number) => L + (i * (W - L - R)) / Math.max(1, vals.length - 1);
  const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <div className="chart-box" ref={box}>
      <svg className="chart" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="P&L through the episode">
        <line className="grid" x1={L} x2={W - R} y1={y(0)} y2={y(0)} />
        <text className="axis" x={L - 6} y={y(0) + 3} textAnchor="end">€0</text>
        <text className="axis" x={L - 6} y={y(hi) + 8} textAnchor="end">{eur(hi, false)}</text>
        <text className="axis" x={L - 6} y={y(lo)} textAnchor="end">{eur(lo, false)}</text>
        <path className="pnl-line" d={d} />
        {vals.map((v, i) => (<Fragment key={i}><circle className={`pnl-pt ${v >= 0 ? "pos" : "neg"}`} cx={x(i)} cy={y(v)} r={2.6} />{i > 0 ? <text className="axis" x={x(i)} y={H - 6} textAnchor="middle">{points[i - 1].label}</text> : null}</Fragment>))}
      </svg>
    </div>
  );
}

/** A price ladder: bp around the mid running up the page (higher rate = higher), the street band, the mid, and the trainee's own price(s) as markers.
 *  Every marker is a public number or the trainee's own draft; nothing is computed beyond positions on the axis. */
/** Label heights, top to bottom, pushed apart so adjacent labels never overlap; each keeps its own marker line at the true position. */
const declutter = (ys: number[], gap = 12): number[] => {
  const order = ys.map((_, i) => i).sort((a, b) => ys[a] - ys[b]);
  const out = [...ys];
  for (let k = 1; k < order.length; k++) out[order[k]] = Math.max(out[order[k]], out[order[k - 1]] + gap);
  return out;
};

export function PriceLadder({ mid, street, mine }: { mid: number; street: { bid: number; offer: number }; mine: { value: number | null; side: "bid" | "offer"; label: string }[] }) {
  const box = useRef<HTMLDivElement>(null);
  const { w: W, h: H } = useSize(box, { w: 360, h: 200 });
  const T = 14, B = 14, ax = Math.round(W * 0.46);
  const offs = [(street.bid - mid) / 1e-4, (street.offer - mid) / 1e-4, ...mine.flatMap((m) => (m.value === null ? [] : [(m.value - mid) / 1e-4]))];
  const span = Math.max(1.5, ...offs.map((o) => Math.abs(o))) * 1.3;
  const y = (bpv: number) => T + ((span - bpv) / (2 * span)) * (H - T - B);
  const yv = (rate: number) => y((rate - mid) / 1e-4);
  const step = span > 12 ? 5 : span > 5 ? 2 : span > 2.4 ? 1 : 0.5;
  const ticks: number[] = []; for (let t = -Math.floor(span / step) * step; t <= span + 1e-9; t += step) ticks.push(+t.toFixed(2));
  const pc = (r: number) => (r * 100).toFixed(4);
  const [yOffer, yMid, yBid] = declutter([yv(street.offer), y(0), yv(street.bid)]);
  const shown = mine.flatMap((m) => (m.value === null ? [] : [{ ...m, value: m.value }]));
  const myY = declutter(shown.map((m) => yv(m.value)));
  return (
    <div className="chart-box ladder" ref={box}>
      <svg className="chart" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="your price against the street and the mid">
        <line className="ruler-axis" x1={ax} x2={ax} y1={T} y2={H - B} />
        {ticks.map((t) => (<Fragment key={t}><line className="ruler-tick" x1={ax - 4} x2={ax + 4} y1={y(t)} y2={y(t)} /><text className="axis" x={4} y={y(t) + 3}>{t > 0 ? "+" : t < 0 ? "−" : ""}{Math.abs(t)}bp</text></Fragment>))}
        <rect className="ruler-street" x={ax - 6} y={yv(street.offer)} width={12} height={Math.max(2, yv(street.bid) - yv(street.offer))} />
        <line className="ruler-mid" x1={ax - 10} x2={ax + 10} y1={y(0)} y2={y(0)} />
        <text className="axis lbl" x={ax - 14} y={yOffer + 3} textAnchor="end">street offer {pc(street.offer)}</text>
        <text className="axis lbl strong" x={ax - 14} y={yMid + 3} textAnchor="end">mid {pc(mid)}</text>
        <text className="axis lbl" x={ax - 14} y={yBid + 3} textAnchor="end">street bid {pc(street.bid)}</text>
        {shown.map((m, i) => (
          <g key={i} className={`ladder-mine ${m.side}`}>
            <line x1={ax} x2={ax + 28} y1={yv(m.value)} y2={yv(m.value)} />
            <path d={`M${ax + 8},${yv(m.value)} l9,-5 v10 z`} />
            <text className="axis lbl" x={ax + 34} y={myY[i] + 3}>{m.label} {pc(m.value)} <tspan className="dim">({(m.value - mid) / 1e-4 >= 0 ? "+" : "−"}{Math.abs((m.value - mid) / 1e-4).toFixed(2)}bp)</tspan></text>
          </g>))}
      </svg>
    </div>
  );
}

/** DV01 against its limit as a vertical scale from −limit to +limit: where you are, and (once revealed) where the decision took you. */
export function LimitThermometer({ value, after, limit, asAt }: { value: number; after?: number | null; limit: number; asAt?: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const { w: W, h: H } = useSize(box, { w: 200, h: 160 });
  const T = 10, B = 10, ax = 74, bw = 22;
  const y = (v: number) => T + ((limit * 1.1 - Math.max(-limit * 1.1, Math.min(limit * 1.1, v))) / (2.2 * limit)) * (H - T - B);
  const util = Math.abs(value) / limit;
  const fillCls = util > 1 ? "neg" : util >= 0.7 ? "warn" : "ok";
  const [yNow, yAfter] = declutter([y(value), after != null ? y(after) : y(value) + 40]);
  const mark = (v: number, cls: string, label: string, ly: number) => (
    <g className={`therm-mark ${cls}`}><line x1={ax - 6} x2={ax + bw + 6} y1={y(v)} y2={y(v)} /><text className="axis lbl" x={ax + bw + 12} y={ly + 3}>{label} {eur(v)}</text></g>
  );
  const tickVals = [limit, 0.7 * limit, 0, -0.7 * limit, -limit].filter((t, i, a) => i === 0 || i === a.length - 1 || t === 0 || Math.abs(y(t) - y(0)) >= 14 && Math.abs(y(limit) - y(t)) >= 12 && Math.abs(y(-limit) - y(t)) >= 12);
  return (
    <div className="chart-box thermo" ref={box}>
      <svg className="chart" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="DV01 against the limit">
        <rect className="therm-track" x={ax} y={T} width={bw} height={H - T - B} />
        <rect className={`therm-fill ${fillCls}`} x={ax} y={Math.min(y(0), y(value))} width={bw} height={Math.abs(y(value) - y(0))} />
        {tickVals.map((t, i) => (<Fragment key={i}><line className={t === 0 ? "ruler-mid" : "ruler-tick"} x1={ax - 5} x2={ax} y1={y(t)} y2={y(t)} /><text className="axis" x={ax - 8} y={y(t) + 3} textAnchor="end">{t === 0 ? "0" : eur(t)}</text></Fragment>))}
        <line className="therm-limit" x1={ax - 2} x2={ax + bw + 2} y1={y(limit)} y2={y(limit)} /><line className="therm-limit" x1={ax - 2} x2={ax + bw + 2} y1={y(-limit)} y2={y(-limit)} />
        {mark(value, "now", after != null || asAt ? "at decision" : "now", yNow)}
        {after != null ? mark(after, "after", "after", yAfter) : null}
      </svg>
    </div>
  );
}

/** Histogram of the path outcomes the engine simulated (whole euros), with the realised result and the mean marked. Binning is presentation only. */
export function Distribution({ yours, reference, realised }: { yours: number[]; reference?: number[] | null; realised: number }) {
  const box = useRef<HTMLDivElement>(null);
  const { w: W, h: H } = useSize(box, { w: 360, h: 170 });
  const L = 8, R = 8, T = 10, B = 34, N = 24;
  const all = [...yours, ...(reference ?? []), realised];
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1) { lo -= 1; hi += 1; }
  const bin = (xs: number[]) => { const c = new Array(N).fill(0); for (const v of xs) c[Math.min(N - 1, Math.floor(((v - lo) / (hi - lo)) * N))]++; return c as number[]; };
  const a = bin(yours), r = reference ? bin(reference) : null;
  const top = Math.max(1, ...a, ...(r ?? []));
  const x = (v: number) => L + ((v - lo) / (hi - lo)) * (W - L - R);
  const bw = (W - L - R) / N, y = (c: number) => T + (1 - c / top) * (H - T - B);
  const mean = yours.reduce((p, q) => p + q, 0) / yours.length;
  return (
    <div className="chart-box dist" ref={box}>
      <svg className="chart" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="distribution of P&L over simulated market paths">
        <line className="ruler-axis" x1={L} x2={W - R} y1={H - B} y2={H - B} />
        {a.map((c, i) => (c ? <rect key={i} className="dist-bar" x={L + i * bw + 1} y={y(c)} width={bw - 2} height={H - B - y(c)} /> : null))}
        {r ? <path className="dist-ref" d={r.map((c, i) => `${i ? "L" : "M"}${(L + i * bw + bw / 2).toFixed(1)},${y(c).toFixed(1)}`).join(" ")} /> : null}
        <line className="dist-mean" x1={x(mean)} x2={x(mean)} y1={T} y2={H - B} /><text className="axis lbl" x={x(mean)} y={H - B + 12} textAnchor="middle">mean {eur(mean)}</text>
        <line className="dist-real" x1={x(realised)} x2={x(realised)} y1={T} y2={H - B} /><text className="axis lbl dist-real-t" x={x(realised)} y={H - B + 26} textAnchor="middle">realised {eur(realised)}</text>
        <text className="axis" x={L} y={H - 2}>{eur(lo)}</text><text className="axis" x={W - R} y={H - 2} textAnchor="end">{eur(hi)}</text>
      </svg>
    </div>
  );
}

export const RateTick = ({ rate }: { rate: number }) => <span className="num">{pct(rate, 4)}</span>;
