import type { ReactNode } from "react";
import { eur, sign } from "../lib/format";

export function Panel(p: { title: string; aside?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <section className={`panel ${p.className ?? ""}`}>
      <header className="panel-h"><h2>{p.title}</h2>{p.aside ? <div className="panel-aside">{p.aside}</div> : null}</header>
      <div className="panel-b">{p.children}</div>
    </section>
  );
}

/** A signed number: tabular, right-aligned, coloured by sign (and always carrying its glyph, never colour alone). */
export function Num({ v, f = eur, eps = 0.5, plain = false }: { v: number; f?: (x: number) => string; eps?: number; plain?: boolean }) {
  return <span className={`num ${plain ? "" : sign(v, eps)}`}>{f(v)}</span>;
}

export function Chip({ tone = "neutral", children, title }: { tone?: "neutral" | "accent" | "pos" | "neg" | "warn" | "bid" | "offer"; children: ReactNode; title?: string }) {
  return <span className={`chip chip-${tone}`} title={title}>{children}</span>;
}

export const Kbd = ({ children }: { children: ReactNode }) => <kbd className="kbd">{children}</kbd>;

export function RatingChip({ rating }: { rating: string }) {
  const glyph = { sound: "●", defensible: "◐", poor: "○", error: "✕" }[rating] ?? "·";
  return <span className={`rating rating-${rating}`}><span aria-hidden>{glyph}</span> {rating.toUpperCase()}</span>;
}

/** Signed exposure against a limit: a bar from the centre, ticks at the limits, amber from 70% and red past 100%, always with the figures. */
export function Gauge({ value, limit, label, f = eur, compact = false }: { value: number; limit: number | null; label: string; f?: (x: number) => string; compact?: boolean }) {
  const util = limit ? Math.abs(value) / limit : 0;
  const tone = util > 1 ? "neg" : util >= 0.7 ? "warn" : "ok";
  const half = limit ? Math.min(1, util) * 50 : 0;
  return (
    <div className="gauge" role="meter" aria-label={label} aria-valuenow={value} aria-valuemin={limit ? -limit : undefined} aria-valuemax={limit ?? undefined}>
      <div className="gauge-row">
        <span className="gauge-label">{label}</span>
        <span className="gauge-val"><Num v={value} f={f} />{limit ? <span className="dim">{compact ? "" : ` / ${f(limit).replace("+", "")}`} · {(util * 100).toFixed(0)}%</span> : null}</span>
      </div>
      <div className="gauge-track">
        <span className="gauge-mid" />
        {limit ? <span className={`gauge-fill gauge-${tone}`} style={value >= 0 ? { left: "50%", width: `${half}%` } : { right: "50%", width: `${half}%` }} /> : null}
      </div>
    </div>
  );
}
