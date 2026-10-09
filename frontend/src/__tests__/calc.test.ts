import { describe, expect, it } from "vitest";
import { evalExpr } from "../lib/calc";

describe("the scratch calculator", () => {
  it.each([["625 * 456 / 1000", 285], ["1.2k + 300", 1500], ["(2+3)*4", 20], ["-5 + 2", -3], ["225k*2", 450000], ["1,250,000 - 250k", 1000000], ["2 × 3 ÷ 4", 1.5], ["€150m / 3", 50e6]])("%s = %s", (e, v) => expect(evalExpr(e as string)).toBeCloseTo(v as number));
  it.each(["", "2 +", "(2", "2)", "abc", "2 3", "1/0", "alert(1)", "2 ** 3"])("rejects %j without evaluating anything", (e) => expect(evalExpr(e)).toBeNull());
});
