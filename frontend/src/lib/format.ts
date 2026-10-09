// Display formatting only. The conventions mirror the Python side (fmt_eur, pct) so numbers read the same in both places.

export function eur(x: number, signed = true): string {
  const a = Math.abs(x);
  if (a < 0.5) return "€0";
  const sign = x < 0 ? "−" : signed && x > 0 ? "+" : "";
  const body = a >= 1e6 ? `${(a / 1e6).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}m`
    : a >= 1e3 ? `${(a / 1e3).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}k`
    : Math.round(a).toLocaleString("en-US");
  return `${sign}€${body}`;
}

export const eurM = (x: number): string => `€${(x / 1e6).toLocaleString("en-US", { maximumFractionDigits: 0 })}m`;
export const pct = (rate: number, dp = 4): string => `${(rate * 100).toFixed(dp)}%`;
export const pctNum = (rate: number, dp = 4): string => (rate * 100).toFixed(dp);
export const bp = (x: number, dp = 1, signed = true): string => {
  const v = Math.abs(x) < 0.5 * 10 ** -dp ? 0 : x;
  return `${v < 0 ? "−" : signed && v > 0 ? "+" : ""}${Math.abs(v).toFixed(dp)}bp`;
};
export const num = (x: number, dp = 0): string => x.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });

export type Sign = "pos" | "neg" | "zero";
export const sign = (x: number, eps = 0.5): Sign => (x > eps ? "pos" : x < -eps ? "neg" : "zero");

/** Parse a rate typed in percent ("2.8465", "2,8465%"); returns a decimal rate, or null if unreadable or implausible. */
export function parseRatePct(raw: string): number | null {
  const t = raw.trim().replace(",", ".").replace("%", "");
  if (!/^[+-]?\d*\.?\d+$/.test(t)) return null;
  const x = Number(t);
  return x > 0 && x < 15 ? x / 100 : null;
}

/** Parse a size typed in EUR millions ("150", "62.5"); null if unreadable or not positive. */
export function parseSizeM(raw: string): number | null {
  const t = raw.trim().replace(",", ".").toLowerCase().replace(/m$/, "");
  if (!/^\d*\.?\d+$/.test(t)) return null;
  const x = Number(t);
  return x > 0 ? x * 1e6 : null;
}
