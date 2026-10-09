# Design

Goal (from CLAUDE.md): make **Trade → Position → Risk → Hedge → Market Move → P&L** and
**Fair Value → Quote → Client Trade → Position → Risk → Skew/Hedge → Move → P&L → Re-quote**
automatic for a junior EUR linear-rates trader.

## Layers

```
engine/         deterministic finance. No randomness, no I/O, no UI. Everything numerical lives here.
marketmaking/   bid/offer mechanics, client-trade -> position, stylised quote-skew model.
curriculum/     skill graph (skills.py) + curated conceptual questions as TOML data.
questions/      Question model + grading, registry, random market generator, templates/.
episodes/       stateful market-making episodes: state, factors, assessment, runner, level specs (docs/EPISODES.md).
                api.py is the frontend boundary (Session); views.py the public plain-data view-models; render.py the terminal wording.
session.py episode_session.py cli.py trainer     thin terminal UI.   (a later UI would sit beside these and talk to episodes/api.py and questions/)
```

Dependencies point downwards only. `questions/` calls the engine to get answers; **no template
contains financial arithmetic of its own** beyond presentation. Python stdlib only at runtime;
`pytest` for development.

### Engine

| Module | Contents |
|---|---|
| `dates.py` | TARGET calendar (Easter-based), Following / Modified Following, T+2 spot, ACT/360, ACT/365F, 30E/360, schedules |
| `curve.py` | `Curve` (date-based, log-linear; used for both discount and projection), `CurveShock` |
| `instruments.py` | `IRSwap` (vs 6M Euribor, spot or forward start), `OISSwap`, `FRA`, `BasisSwap` (3s6s), `FixedBond` (with ASW spread, repo funding spread, accrued, ICMA yield maths), `AssetSwapPackage` |
| `marketdata.py` | `MarketCurves`: par quotes in → ESTR-OIS, 6M and 3M Euribor curves out (lazy, dual-curve bootstrap); bumps and shifts; `rolled()` to a later date with past fixings carried in `history` |
| `risk.py` | `Portfolio`, key-rate and parallel DV01, at-market factories (`par_irs`, `par_ois`, `par_fra`, `par_basis`), hedge sizing and solver |
| `pnl.py` | the two P&L paths (below) and a report that shows both |
| `carry.py` | carry / roll-down / other for swaps AND funded bonds, breakeven for any shape of move, holding-period P&L attribution |
| `futures.py` | Bund / Bobl / Schatz futures: conversion factors, the basis screen (`basis_line`: gross / carry / net basis, implied repo), CTD, `BondFuture` (curve-consistent price, DV01, CTD switches), long-basis payoff |
| `stir.py` | 3M Euribor futures (`STIRFuture`), IMM dates, strips, convexity adjustment |

**One generic risk engine.** An instrument only implements `pv(market)`. Risk is measured by bumping one
*par quote* by ±0.5bp, re-bootstrapping and repricing, as a desk risk system does. Risk keys are
`(curve, pillar_months)`: `("OIS", 120)`, `("E6M", 120)`, `("BASIS_3S6S", 120)`. A new product costs one `pv` method; DV01,
hedging and P&L come free. Consequences (all tested):

* A par instrument struck at its own pillar has risk **only in its own key**. A par 10Y IRS is entirely `("E6M", 120)`;
  bumping OIS leaves its PV at zero because the Euribor curve re-fits. So "the 2Y moves −5, the 10Y moves +3" fully
  determines a curve trade's P&L without specifying what happens in between.
* Off-pillar or off-market instruments spread across neighbouring keys, and across curves (discounting risk appears in OIS keys).
* **Calibration reuses the real instruments**: each pillar solves "instrument struck at its quote has PV 0". Pricing
  and bootstrapping cannot disagree; every input quote reprices to ~1e-15.

### Two P&L paths (deliberately separate)

| | First-order (the trader's head) | Full revaluation (the numerical truth) |
|---|---|---|
| What | `P&L ≈ −DV01 × move`, bucketed: `Σ −KR_i × move_i` | `PV(shocked market) − PV(base market)` |
| Code | `pnl.first_order_pnl`, `key_rate_first_order_pnl` | `pnl.revalue_pnl` |
| Uses | risk numbers only | reprices every leg, includes convexity and cross effects |
| Role | what you are trained to do in seconds | what validates it |

They share no code, so each checks the other: the gap is convexity, scales with move² (tested: ×4 when the move doubles),
and is positive for a long-duration book (negative for a payer). In questions:

* a `NumericPart` stores the **precise** value in `answer` and the **first-order** value in `approx`;
* `accept_approx=True` (default) means the first-order answer is a correct answer, and tests assert that the
  tolerance really admits it (scanned over 400 seeds per template);
* `accept_approx=False` is for questions where the approximation is the trap (forward-start rates weighted by years instead of annuities);
* after every answer the session prints both: `first-order estimate: … | precise: … | difference …`, so you see how big the
  approximation error actually was. Bond questions go one step further: duration only → + convexity → exact repricing.

### Carry, roll-down and warehousing

*What does it cost or pay to hold a position while time passes?* Time can pass in two ways, and the gap between them is the lesson:

| | **Static curve** (what desks mean by "carry & roll-down") | **Forwards realised** |
|---|---|---|
| Held fixed | every par swap rate **by tenor** | the **forward** curve |
| The position | ages and rolls down the curve | ages along a curve that drifts to its forwards |
| Par swap, receiver, upward slope | earns carry **and** roll-down | earns **zero** (exactly) |

The engine splits the static-curve P&L into three parts, each equal to a calculation a trader can do:

| Part | Engine definition | Mental version |
|---|---|---|
| **Carry** | cash accrual: fixed accrued − floating accrued over the horizon (undiscounted) | `N × (K × time − short rate × days/360)`. Exact: it *is* this |
| **Roll-down** | clean twin (same remaining dates, restarted at the new spot) repriced on the unchanged curve − today's PV | `DV01 × (K − curve rate for the remaining maturity)`. Off by the annuity ratio (~ horizon/tenor: 2% for a 3M roll on 10Y, 12% on 2Y) |
| **Other** | what is left: PV of accrued coupons (paid later, ≈ 2% below face) + the IRS floating leg's in-progress coupon having been fixed at the old rate | none; reported so nothing is hidden. Larger for short tenors where the front end slopes |

Identities (all tested, and they are the intuition):

1. **Forwards realised, par swap: total P&L = 0, exactly** (machine precision). Carry is offset by the mark-to-market drift the forwards impose: *carry is
   the market's expected drift being paid to you, not free money*. General form: `total_forward = PV₀ × (1/DF − 1)`.
2. **Static curve, par swap:** `total ≈ DV01 × (forward rate − spot rate)`, both for the remaining maturity. On OIS the equality holds to 0.002bp;
   on IRS to a few tenths of a bp (the floating-reset effect).
3. **Breakeven:** the parallel rise in rates that erases the total is `total / DV01` (≈ the forward-implied drift). `breakeven_move()` solves it by full
   revaluation for *any* shape, e.g. a spread move for a curve trade. A payer in an inverted curve earns carry yet breaks even on a *fall*.
4. **Curve trades:** a DV01-neutral steepener's carry + roll-down is `−|DV01| × (forward spread drift)`: it pays when the forwards already price a steeper curve.
5. **Forward-start swaps** accrue nothing (carry exactly 0) but still roll down.

**Question design for intuition.** The numeric questions build the mental route piece by piece (carry, roll-down, total, breakeven), then ask the conceptual
step that matters: what happens if forwards are realised instead? The warehousing questions put carry next to risk: breakeven as a % of one standard
deviation (carry is typically a small cushion, so a position that "pays carry" is still a directional bet), and for a market maker, a week of carry + roll-down
set against one sigma of P&L and the cost of hedging (carry is a second-order input to skew; inventory against the limit, expected flow and volatility
remain first order). The attribution question splits a month of P&L into time (carry, roll-down, other) versus market move (delta, convexity residual).

**Tolerances come from measurement, not guesswork.** For each mental formula we measured the gap to the engine over 100+ random markets and set the
tolerance from the worst case plus a margin (~35% for single swaps, 50% for curve trades; a false rejection of a correct mental answer is worse than a slightly looser tolerance):

| Quantity | Mental route | Tolerance |
|---|---|---|
| carry | cash-accrual arithmetic | none beyond rounding of the printed rates (it *is* that arithmetic) |
| roll-down | `DV01 × (K − rate for remaining maturity)` | `rel = 2% + days/365/tenor` (the annuity ratio) |
| total, breakeven | carry + roll-down | `abs = f(tenor) × g(horizon) × |DV01|` |
| curve-trade total | `−position sign × |DV01| × forward spread drift` | `0.58bp × g(horizon) × |DV01 of one leg|` (measured worst 0.39: leg errors largely cancel) |

with measured worst error of the total in bp of DV01, 3-month horizon: **0.66 / 0.48 / 0.37 / 0.24 / 0.19 / 0.14** for 5 / 7 / 10 / 15 / 20 / 30Y
(roughly 1/tenor; tolerances 0.90 / 0.65 / 0.50 / 0.33 / 0.26 / 0.19) and horizon factor g = 0.5 for a week, 0.9 for a month, 1.0 for a quarter. The residual is the `other` term above, which the mental route
does not include. Two further rules keep questions meaningful:

* **Significance.** A scenario is drawn only if its answer is at least 2.5× the tolerance on it; otherwise a lazy answer (zero, wrong sign) would pass.
  Where the combined total cannot clear that bar (a week of carry for a market maker), the question asks the sharp components separately, carry and
  roll-down, and uses the precise total only for the judgement.
* **Consistent judgement.** Multiple-choice readings that depend on a number (does a week of carry earn back the hedge cost?) are drawn only when the engine's
  total and the mental estimate agree on the answer.

A 200-seed scan per template (run when tolerances change, not in the unit suite) asserts the mental answer is accepted, with every worst case at ≤ 87% of its allowance. Numeric carry questions use tenors ≥ 5Y because the floating-reset effect makes
short-tenor totals noisy; the 2Y front end belongs to the later curve-shape module.

**Limits (raised as errors, not silently ignored).** The horizon may not cross a payment date; only IRS and OIS are supported. Bond carry needs repo
financing, so it arrives with the repo module. In a rolled market past ESTR compounding and past fixings come from `history` (the forwards-realised assumption);
explicit `fixings={index: {period start: rate}}` are supported for seasoned trades.

### Bonds versus swaps, repo and bond carry

**Pricing a bond against the swap curve.** A `FixedBond` is priced off the OIS curve plus its asset-swap spread:
`dirty price per unit face = V − asw × A`, where `V` is the bond's cash flows discounted on OIS ("swap-curve value") and `A` is the spread annuity
(PV of 1 per year on the coupon dates, ACT/360, i.e. the floating leg of the asset swap). Sign convention, used everywhere:

| Quantity | Definition | Sign |
|---|---|---|
| **ASW** (par-par, over OIS) | `(V − dirty price) / A`, roughly bond yield − swap rate (bond basis) | **cheap bond = positive** |
| **Swap spread** (Bund-style) | swap rate − bond yield | the *negative* of ASW, roughly |
| **Funding spread** | repo rate − ESTR | **special = negative** |
| **Asset-swap package** | long bond + pay the bond's coupons, receive ESTR + ASW, outlay par | gains when ASW **tightens** (= swap spread widens) |

Quick rules and when they fail (all measured, see tolerances): `ASW ≈ yield − swap par yield` is good for near-par bonds with moderate spreads and overstates a
deep-discount, wide-spread bond (dollar duration ≠ spread annuity; convexity). `ASW01 = N × A × 1bp ≈ a swap DV01 on the same notional and maturity`.

**The package is a spread instrument.** At inception it is worth par and, because it is priced as bond + swap leg from the curve, equals the closed form
`N × [1 + (locked_spread − asw) × A]`: a parallel move of 50bp leaves it exactly at par, and a bp of ASW is worth `N × A × 1bp`. So an ASW package carries
essentially no outright rate risk; a bond hedged with an ordinary DV01 swap hedge, by contrast, is left with exactly the ASW exposure.
**Subtlety worth knowing:** the engine holds the bond's ASW constant when rates move, and the spread annuity shrinks when rates rise, so the bond's
swap-curve DV01 differs from market value × modified duration by a convexity effect that grows with ASW × maturity (≈2% for small spreads, up to ~12% for 30Y
at 60bp). The hedge-ratio question's tolerance is a function of exactly those two quantities.

**Repo and carry.** Financing = market value × (ESTR growth + funding spread × days/360), ESTR being the forward path implied by the OIS curve. Bond carry
= coupon accrued (ACT/ACT) − financing. For bonds the three-part split of the static-curve P&L collapses to two exact parts, because the clean price is defined as
dirty minus accrued: **carry** and **roll-down = clean price change**, with `other = 0` exactly. The clean-price change itself splits into
**pull-to-par** (the clean drift at an unchanged yield) and **curve roll-down** (`DV01 × (yield − remaining-maturity yield)`), and
`carry + pull-to-par = growth of the dirty price at an unchanged yield − financing ≈ MV × (yield − repo) × time`: the *yield pickup over repo*. The quick
form runs high by the compounding term `MV × y²/2 × time`, which is exactly the tolerance used.

Identities (tested): a bond funded at the forward ESTR path earns **exactly zero if forwards are realised**, for any price and any ASW (carry is paid for by the
forward drift, the same lesson as for swaps); a repo spread (specialness) is then the only edge that survives, worth `MV × spread × days/360`; carry changes sign near
repo = coupon / dirty price (the current yield); discount bonds pull up to par and premium bonds pull down.

**Limits.** The asset-swap package is priced at its first coupon date only. ASW is over the OIS curve with an ESTR floating leg (traditional EUR ASW is quoted against
6M Euribor, which would add the Euribor-ESTR basis). One ASW per bond (no issuer spread curve). A bond built with `FixedBond.from_maturity` is valued mid-period
(dirty = `pv`, clean = dirty − accrued, coupon dates unadjusted); the futures module uses these.

### Bond futures (Bund family) and 3M Euribor futures

**The chain, as code.** `bond → conversion factor → futures-equivalent price → CTD → futures price → futures DV01 → implied repo → basis → trade`. Every link
is a function in `engine/futures.py`, and every question walks some of them.

| Quantity (per 100 face) | Definition | Teaches |
|---|---|---|
| **Conversion factor** CF | price at a 6% yield on the delivery date, remaining life rounded DOWN to whole months, accrued removed, 6 dp | one flat 6% yield makes bonds *nearly* interchangeable: not exactly |
| **Invoice** | `F × CF + accrued at delivery` (one contract = €100k face of any deliverable; 1 point = €1,000, 1 tick = €10) | CF < 1 for a sub-6% coupon: the short receives less than the notional |
| **Gross basis** | `clean − F × CF` | the cost of owning the bond against the future, before carry |
| **Carry** | accrued built up (+ any coupon, reinvested at repo) − `dirty × repo × days/360` | positive when coupon income beats financing |
| **Net basis** | `gross − carry = forward clean − F × CF = CF × (F_i − F)` | the price of the short's delivery options |
| **Futures-equivalent price** `F_i` | `forward clean / CF`: the futures price at which delivering bond *i* is exactly break-even | the CTD is the bond with the lowest `F_i` |
| **Implied repo** | the repo that balances: buy the dirty bond, sell the future, deliver | above the actual repo = a riskless cash-and-carry; normally *below* it |
| **CTD** | lowest net basis = highest implied repo when all bonds finance at one repo | a ranking decision, not a definition |

**Why there is a CTD.** CF prices every bond at one flat 6%; the market prices them at 2-3%. At yields **below** 6% the CF over-states what a long-duration bond is worth
relative to a short one, so the *lowest-duration* bond is cheapest; above 6% it is the *highest-duration*. It is a tendency (carry, ASW and curve slope can override,
and the engine ranks on net basis), but a very good first guess. The future is priced off the CTD: `fair F = min_i F_i`, and it trades *below* that by the value of
the other options (the CTD's net basis), which is why the CTD's implied repo sits a little below the repo rate. Net basis is ranked with each bond at **its own repo**: a special bond saves
`dirty × spread × days/360` of net basis and can steal the crown.

**The future is short the delivery option.** `F = min_i F_i ≤ F_ctd(y)` at every curve level, with equality only while that bond is cheapest, so the future has *less
convexity than its CTD* and underperforms it in a big move in either direction. Its DV01 is the CTD's DV01 divided by CF; if a longer-duration bond becomes CTD the DV01 per
contract *rises* and a CF-weighted hedge sized yesterday is too small. A CF-weighted hedge of a position in the CTD is `face × CF / 100,000` contracts, not `face / 100,000` (over-hedged by `1/CF − 1`).

**The long-basis payoff (exact).** Buy the CTD, repo it, sell CF futures-units per 100 face and hold to delivery:
`P&L = −net basis + CF × (F_i' − min_j F_j')`. The first term is the premium (if nothing happens the whole net basis is lost, because the future converges to the CTD's forward price);
the second is the option payoff (how far the old CTD has become dearer than the cheapest). It is DV01-neutral, long volatility and short time. A non-CTD bond loses only `CF × offset` if nothing happens
(its out-of-the-money value remains). At delivery the CTD's gross basis is exactly zero and every other bond's is positive.

**Two layers, deliberately.** `basis_line` takes quoted prices only (no curve), which is what the student sees and what ranking and implied-repo questions grade. `BondFuture` is the curve-consistent
model (bond price from the OIS curve and its ASW, financing at the OIS-implied ESTR path plus the bond's funding spread, `price_offset` calibrated to a printed futures price): DV01, hedge ratios, CTD switches and scenario
P&L come from repricing it. At the base market the two layers agree on prices. *Scenario shocks are applied as price changes on top of the repo-implied forward*, because with a
constant ASW the model's own forward price differs from the repo arithmetic by about ASW × 1y whenever a coupon is paid inside the window (tested: exactly equal with no coupon).

**Mental routes and measured tolerances.** CF ≈ `1 − (6% − coupon) × annuity at 6%` (error < 0.0003, usually 1e-5). Futures DV01 ≈ CTD forward dirty price × modified duration *at delivery* × 1bp / CF × 1000: within +0.4% to
+3.8% of the engine for Bund, Bobl and Schatz (using today's duration instead is up to 14% out for a Schatz four months from delivery, because duration shortens as time passes); the contracts-to-hedge tolerance is
`3% + days/365/duration + the constant-ASW term`. Net basis and implied repo ignore interest on a coupon received before delivery; the allowance is exactly that interest. CTD-switch answers read a printed table
of futures-equivalent prices and DV01s: the first-order error is convexity (`≈ ½ D² F move²`, spread across bonds for the P&L), plus the table's rounding; the move is the mildest that changes the CTD and the scenario is redrawn
until every answer clears its tolerance, and the first-order and exact CTDs agree with a margin.

**3M Euribor futures.** Price = 100 − rate; EUR 25 per bp; long = long duration (like receiving in a FRA); a receiver is hedged by *selling* the strip. The futures rate is the forward rate plus a convexity adjustment (daily margining makes a long worth less than a FRA;
Ho-Lee `½σ²T₁T₂`, about 1bp two years out, held fixed when the curve moves). A 1bp move in par swap quotes moves a 3M forward by ~0.96bp, so the engine's DV01 per contract is ~€24.1, not 25, and a strip hedges *parallel* risk; stub periods, discounting
and 3M-versus-6M show up on non-parallel moves.

**Limits.** One delivery date (the 10th, TARGET Following); no wildcard or end-game options, only the quality (which-bond) option. Coupon dates are unadjusted. One flat repo rate for the term plus a per-bond spread. Baskets are stylised
(coupons around the current coupon, a few bp of ASW noise). The STIR convexity adjustment is an input, not derived from a vol surface (vol products are out of scope).

### Question architecture

Every question is `(template_id, seed)` → `Question(stem, parts, solution, facts)`; regenerating the pair reproduces it exactly
(`./trainer --replay mm.client_trade_risk#249523`).

| Source | Use for | Where |
|---|---|---|
| Curated (TOML) | conceptual judgement, conventions, direction. First option is correct; order shuffled per seed | `curriculum/curated/*.toml` |
| Parameterised template | one skill, many numerical instances; answers from the engine | `questions/templates/*.py`, `@template(...)` |
| Multi-part scenario | one market state followed through trade → position → DV01 → edge → hedge → P&L | templates with several `Part`s (`mm.client_trade_risk`, `curves.curve_trade`) |

A `Part` is a `NumericPart` (tolerance, sign-aware feedback, unit-slip detection: "right size, wrong sign", "looks 1000x too large")
or a `ChoicePart`. `facts` carries the generation inputs so tests can recompute answers by an independent route.

Stateful multi-step episodes are built on top of these pieces (`QuotingContext`, `Portfolio`, `Quote.dealer_swap`): see `docs/EPISODES.md`.

The TRAIN expansion added sources in eight modules under `questions/templates/` (`curve_maths`, `money_market`, `swap_valuation`, `risk_book`, `portfolio`, `rv_spreads`, `futures_specs`, `mm_standalone`)
and two curated files (`foundations.toml`, `mm_judgement.toml`). They follow the rules above and two more: a source that exists never changes what it generates for a given `(template, seed)`, because a practice
record and a replay are that pair (a digest test pins 372 draws of the 62 earlier sources), and a part's `kind` must not depend on the seed, because the catalogue classifies a source from seed 0.

### Curriculum

`curriculum/skills.py` is a graph of 41 skills with prerequisites, grouped in ten tracks. A skill is **planned** when it is on the roadmap and has no questions of any kind
(the TRAIN catalogue shows a *planned* chip); a skill with no standalone questions that is practised only in the Live Desk shows *no standalone questions*
(`./trainer list`: `NO QUESTIONS`). A test fails if a planned skill gets questions (clear the flag) or an active skill has none. Every skill now has standalone questions: see
`docs/CURRICULUM.md` for the coverage matrix, the audit of the question sources, the review of the public book material and what remains outside TRAIN.

## Market conventions

* **DV01 = P&L for a 1bp *fall* in rates.** Long duration (receiver, long bond) is positive. Fast estimate:
  P&L ≈ −DV01 × move. We say "long duration", never "long rates" (ambiguous).
* **EUR products.** IRS: fixed annual 30E/360 vs 6M Euribor semi-annual ACT/360, discounted on ESTR-OIS. OIS: fixed annual ACT/360
  vs compounded ESTR. FRA: settled at period start, `N τ (K − F)/(1 + Fτ)`. Basis: 3M + spread vs 6M flat.
  Bonds: annual coupon, valued on a coupon date (clean = dirty), discounted on OIS.
* **Dates.** One calendar (TARGET), Modified Following, spot = T+2, PVs as at spot. **Not modelled:** end-of-month rule,
  stubs, payment lag (EUR OIS has a 1-day lag), fixing lags, holiday calendars other than TARGET, accrued interest.
* **Interpolation.** Log-linear on discount/projection factors (piecewise-flat forwards), flat-forward extrapolation.
  Consequence worth knowing: a 1bp parallel move in 30E/360 par rates moves an ACT/360 forward by only ~0.96bp (the
  360/365 factor plus the interpolation), which is why a FRA's DV01 is 3–8% below the naive N × τ × 1bp. This is real and tested
  against a directly measured forward move.
* **Bumps.** ±0.5bp central difference per 1bp so DV01 carries no convexity contamination. A "rates move" shifts OIS and
  Euribor swap quotes together; the 3s6s basis spread is held (it has its own risk keys).
* **Rounding.** Screen quotes to 0.1bp; answers accepted within a stated tolerance (mental maths is the point: 3–5% typical).

### Quote convention: how bid / offer, pay / receive and duration fit together

Rate quotes are shown from the **dealer's** side. **Bid = the fixed rate at which the dealer pays fixed (the lower rate).
Offer = the fixed rate at which the dealer receives fixed (the higher rate).** The client always trades at the
worse rate for them: they pay more than mid or receive less than mid. This is the standard textbook convention (e.g. Hull). Interdealer "paid / given" jargon is deliberately not used here.

| Client does | Hits | Dealer does | Dealer is | DV01 | Dealer makes money if rates | Dealer wants this flow when |
|---|---|---|---|---|---|---|
| **pays** fixed | **offer** (higher) | **receives** fixed | **long** duration | **+** | **fall** | short duration, or a bullish-rates view |
| **receives** fixed | **bid** (lower) | **pays** fixed | **short** duration | **−** | **rise** | long duration, or a bearish-rates view |

Skew, in the same terms:

| Dealer state | Wants to | Quotes (vs symmetric around fair value) | Makes attractive | Which, if dealt, makes the next skew… |
|---|---|---|---|---|
| long duration (or expects it: flow, bearish view) | pay fixed | **higher** in rate: both bid and offer up | bid, for clients who **receive** | smaller (inventory falls) |
| short duration (or bullish view) | receive fixed | **lower** in rate: both down | offer, for clients who **pay** | smaller |

Think of the swap rate as the *price of paying fixed*. A long-duration dealer is *short* that price, so it wants to buy it back:
it quotes higher, like a short squeeze in reverse. In bond-price language the same statement is "the long dealer is more willing
to sell, so both its bid and offer prices are lower": **a bond-price bid corresponds to the swap-rate *offer*** (lower price = higher
rate). CLAUDE.md's "long inventory ⇒ more aggressive offer" is the price-language version of "long duration ⇒ better rate-bid".

Worked examples (executable in `tests/test_conventions.py`; 10Y IRS market 2.843 / 2.847, mid 2.845):

1. **Client pays €300m.** Trade at 2.847; dealer receives fixed ⇒ long duration, DV01 **+€261k/bp**. Marked at mid the dealer
   immediately shows **+€52.2k** (= 0.2bp × DV01: the edge). Rates −2bp: **+€575.0k** (edge + €522.8k); +2bp: **−€469.5k**.
   First-order edge − DV01 × move gives +€574.5k for the rally: the €0.5k gap is convexity.
2. **Client receives €300m.** Trade at 2.843; dealer pays fixed ⇒ short duration, DV01 **−€261k**; edge +€52.2k; rates +2bp: +€574k.
3. **Round trip** (both clients): DV01 ≈ 0, PV at mid = **+€104.4k** = full 0.4bp width × DV01.
4. **Dealer long 300k DV01, limit 500k.** Quote moves from 2.8430/2.8470 to **2.8444/2.8484** (+0.14bp, both sides up). The bid
   is better for a client who receives and the offer worse for one who pays. If a client **receives** €100m (encouraged) inventory
   falls to +213k and the next skew eases to +0.09bp; if one **pays** (discouraged) it rises to +387k and the skew intensifies to +0.20bp.
5. **Dealer short:** exact mirror image (skew sign flips; encouraged client action is *paying*).
6. **Bearish-rates view** (4bp, 0.8 conviction) with a flat book: quote **higher**, encouraging clients to **receive**: the dealer ends up *paying* fixed = short duration
   = in the right position if rates really do rise. A view skews the same way as a long inventory does, because both want to be *shorter*.

## Why the quote model is "stylised"

`marketmaking/quoting.py::make_quote` turns a `QuotingContext` (fair value, inventory DV01 and limit, expected flow, view and
conviction, volatility, liquidity, adverse selection) into a quote **and the contribution of each driver**: inventory skew,
expected-flow skew, view skew, core width, limit-pressure widening on the risk-adding side. It is a teaching device: magnitudes are
plausible for liquid 10Y (fractions of a bp) but nobody claims they are optimal. Questions built on it grade **direction and
relative width**, not a point value, and always show the decomposition. This keeps CLAUDE.md's rule *no single formula where
there is no genuine model*, while letting generators make unambiguous scenarios (rejection sampling discards cases where drivers nearly cancel).

Principles it encodes: skew manages inventory; width protects against information and volatility; limits beat views;
skewing and widening both cost flow.

## Validation strategy

1. **Engine vs independent closed forms.** Hand-written OIS and IRS par-rate formulas; forward-swap additivity
   (`S10·A10 = S5·A5 + S5y5y·A5y5y`); float-leg telescoping when projection = discount; FRA formula and its single-curve identity;
   par swap DV01 = N × annuity × 1bp; FRA DV01 = Nτ·D/(1+Fτ)·(measured dF); bond duration/convexity vs finite differences.
2. **Properties.** Par instruments have PV 0; hedges zero the DV01; par risk is own-key only; receiver convexity positive and the
   first-order error scales with move²; key rates sum to parallel; every input quote reprices.
3. **Every template × 60 seeds** (and a 400-seed scan for tolerances): finite answers, exact and first-order answers grade correct,
   negated answer gets the sign hint, deterministic regeneration, variety, choice answers not always "A".
4. **Per-template independent recomputation** from `facts` (e.g. edge = half-width × |DV01|; basis01 = N × 1bp × 3M-leg annuity).
5. **Carry/roll identities:** forwards-realised total = 0 and `PV₀(1/DF−1)` to ~1e-9 for IRS and OIS, spot and forward start; carry equals the by-hand
   accrual arithmetic to 1e-12; roll-down equals the clean twin's repricing and tracks `DV01 × (K − S_rem)` within the annuity ratio; OIS breakeven = forward drift;
   breakeven really zeroes the revalued P&L; sign symmetry and linearity in notional; paid periods drop out of aged pricing; weekend carry = 3 days.
6. **Bonds versus swaps:** price = V − asw×A and ASW round-trips; the package equals its closed form and is exactly par under a parallel move; ASW01 = N×A×1bp;
   dated ICMA yields reduce to the closed-form maths at a coupon date and accrete by (1+y)^(days/period); bond carry equals coupon accrual − financing by hand;
   forwards-realised funded bond = 0 exactly; specialness = MV×spread×days/360; carry + pull-to-par = dirty growth − financing exactly.
7. **Bond futures:** CF against its annuity closed form and a hand-laid cash-flow example; 6%-coupon whole-year bond has CF 1; implied repo against an explicit loan-and-coupon cash-flow simulation (with a coupon in the window);
   round trip (price a future from bond *i*, recover bond *i*'s repo and a zero net basis); `net = CF × (F_i − F)` and `net = gross − carry`; the CTD sets the price and has the highest implied repo (one repo); `F ≤ F_i(y)` at every shock;
   the CTD tendency below and above 6%; higher repo raises the fair futures price by about `dirty × Δrepo × days/360`; the long-basis payoff equals `−net basis + CF × (F_i' − min F_j')` and is bounded below by `−net basis`;
   a CF-weighted hedge neutralises a CTD position and the face-for-face hedge over-hedges by `1/CF`; strip DV01 and hedge against a swap.
9. **TRAIN expansion** (`tests/questions/test_expansion.py`): 36 templates recomputed from first principles or by a different engine route (an annuity against a bump-and-reprice, an
   enumeration against a closed form, a finite difference against a duration), their tolerance windows checked against the mental route, the earlier sources pinned by digest, skill coverage,
   filters, no leakage through the session, and the curated options checked for a length tell (the right answer is neither usually the longest nor usually the shortest). Mutation checks (49 single-point
   mutations: signs, weights, divisors, day counts) were run with caches cleared; the three that first survived (an `approx` sign, a client-side sign and a model-quote swap, each only checked for
   self-consistency) now have assertions that tie them to the action or to a hand-built quote, and one equivalent mutant (a redundant guard) remains.
8. **Mutation checks** (run when each layer was written; caches cleared): flipping hedge direction, skew sign, client↔dealer side,
   basis sign, FRA discounting, the IRS fixed-leg day count, carry sign, forward-roll, realised OIS compounding, fixing source, clean-twin restart,
   breakeven sign, paid-period filtering, ASW sign, financing sign, accrued interest, specialness sign or the ICMA exponent each fail the intended test; and for futures the CF month rounding, the accrued
subtracted from the CF, the carry sign, the implied-repo denominator, the CTD choice (max instead of min), the hedge ratio (CF in the wrong place) and the futures DV01 divisor.

## Adding content

* **A conceptual question:** add a `[[question]]` to a TOML file in `curriculum/curated/`.
* **A numerical skill:** write `(rng) -> QuestionBody` with `@template(id, skill, difficulty)` in `questions/templates/`, import the
  module in `templates/__init__.py`, take every answer from the engine (precise → `answer`, mental → `approx`), and add an independent
  check to `tests/questions/test_templates.py`.
* **A product:** add an instrument with `pv(market)` to `engine/instruments.py` (plus a `par_*` factory in `risk.py`).
* **A skill:** add it to `curriculum/skills.py` (mark `planned=True` until it has questions).

## Roadmap

Done: dates and calendar, dual-curve (ESTR-OIS + 6M) and 3M bootstrap, forward-start swaps, FRAs, basis swaps, first-order vs
full-revaluation split, convention matrix and worked examples, carry / roll-down / breakeven / warehousing / attribution,
asset swaps, swap spreads, cash-vs-swaps hedging, repo and specialness, bond carry and roll-down,
**Bund-family futures (conversion factors, DV01 and hedging, CTD as a ranking, CTD switches, implied repo, the basis trade) and 3M Euribor futures strips**.

Next, in suggested order:

1. **Stateful market-making episodes:** levels 1-5 built (`docs/EPISODES.md`): one trade; an inventory loop; a curve book; hedging with futures
   and bonds and holding risk overnight; information, views and changing conditions. The user interface is the next design step.
2. **Curve shape and interpolation (engine side):** front-end humps and what the sawtooth in log-linear forwards does to roll-down and DV01 (this is where the 2Y floating-reset
   effect belongs). The TRAIN questions on interpolation exist (`math.interp_log_linear`); alternative interpolators in the engine do not.
3. **Portfolio scenarios (engine side):** mixed swap/bond/future books in one risk report. TRAIN has bucketed swap books and multi-factor shocks (`portfolio.bucket_book`, `portfolio.scenario_pnl`); a book mixing
   bonds and futures with the swaps is still to be built.
4. **Attempt log + review queue** (a plain record, not adaptive). The stateful market-making episodes now exist and their frontend boundary is frozen
   (`docs/EPISODES.md` section 19); the user interface is designed in `docs/UI.md` (not yet built; CLAUDE.md, "UI-agnostic core").
5. Later, if wanted: a traditional EUR ASW over 6M Euribor (adds the Euribor-ESTR basis), ESTR futures, end-game/wildcard delivery options.
