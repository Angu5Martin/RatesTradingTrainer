// A scratch calculator for working a number out by hand: + - * / ( ), unary minus, thousands separators, and k / m / bn suffixes (225k, 1.2m).
// Client-side arithmetic only; it knows no finance and is never sent anywhere. No eval.

const SUFFIX: Record<string, number> = { k: 1e3, m: 1e6, b: 1e9, bn: 1e9 };

type Tok = { t: "num"; v: number } | { t: "op"; v: string };

function tokenise(src: string): Tok[] | null {
  const s = src.replace(/[€,]/g, "").replace(/−/g, "-").replace(/×/g, "*").replace(/÷/g, "/").toLowerCase().trim();
  const out: Tok[] = [];
  const re = /\s*(?:(\d*\.?\d+)(bn|b|m|k)?|([+\-*/()]))/gy;
  let i = 0;
  while (i < s.length) {
    re.lastIndex = i;
    const m = re.exec(s);
    if (!m) return null;
    i = re.lastIndex;
    if (m[3]) out.push({ t: "op", v: m[3] });
    else out.push({ t: "num", v: Number(m[1]) * (m[2] ? SUFFIX[m[2]] : 1) });
  }
  return out;
}

export function evalExpr(src: string): number | null {
  const toks = tokenise(src);
  if (!toks || toks.length === 0) return null;
  let p = 0;
  const peek = () => toks[p];
  const expr = (): number | null => {
    let l = term();
    while (l !== null && peek()?.t === "op" && (peek().v === "+" || peek().v === "-")) { const op = toks[p++].v; const r = term(); if (r === null) return null; l = op === "+" ? l + r : l - r; }
    return l;
  };
  const term = (): number | null => {
    let l = factor();
    while (l !== null && peek()?.t === "op" && (peek().v === "*" || peek().v === "/")) { const op = toks[p++].v; const r = factor(); if (r === null) return null; l = op === "*" ? l * r : l / r; }
    return l;
  };
  const factor = (): number | null => {
    const t = toks[p];
    if (!t) return null;
    if (t.t === "op" && t.v === "-") { p++; const v = factor(); return v === null ? null : -v; }
    if (t.t === "op" && t.v === "+") { p++; return factor(); }
    if (t.t === "op" && t.v === "(") { p++; const v = expr(); if (v === null || toks[p]?.v !== ")") return null; p++; return v; }
    if (t.t === "num") { p++; return t.v; }
    return null;
  };
  const v = expr();
  return v !== null && p === toks.length && Number.isFinite(v) ? v : null;
}
