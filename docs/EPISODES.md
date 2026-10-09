# Stateful market-making episodes: design

Status: **levels 1-5 implemented** (`src/rates_trainer/episodes/`, `marketmaking/flow.py`, `episode_session.py`; play with
`./trainer episode -L N`). Section 16 records levels 1-2 as built; section 17 is the agreed design of levels 3-5; section 18 records
levels 3-5 as built, with the assumptions and choices made where section 17 left details open; section 19 is the frozen frontend interface. Sections 2-15 are the
design as proposed and approved: where the code differs (file layout in section 11, the CLI flags, the transcript replay), sections 16-19 are authoritative. This document sits beside `docs/DESIGN.md` and follows its conventions (DV01 = P&L for
a 1bp fall; bid = dealer pays fixed; offer = dealer receives fixed).

The loop the episodes train:

    Fair Value → Quote → Client Trade → Position → Risk → Skew/Hedge → Market Move → P&L → Re-quote
    Trade → Position → Risk → Hedge → Market Move → P&L

---

## 1. Principles

1. **Decisions persist.** One state object is carried through the episode. Every quote, fill, hedge and market move changes it, and later
   decisions are taken from the state that earlier decisions produced.
2. **Judge the decision on what was known when it was taken.** Every decision is assessed against the information set at that moment
   (the observation the trainee saw, plus the regime parameters the observation describes qualitatively). The realised market path is
   never an input to the grade. It is reported separately, as outcome.
3. **Four separate things are reported, never merged:**
   *decision quality* (ex ante), *risk taken* (ex ante distribution), *realised outcome* (P&L on this path), and *luck* (realised minus expected).
   A good decision can lose money and a bad one can make it, and the report says so explicitly.
4. **No single correct answer where none exists.** Hedge and quote decisions are rated *sound / defensible / poor* by whether they are efficient
   for some reasonable risk appetite (section 6), not by matching one number. Hard errors (wrong-sign hedge, crossed market, limit breach) are
   still flagged as errors.
5. **Stylised and transparent, not a simulator.** A handful of named risk factors, a simple flow model and the existing teaching quote model.
   Every parameter is visible in code and documented. Realism only where it changes a decision.
6. **The engine does the finance.** The episode layer composes engine calls (pricing, key-rate DV01, full revaluation, carry/roll, futures and bond
   analytics). It never re-implements a formula. The UI stays a thin adapter over plain data.

---

## 2. What exists and what it gives the episodes

| Existing piece | Reused as |
|---|---|
| `MarketCurves` (quotes → OIS / 6M / 3M curves, `bumped`, `shifted`, `rolled`) | the curve part of the market state; market moves are `shifted(CurveShock)`; overnight steps are `rolled(..., "static"/"forward")` |
| `CurveShock.points` | the carrier of factor moves (level / slope / curvature) onto the pillars |
| Instruments: `IRSwap`, `OISSwap`, `FRA`, `BasisSwap`, `FixedBond` (ASW, funding spread), `AssetSwapPackage`, `BondFuture`, `STIRFuture` | positions in the book; all expose `pv(market)` |
| `risk.py`: `Portfolio`, `key_rate_dv01`, `parallel_dv01`, `par_*` factories, `dv01_hedge_swap`, `solve_key_rate_hedge` | book risk at every step; hedge candidates and their sizing |
| `pnl.py`: `first_order_pnl`, `key_rate_first_order_pnl`, `revalue_pnl` | the two P&L paths at every mark |
| `carry.py`: `carry_roll`, `attribute` | overnight carry / roll-down and end-of-day attribution (level 4+) |
| `futures.py`, `stir.py` | futures as hedge instruments; CTD / net-basis behaviour as a spread factor |
| `marketmaking/quoting.py`: `Quote`, `ClientAction`, `dealer_swap`, `QuotingContext`, `make_quote` | quote mechanics; the **reference** quote (direction and width bands); competitors' ("street") quotes |
| `questions/model.py`: `NumericPart`, `ChoicePart`, `Tolerance`, grading feedback | optional calculation checkpoints inside an episode ("what is your DV01 now?"), used sparingly |
| `questions/market.py`: `random_market`, `random_futures`, `random_bond` | initial market states |
| Registry pattern `(id, seed) → object` | `(episode_id, seed) + decisions → exactly the same episode` (replay) |

Measured cost (this machine): key-rate DV01 of a whole book ≈ 0.25 s (dominated by re-bootstrapping, not by the number of instruments);
a shifted market ≈ 6 ms. So exact risk and full revaluation at every step are affordable; ex-ante distributions use first-order risk × factor
scenarios (linear algebra, milliseconds).

## 3. What is missing

1. A **mutable episode state** (market, book, limits, regime, ledger, history). Today everything is a one-shot `QuestionBody`.
2. **Spread factors outside the curve.** A bond's ASW lives on the instrument; a future's price offset on the `BondFuture`. To move "swap spreads"
   or "the futures basis" as market factors, the episode needs a market-level spread overlay (section 4.1).
3. A **factor model** for market evolution with a covariance, so that risk can be expressed as a P&L standard deviation and hedges compared
   by the residual risk they leave.
4. A **client flow model** that reacts to the trainee's quote (fill probabilities) and can be informed (adverse selection).
5. **Typed decisions** and an **assessment** layer (ex ante) separate from the **outcome** layer (ex post).
6. A **P&L ledger** that explains every euro: edge at fill, hedge costs, market-move P&L by factor (first order and full), carry, convexity/residual.
7. An **episode runner** (UI-agnostic step API) and a thin terminal adapter. An episode registry beside the question registry.

Nothing in the engine has to change for levels 1-3. Level 4 (bonds/futures as hedges with spread factors) needs only the overlay in 4.1, which
lives in the episode layer.

---

## 4. State model

New package `src/rates_trainer/episodes/` (sits above `engine/`, `marketmaking/` and `questions/`; nothing below imports it).

```python
@dataclass(frozen=True)
class Regime:                        # what the trainee is told, qualitatively, and what drives the generators
    vol: float                       # 0.6 calm / 1.0 normal / 1.8 stressed: scales factor vols
    liquidity: Liquidity             # DEEP / NORMAL / THIN: scales street width and hedge cost
    flow_bias: float                 # -1..1: expected client direction (+ = clients pay fixed, dealer gets long duration)
    flow_predictability: float       # 0..1: how reliably the bias materialises
    informed_share: float            # 0..1: fraction of clients whose trade predicts the next move
    signal: Signal | None            # a market view the trainee is given, with its stated reliability
    event: Event | None              # e.g. a data release between steps k and k+1 (a vol jump, known in advance)

@dataclass(frozen=True)
class MarketState:
    curves: MarketCurves             # engine object; moves via .shifted(), time via .rolled()
    spreads: dict[str, float]        # overlay: {"asw:<bond id>": decimal, "fut:<code>": price offset, "repo:<bond id>": funding spread}
    street: dict[str, Quote]         # competitors' quotes per instrument key (the interdealer screen)
    clock: Clock                     # date + intraday step (morning / midday / afternoon / close)

@dataclass(frozen=True)
class Position:
    key: str                         # "IRS10Y#3": instrument family + tenor + fill number
    inst: Instrument                 # the engine object, struck at the fill rate/price
    origin: str                      # "client" | "hedge" | "initial"
    fill: Fill                       # time, rate/price, notional, edge at fill (vs mid), hedge cost paid

@dataclass(frozen=True)
class Book:
    positions: tuple[Position, ...]
    def materialise(self, m: MarketState) -> Portfolio    # instruments re-bound to the current spread overlay

@dataclass(frozen=True)
class Limits:
    dv01: float                      # |parallel DV01| limit
    bucket: dict[int, float] | None  # optional per-tenor (key-rate) limits, level 3+
    spread01: float | None           # optional ASW / basis limit, level 4+

@dataclass(frozen=True)
class EpisodeState:
    step: int
    market: MarketState
    book: Book
    limits: Limits
    regime: Regime
    ledger: tuple[LedgerEntry, ...]  # every euro of P&L with its cause
    history: tuple[StepRecord, ...]  # observation, decision, assessment, outcome per step
```

State is **immutable**: each step returns a new `EpisodeState`. That makes replay, counterfactuals ("what if you had fully hedged at step 2")
and testing trivial: a counterfactual is the same transition function applied to a different decision.

### 4.1 Spread overlay (the one structural addition)

`Book.materialise` re-binds instruments to market-level spreads before pricing: a bond position is priced as
`bond.with_asw(spreads["asw:<id>"])` (and `funding_spread` from `repo:`), a `BondFuture` with `price_offset = spreads["fut:<code>"]`.
Curve risk is then the engine's `key_rate_dv01` on the materialised portfolio; spread risk is a bump of the overlay entry (one line: reprice
with the spread +/-0.5bp). The engine stays exactly as it is.

---

## 5. Episode lifecycle

```
Episode(spec, seed)
  ├─ initial_state()                         market, book (possibly non-empty), limits, regime
  └─ loop over the spec's stages:
       observe(state)      -> Observation      plain data: screen, book risk, limits, regime text, what is being asked
       decide              <- Decision         from the trainee (UI) or a policy (tests, counterfactuals)
       assess(state, d)    -> Assessment       EX ANTE only: errors, consistency, efficiency, distribution
       apply(state, d)     -> state'           fills hedges, records quote
       events(state')      -> state''          client arrival + fill, market move, time passing (seeded, see below)
       report(state, state'') -> Outcome       EX POST: what happened and the P&L explain (both paths)
  └─ debrief(history)  -> Debrief              decision quality vs outcome vs luck; counterfactual policies on the same path
```

A **stage** is one of `Quote`, `RespondRFQ`, `Hedge`, `Mark` (observe P&L and risk, optional checkpoint question), `Overnight` (roll + carry).
An episode spec is a list of stages plus generator settings, so level 1 and level 5 differ only in their specs.

**Determinism and fairness.** Three independent random streams per episode, each seeded from `(episode_id, seed, stream name)`:
`market` (factor moves, events), `arrivals` (which client comes, side, size, informed or not) and `fills` (one uniform per arrival).
None of them depends on the trainee's decisions. So the market path is the same whatever the trainee does, and a counterfactual policy faces
exactly the same clients and the same uniform draws (common random numbers): differences in outcome are caused by decisions, not by luck.
Whether a client trades with you depends on your quote through the fill probability, compared with that fixed uniform.

**Replay.** An episode transcript is `(episode_id, seed, [decisions])`; it is enough to regenerate everything. That is also the record the
roadmap's attempt log will store.

---

## 6. Decisions and how they are graded

### 6.1 Decision types

| Decision | Input | Notes |
|---|---|---|
| `QuoteTwoWay(instrument, bid, offer)` | two rates, or `skew bp + half-width bp` relative to the screen mid | the core market-making decision |
| `RespondRFQ(instrument, side, level \| pass)` | one price for the side the client asked for | level 2+: more realistic D2C swap flow |
| `Hedge(trades)` | zero or more `(hedge instrument, signed size)` from a menu, or "warehouse" | menu: pillar IRS, OIS, 3M futures strip, Bund/Bobl/Schatz, a bond; each with its own cost |
| `Checkpoint(answer)` | a `NumericPart` / `ChoicePart` answer | optional; at most one or two per episode, never "DV01 after every trade" |

Convenience inputs (UI only): "hedge 50%", "hedge fully in the 10Y", "flatten the 2Y bucket". They are translated into explicit `Hedge` trades
before assessment, so the assessment always sees real instruments and sizes.

### 6.2 Three layers of assessment (all ex ante)

**(a) Errors, binary.** Crossed or inverted quote; a hedge with the wrong sign (adds risk); a decision that breaches a limit or leaves a breach
uncorrected; a quote that lets the street arbitrage you (bid above the street offer). These are the only "wrong answers".

**(b) Consistency with the state.** For quotes, compared with the reference `make_quote` on the same context, grading *direction and relative
size only*, as the existing `mm.skew_and_width` template does:
* skew direction: when the reference net shift is crisp (|shift| ≥ a threshold), the trainee's shift must have the same sign; when it is near
  zero, any small skew is fine;
* width: wider, same or narrower than a normal day, in line with vol, liquidity and informed share (bands, not a number);
* the side being encouraged must be the one that reduces risk (or matches the stated view when risk is small).

For hedges: sign, and whether the instrument's risk *profile* matches the book (a 2Y hedge on a 10Y position is flagged as creating curve risk,
not as wrong).

**(c) Efficiency: risk against reward, over a band of risk appetites.** Every decision is placed among a small set of **candidate decisions**
generated from the same state (for a hedge: warehouse, 25/50/75/100% in the same tenor, the best key-rate hedge, a futures hedge, a cheaper
neighbouring tenor; for a quote: the reference quote, symmetric, more/less skewed, wider/narrower). For each candidate the assessor computes,
from the state at decision time only:

* `E`: expected P&L to the next mark: edge expected from fills (fill probability × half-spread) − hedge cost (half the bid/offer crossed ×
  |DV01|) + carry/roll (overnight stages) + expected drift (signal × its stated reliability; adverse selection × informed share);
* `σ`: standard deviation of the P&L to the next mark, from the book's key-rate and spread exposures and the factor covariance (section 8):
  `σ² = xᵀ Σ x`;
* `P(limit)`: probability the expected inventory after flow breaches the limit.

A decision is then rated:

| Rating | Meaning |
|---|---|
| **Sound** | for some risk appetite λ in the scenario's band `[λ_lo, λ_hi]`, its mean-variance utility `E − λσ²/2` is within a small tolerance of the best candidate |
| **Defensible** | not optimal for any λ in the band, but within a wider tolerance, or a different (consistent) trade-off, e.g. a cheaper hedge that leaves stated curve risk |
| **Poor** | dominated: another candidate has higher `E` and lower `σ` by a margin, for every λ in the band; or a binary error |

The λ band is the honest way of saying "partially hedging, fully hedging or warehousing can all be right". It is derived from the scenario: a
calm, liquid market with offsetting flow expected gives a low λ (warehousing efficient); limit pressure, thin liquidity or informed flow raise it.
Tests check that the reference policy is always at least *defensible*, and that obviously bad decisions (doubling the risk, hedging the wrong way,
paying a large cost to remove tiny risk) are *poor* for every λ in the band.

The assessment is shown with its numbers ("your hedge: cost €18k, residual σ €42k, 2s10s exposure €-35k/bp. Full 10Y hedge: cost €30k, σ €6k.
Warehouse: cost 0, σ €210k, 31% chance of breaching the limit on expected flow"). The trainee sees the trade-off they chose, not just a verdict.

### 6.3 Outcome, luck and the debrief (ex post)

After each step: fills, the market move (by factor), the P&L explain (section 9), new risk and limit usage.
At the end:

* **Decision card:** ratings per decision, errors, and the reasons.
* **Outcome card:** total P&L, split into edge earned, hedge costs, carry, and market P&L by factor (level, curve, spread, basis), plus the
  convexity/residual term. Both first-order and full-revaluation numbers.
* **Luck:** realised P&L minus the sum of ex-ante expectations, expressed in σ ("you were 1.4σ unlucky: the 10Y sold off 9bp against your warehoused long").
* **Same path, other policies** (common random numbers): what the reference policy, "always hedge fully" and "never hedge" would have made on this
  exact path; and, over a few hundred simulated paths (first-order P&L, milliseconds), their mean and spread. This is how a trainee sees that
  a decision that lost money today was still the better decision, or the reverse.

---

## 7. Client flow

One client inquiry per quoting stage (deterministic count keeps the episode readable); the inquiry may or may not trade.

* **Who arrives** (`arrivals` stream): side drawn with `P(client pays) = ½ + ½ · flow_bias · flow_predictability` (plus a background
  uninformed coin when predictability is low); size from a size ladder by tenor; informed with probability `informed_share`.
* **Does the client deal with you** (`fills` stream): the client compares your price on its side with the street price (from competitors' quotes, built with
  `make_quote` on randomised competitor inventories). `P(fill) = logistic((street − yours) / s)` in bp of rate (for a paying client, a lower offer
  is better), with `s` the client's price sensitivity: real-money clients are sensitive, informed clients much less so (they need to trade).
  The uniform from the `fills` stream decides. So skewing higher makes your bid attractive and *raises the probability* that a receiving client trades
  with you: the consequence is probabilistic and visible.
* **Informed flow**: an informed client's trade predicts the next market move in its favour by `κ × size` bp (section 8). Its cost to the dealer is
  therefore known *in expectation* at quote time from `informed_share` (which the observation describes as "flow quality"), and it is part of
  `E` in the assessment. This is the "getting flow vs protecting against adverse selection" trade-off with numbers behind it.
* **RFQ variant (level 2+):** the client asks for one side; you show one level or pass. Winning is a function of your level against the
  best competitor's (one fills uniform). This is closer to how D2C swap flow arrives and makes the width decision sharper.

## 8. Market evolution

A small, named factor model (stylised, documented, deterministic given the `market` stream):

| Factor | Moves | Normal vol (bp per day) |
|---|---|---|
| level | all OIS and Euribor par quotes together | 5 |
| slope | 2s30s twist (loadings −1 at 2Y … +1 at 30Y) | 2 |
| curvature | belly vs wings | 1 |
| Euribor-OIS basis | Euribor quotes only (`shifted(..., curves=("E6M",))`) | 0.4 |
| swap spread / ASW | the `asw:` overlay of every bond, common factor + small idiosyncratic | 0.8 |
| futures net basis | the `fut:` overlay (and CTD switching follows from curve moves through the engine) | 0.3 ticks |

Per step the factors move by `vol × regime.vol × √(step length)` times independent normals, plus:
* **informed drift** after an informed client fill (section 7);
* **signal drift** when the scenario gives the trainee a view: the expected move equals the stated view times its stated reliability, so a
  "55% reliable" view is worth trading a little and a "90% reliable" view a lot (and acting on a view is assessed on `E` and `σ`, not on whether
  the move happened);
* **events:** a known data release between two steps multiplies that step's vol; the trainee knows it is coming (it is in the observation), so widening or
  hedging before it is assessable ex ante.

The covariance `Σ` used for `σ` in the assessment is the same model's (loadings × vol²), so the risk the trainee is shown and the moves that
happen are consistent. Pillar-level moves are carried to the curves with `CurveShock.points`.

**Time.** Most stages are intraday (no carry; step length a fraction of a day). An `Overnight` stage rolls the market with `rolled(..., "static")`
(or forwards realised) and books carry and roll-down from `carry.py`, so warehousing has a visible daily cost or benefit.

## 9. Risk and P&L at every mark

* **Risk:** parallel DV01, key-rate DV01 by tenor bucket (engine), spread01s from the overlay, limit utilisation; and the σ of the book over
  the next step.
* **P&L explain** for each step, every euro accounted for in the ledger:
  `edge at fills + hedge cost + Σ_factors (−exposure × move) [first order] + convexity/residual [= full revaluation − first order] + carry`.
  Both paths are shown, as everywhere else in the trainer. A hedge that "failed" shows up as a non-zero curve, spread or basis line with the
  exposure that caused it (e.g. a 10Y swap hedged with Bund futures loses on the swap-spread factor; a 10Y hedged with a 5Y loses on slope).
* **Invariant (tested):** the ledger sums to the full-revaluation change of the book plus cash, to rounding.

## 10. Progression

*Levels 1-2 are built (section 16). Rows 3-5 are the original sketch; section 17 is the detailed design that supersedes them.*

| Level | Instruments | New idea | Typical stages |
|---|---|---|---|
| **1. One trade** | 10Y IRS | quote → fill → position → DV01 → hedge or warehouse → move → P&L, decision vs outcome | Quote, Hedge, Mark (≈3 decisions) |
| **2. Inventory loop** | one tenor | skew to work inventory, expected flow, limit pressure, re-quote after fills; hedge vs wait for offsetting flow | 4-6 × (Quote, optional Hedge, Mark) |
| **3. Curve book** | 2/5/10/30Y IRS, OIS, 3M strip | key-rate risk; choosing the hedge tenor; slope/curvature moves; Euribor-OIS basis | as 2, with a hedge menu and bucket limits |
| **4. Cross-product** | + bonds, ASW, Bund/Bobl futures, repo | cheap-but-imperfect hedges (futures: spread and CTD risk), spread factors, overnight carry and repo | as 3, plus Overnight |
| **5. Information and regime** | any of the above | informed flow, signals with stated reliability, events, stressed vol; quoting for liquidity vs for risk | mixed; RFQ responses |

Each level is a few episode specs with randomised parameters, so the same episode id gives different markets and flows across seeds, as the question
templates do. Level 1 and 2 cover `mm.requote_loop` (planned today) and deepen `mm.skew`, `mm.client_trade`, `mm.hedge_vs_inventory`; level 3
activates `risk.key_rate`; levels 4-5 are the bridge to the `portfolio.*` skills.

**A level-1 episode, concretely.** Screen: 10Y mid 2.845%, street 2.843/2.847, flat book, limit €500k DV01, normal vol, deep liquidity,
two-way flow. *Quote* → trainee shows 2.843/2.847 → a client pays €300m (fill drawn against the street) → book: receive fixed, DV01 ≈ +€260k,
edge ≈ €52k. *Hedge* menu: warehouse / 50% / 100% in the 10Y (cost 0.1bp × DV01) / 100% in 5Y (cheaper, leaves slope risk) → assessment shows E, σ and
the curve exposure each leaves; with a deep market and two-way flow both 50% and 100% are sound, warehousing is defensible, the 5Y is defensible
with a stated slope risk. *Market* moves +4bp level, +1bp slope → explain: edge, hedge cost, level P&L, slope P&L, convexity; luck vs the decision.

## 11. Architecture

```
engine/          unchanged (deterministic finance)
marketmaking/    quoting.py unchanged; + flow.py (fill probability, street quotes) — pure functions
episodes/        NEW
  state.py       Regime, MarketState (+ spread overlay), Position, Book, Limits, EpisodeState, Ledger
  factors.py     factor definitions, covariance, factor move -> (CurveShock, spread changes)
  generators.py  seeded streams: market path, arrivals, fills uniforms
  decisions.py   typed decisions + parsing helpers (no I/O)
  assess.py      candidates, E / σ / P(limit), errors, consistency, rating over the λ band
  explain.py     ledger and P&L explain (both paths), risk report
  episode.py     EpisodeSpec, stages, transition function, debrief, replay
  specs/         level 1-5 episode specs
episode_session.py   thin terminal adapter (renders Observation / Assessment / Outcome; reads Decisions)
cli.py               `./trainer episode [--level N] [--seed S] [--replay TRANSCRIPT]`
```

*(Proposed layout. As built: `state.py factors.py evidence.py products.py decisions.py assess.py episode.py specs.py` plus, for the frontend boundary,
`serial.py views.py render.py api.py` (section 19); the CLI is `./trainer episode -L N [--seed S]`; replay is by decision record, section 19.4.)*

Changes outside the new package: a `flow.py` module beside `quoting.py`; a small CLI subcommand; skill flags. No changes to the engine, the question
model or the existing templates. Episodes get their own registry (`EpisodeSpec` with skill tags), so `./trainer list` can show them beside questions.

## 12. Validation

* **Determinism / replay:** same `(id, seed, decisions)` → identical transcript; different decisions → identical market path and arrivals.
* **Conservation:** the ledger equals the full-revaluation change of the book plus cash at every step; first-order + residual = full.
* **No hindsight (structural test):** the assessment of every decision is identical under two different `market` seeds.
* **Assessment sanity:** reference policy ≥ defensible on many seeds; wrong-sign hedges, doubled risk, crossed quotes, breaching quotes → poor or error; raising
  vol or informed share widens the reference width and raises λ; σ from `Σ` matches the dispersion of simulated first-order P&L.
* **Flow model:** fill probability decreases monotonically in the distance from the street on the client's side; skewing higher raises receiving
  fills and lowers paying fills; informed flow carries the stated expected drift (checked by simulation).
* **Mutation checks** on the sign conventions (skew direction, fill side, hedge sign, factor loadings, ledger signs), as for every other layer.

## 13. Implementation plan (after agreement)

1. **State, factors, generators, ledger, explain** + tests (conservation, determinism, no-hindsight harness).
2. **Flow model** (`marketmaking/flow.py`) + tests.
3. **Assessment** (candidates, E/σ, λ band, ratings) + tests on hand-built states.
4. **Episode runner + terminal adapter**; **level 1 and level 2** specs; activate `mm.requote_loop`.
5. Level 3 (multi-tenor, hedge menu, bucket limits, basis).
6. Level 4 (spread overlay with bonds and futures, overnight carry/repo) and level 5 (informed flow, signals, events).

Stop for review after step 4: levels 1-2 working end to end are the test of whether the design teaches what it should.

## 14. Deliberately out of scope

Adaptive difficulty, speed, gamified scoring, live data, an order-book or agent-based market simulator, optimal-market-making formulas presented as truth,
and the final UI (CLAUDE.md "UI-agnostic core"). Scores in the debrief are diagnostic (ratings and P&L explain), not points.

## 15. Choices worth confirming

1. **Two-way quotes first, RFQ responses from level 2.** Two-way quotes match the CLAUDE.md examples and teach skew most directly; RFQs are more
   realistic for D2C swaps. Both are planned; the order is the question.
2. **Rating by efficiency over a λ band** rather than a single target. It needs one parameter band per scenario, documented; the alternative
   (pure rules) cannot express "several hedges are fine".
3. **One client inquiry per quoting stage.** Keeps episodes short and readable; a Poisson arrival process adds noise without teaching more.
4. **Intraday by default, overnight from level 4.** Carry only becomes material over days; introducing it later keeps levels 1-3 focused on flow and risk.

---

## 16. As built (levels 1-2)

**Levels.** `mm.ep1_single_trade` (skill `mm.hedge_vs_inventory`): one two-way quote, one client, one DV01 checkpoint (after a fill),
one hedge decision, one market move, debrief. `mm.ep2_inventory_loop` (skill `mm.requote_loop`): five single-sided client requests
(price or pass), each followed by a hedge decision and a market move, carrying the book and P&L throughout. Focus tenor 5Y, 10Y or 30Y;
hedges in the focus tenor and its neighbours, or any explicit legs (`pay 100m 10y + receive 40m 30y`).

**Refinements agreed at review, and how they are implemented.**
* *Benchmarks, not an optimum.* Each hedge decision is shown with the table of alternatives (E, sigma, rating). Several are usually sound
  at once: in a 40-seed sample about 80% of hedge decisions had two or more sound alternatives.
* *Decision quality separate from outcome.* The decision card, the outcome (P&L by cause), luck (realised minus expected, in sigma of the
  uncertainty left: fills and market) and the same-path policy comparison are separate debrief sections.
* *Factors as a training abstraction.* Stated in `factors.py`; level, slope and curvature only at these levels.
* *Uncertain informedness.* The trainee sees a client type and its description, never the flag. Types carry a probability of being
  informed (corporate 2% ... fast money 60%); the assessment uses that probability, the market uses the flag, the debrief reveals it.

**Assumptions the assessment makes (all in code, all tested for direction):**

| Assumption | Value | Where |
|---|---|---|
| Risk appetite band | R from 0.3 to 1.5 x (limit x one-step normal-vol level move); utility E - sigma^2/2R | `assess.R_BAND`, `r_ref` |
| Rating gaps | sound <= 0.20, defensible <= 0.60 of the cost of a full hedge, at the most favourable R | `SOUND_GAP`, `DEFENSIBLE_GAP` |
| Cost of keeping a position | `c x (E|level + N| - E|N|)`, N = rest of the day's net client flow ~ Normal(expected flow, typical trade x sqrt(4 x 0.4)) | `exit_cost` |
| Informed drift | a level move of 1.5bp x regime vol in the client's favour, expected value = P(informed | type) x 1.5bp x vol | `INFORMED_DRIFT_BP` |
| Fill probability | logistic in your price improvement over the street; p at the street 35-50%, sensitivity 0.10-0.35bp by type | `flow.CLIENT_TYPES` |
| Factor vols (normal, per day) | level 5bp, slope 2bp, curvature 1bp; x 0.6 / 1.0 / 1.8 by regime; steps of 1-2 hours | `factors.FACTORS` |

The exit-cost term is what makes warehousing a real choice: a small position is mostly netted away by the day's two-way flow (nearly
free to keep), a large one is not (it costs almost a full hedge later, plus its risk now). An earlier draft charged every position the
full hedge cost later, which made warehousing always inferior; another credited only the skew-induced expected reduction, which is zero
for random two-way flow. The convex form above is the right economics and is tested.

**Commit before reveal (review change).** Before a hedge decision the trainee sees only what a desk would know: mid and street, the last
inquiry and how it ended, the book, limit use, any curve position, P&L so far, conditions and desk expectations, and the hedge instruments with
their DV01 per €1m and their cost to cross. The verdict, the benchmark alternatives (E, sigma, rating) and residual risks are revealed only in the
result of `submit()`, before the outcome of the market move. A test asserts that no observation can contain assessment content.

**Departures from the proposal.**
* The spread overlay (section 4.1) is not needed until bonds and futures enter (level 4), so it is not built.
* Ex-ante distributions over simulated paths are not shown; each decision shows E and sigma, and the debrief compares policies on the
  same path. (The many-path comparison was added at level 5 only, section 18.)
* `MarketState` is the engine's `MarketCurves` plus the street quote derived from it; the regime carries the rest.

**Validation (tests/episodes/).** Exact replay; clients, fills' uniforms and the market path identical under different policies; fills are the fixed uniform
against the decision-dependent probability; assessments of everything before the first move identical under different market paths and
with every informed flag flipped (no hindsight, structurally); informed drift exactly as stated; ledger equals the full revaluation of the book
and the convexity/cross term is second order; luck centred on zero across paths; the reference policy never poor and mostly sound; ending over
the limit and hedges that add risk are errors; warehousing sound for a small calm position and poor for a large stressed one; offsetting
expected flow and two-way netting behave as stated; a neighbouring-tenor hedge names its curve position and a level-and-curve hedge removes it;
wrong-way skew poor, crossing the street an error; skewing up attracts receivers; RFQ rules (axe, breach, through mid; informed-looking clients
priced wider); parsing; the terminal adapter and CLI.

Mutation checks (15, all caught): fill-improvement sign, factor-exposure sign, hedge direction, wrong-way-hedge flag, expected-flow sign in the
exit cost, skew-direction check, expected and realised informed-drift signs, limit-breach test, rating at the worst instead of the best appetite,
a 100x too relaxed risk appetite, the fill comparison, hedges executed at a profit, a dropped convexity/cross term, and a leak of the informed
flag into the assessment.

---

## 17. Levels 3-5: detailed design (approved; built as recorded in section 18)

### 17.1 The spine of the progression

Each level adds **one new axis of judgement** to a loop the trainee already runs fluently. They are not longer versions of the same episode.

| Level | The question the trainee learns to answer | What they can already do | What is new |
|---|---|---|---|
| 1 | "This trade gave me risk. Do I keep it?" | — | position → DV01 → hedge cost vs risk; decision vs outcome |
| 2 | "How do I price the next client given what I hold?" | L1 | inventory over time, axes, passing, limits, flow as a hedge |
| **3** | "What *shape* is my risk, and where should I hedge it?" | L2 | risk is a vector (level and curve); cross-tenor netting; hedge-tenor choice |
| **4** | "Which *product* should carry my hedge, and for how long?" | L3 | hedges are trades with their own risks (swap spread, futures basis), costs and carry; holding risk overnight |
| **5** | "*Why* am I moving my price: inventory, information or conviction?" | L2-L3 | inferring informed flow from evidence; views with stated reliability; events and regime change |

Two design rules follow. (1) Each level keeps the episode at 5-7 decision points; complexity goes into the decisions, not the count.
(2) A level introduces only the products and state its new axis needs. Level 5 deliberately returns to a swaps-only book (with the level 3 hedge
menu) so that the new difficulty is judgement, not bookkeeping; level 4's products are not carried into level 5.

Unchanged at every level: commit-before-reveal; decision quality, outcome and luck kept separate; the four seeded streams (setup, arrivals, fills,
market) drawn before any decision, so that same-path counterfactual policies remain exact; the efficiency band for hedges and consistency grading for
prices; first-order and full-revaluation P&L side by side; one optional calculation checkpoint per episode.

### 17.2 Level 3: the curve book

**Learning objective.** Read a multi-tenor book as exposures to level and curve; price a client in one tenor by what the trade does to the
*whole* book; choose where to hedge (and whether to keep curve risk deliberately) knowing that tenors differ in cost.

**New concepts and decisions.** Bucketed (key-rate) DV01; level and slope exposure of a book; "risk-equivalent" position (my book behaves like
X of 10Y); cross-tenor netting (a client paying 2Y offsets a 10Y receiver's level, not its curve); natural hedges from flow; a curve limit;
hedge-tenor selection, including a two-leg level-and-curve hedge.

**Structure (5 rounds, ~10 decisions).** Start with a book of 2-3 positions in different tenors with a non-trivial curve profile. Each round: a
client request in one of 2Y / 5Y / 10Y / 30Y → price or pass → hedge decision (menu: any of the four tenors by percentage of DV01, "flatten the
X bucket", explicit legs) → market move with meaningful slope and curvature. One checkpoint, after round 2: "what is your slope exposure?" (or a choice:
"you are long level and short the curve / ..."). Two specs with different structural flow so the curve inventory builds differently:
* *LDI morning*: pension funds receive 30Y, real money mixed in the belly;
* *corporate hedging*: corporates pay or receive 5-10Y around issuance, bank treasuries in 2-5Y.

**Shown before each decision.** The four-tenor screen (mid, street, cost to cross); the book by position and by bucket (engine key-rate DV01
summed into 2/5/10/30 buckets); level and slope exposure; total-DV01 and curve-limit use; the inquiry. *Not* shown: the risk-equivalent of the
incoming trade (working that out is the skill), sigma, the benchmarks.

**New state.** Per-tenor street and costs; bucketed risk; `Limits(dv01, slope)`; inquiries carry a tenor; client types gain a tenor preference.

**Client flow.** As level 2 (RFQs, fill model, informedness by type) plus tenor: each type draws a tenor from its own preference, and the specs set
a structural direction per tenor (e.g. receivers in 30Y). Netting opportunities therefore arise naturally rather than by script.

**Assessment.**
* *Prices*: the reference quote uses the book's **risk-equivalent inventory in the inquiry's tenor**: the DV01 in tenor T with the same
  variance-minimising relationship to the book, `beta_T = Cov(book, unit swap T) / Var(unit swap T)` from the factor covariance. A 2Y client who
  offsets a 10Y long therefore gets an aggressive price even though the 2Y bucket was flat; a trade that adds curve risk near the curve limit gets a
  wider one. Grading stays direction and relative size.
* *Hedges*: the same efficiency band; candidates become level-only hedges in each tenor, bucket flattening, the level-and-curve two-leg hedge and
  warehousing. Errors add "over the curve limit after the decision".
* Reasons name the curve position left, and whether a cheaper hedge tenor was chosen deliberately or by accident (the trade-off is shown after commitment).

**Debrief.** As now, plus a round-by-round table of level and slope exposure (did you run curve risk on purpose?), P&L by factor per round, flow that
netted risk for free, and same-path policies: hedge level in the 10Y only (cheap, runs the curve), hedge each bucket, never hedge, reference.

**Builds on level 2** by replacing "how much DV01" with "which risk": the loop is identical, the state has one more dimension.

**Reuse.** `key_rate_dv01` (buckets), `FactorRisk` (level/slope/curvature are already the right factors), `level_and_slope_hedge`, the efficiency
band, the flow and quote models, policies.

**Genuinely new.** Multi-tenor inquiries and street; risk-equivalent (beta) inventory; the curve limit; the generalised hedge candidate generator;
bucket display; client tenor preferences; the slope checkpoint.

**Open choices (recommendation first).**
1. *Reference inventory for a multi-tenor quote*: **risk-equivalent (beta)** / the inquiry tenor's bucket DV01 (misses netting across tenors) /
   total DV01 (ignores the curve).
2. *Limits*: **total DV01 plus one slope limit** (two numbers, teaches the two dimensions) / per-bucket limits (realistic but four numbers to track).
3. *Instruments*: **IRS in four tenors only** / adding OIS and the 3M strip (brings Euribor-OIS basis, which belongs with level 4's "a hedge has its
   own risk" and would dilute level 3).
4. *Pricing format*: **single-sided requests, as level 2** / two-way runs across tenors (four quotes per round: more typing, little extra learning).

### 17.3 Level 4: hedging with other products, and holding risk overnight

**Learning objective.** A hedge is a trade: choose the instrument by what it costs, what risk it leaves behind, what it carries, and how long you
expect to hold it. Hold a book overnight knowing its carry, roll-down and funding.

**New concepts and decisions.** Hedging swaps with Bund/Bobl futures (cheapest and most liquid, but they leave swap-spread risk and futures-basis
risk, and the CTD can switch); hedging with a government bond (needs repo; shorting a special bond is expensive); CF-weighted sizing; carry, roll-down and
funding of the book overnight; liquidity that changes through the day (late in the day swaps are expensive and futures are not); *re-hedging*:
switching a temporary futures hedge into swaps when liquidity returns, or keeping it.

**Structure (two trading days, ~8 decisions).**
* *Day 1, late afternoon* (3 rounds): swap client requests; hedge menu = swaps (wide: thin late-day liquidity), Bund or Bobl futures (tight),
  the CTD bond (repo shown, GC or special). Market moves now include the swap-spread and futures-basis factors.
* *Close*: an **overnight decision**: what to carry (keep, reduce, switch hedges), with the book's overnight carry + roll-down + funding on an
  unchanged curve shown (a desk risk system shows it), and any scheduled overnight event.
* *Overnight*: the market rolls one business day (static curve) and moves (overnight vols); P&L booked as carry, roll-down, funding, level, curve,
  swap spread, futures basis and residual.
* *Day 2, morning* (2 rounds): liquidity is back; a **re-hedge decision** (switch futures into swaps, at a cost, or keep the spread risk), then a client request.

**Shown before each decision.** Swaps screen; futures price, CTD, CF, DV01 per contract, tick cost; the bond's price, yield, ASW and repo (GC or
special) and bid/offer; the book's exposures to level, slope, swap spread (EUR per bp of ASW) and futures basis; limits; session liquidity; overnight
carry/roll/funding of the current book. Not shown: sigma, benchmarks.

**New state.** The **spread overlay** of section 4.1 (bond ASW, futures price offset) with positions materialised against it; a `Clock` (day,
session); futures and bond positions; repo funding; session-dependent costs; new factors: swap spread (common ASW move, which also moves the futures
through their CTD) and futures net basis (noise on the price offset); optionally Euribor-OIS basis.

**Client flow.** Swap requests only, as level 3 (single tenor or two neighbouring tenors). The cross-product element enters through the hedges,
which keeps the number of new things to one.

**Assessment.** Hedge candidates across products: swaps (same / neighbouring tenor), futures (CF-weighted size), bond, combinations; E now includes the
expected carry, roll-down and funding to the next mark and the expected cost of switching later; sigma includes the spread and basis factors. The
overnight decision is assessed on the same band with the overnight horizon (bigger vols, carry). Errors: wrong-sign futures hedge, contracts sized by
face instead of DV01 (shown as a large residual), ending over a limit. Reasons name residual swap-spread and basis risk explicitly.

**Debrief.** P&L by factor including swap spread, futures basis, carry, roll-down and funding; "why your hedge worked or failed" (e.g. "the futures hedge
lost €38k when swap spreads tightened 3bp: that is the spread risk you chose when you paid less to hedge"); same-path policies: swaps only, futures then
switch into swaps next morning, futures and keep, never hedge.

**Builds on level 3**: level 3 chose the *tenor*; level 4 chooses the *product* and the *holding period*, and introduces the first risk that is not a
rate (swap spread).

**Reuse.** `BondFuture` (price from the curve, contracts, DV01, CTD), `FixedBond` (ASW, funding spread, mid-period valuation), `carry.py`
(carry, roll-down, funding for swaps and bonds), `MarketCurves.rolled`, `random_futures` (a basket consistent with the swap curve), the factor-risk
and efficiency machinery.

**Genuinely new.** The spread overlay and materialisation; the two spread factors and their vols; the overnight step with a mixed-product carry ledger
(the carry module does not cover futures: their overnight change is the convergence of the forward, booked as "futures carry" by revaluation); session
liquidity; the product hedge menu and its costs; parsing "sell 300 FGBL", "short 50m of the CTD"; generators that avoid coupon or payment dates
overnight (the carry module refuses to cross them).

**Open choices (recommendation first).**
1. *Products*: **Bund and Bobl futures plus the CTD bond** / adding ASW packages and the 3M strip (more products, the same lesson).
2. *Time*: **one overnight** / several days (more carry, longer episodes, little extra learning).
3. *Client flow*: **swap requests only** / adding a bond or ASW client (a second new idea in one level).
4. *Spread factors*: **swap spread and futures basis**, with Euribor-OIS basis only if the 3M strip is added / all three.
5. *30Y risk*: **hedged with swaps, or with Bund futures plus an explicit curve residual** (no Buxl in the engine) / add Buxl.

### 17.4 Level 5: information, views and changing conditions

**Learning objective.** Separate the three reasons to move a price (inventory, information, conviction) and act on each appropriately: protect
against flow that is probably informed (judged from evidence, never told); size a view by its reliability and the vol, within limits; reduce or
reshape risk ahead of scheduled events; adapt when conditions change mid-session (vol spike, liquidity drain, limit cut).

**New concepts and decisions.** Adverse selection inferred from evidence; persistent named clients; a research view with a stated track record;
scheduled events with jump vol; regime changes; an explicit **position decision** (take, keep or cut risk for a reason other than inventory), distinct
from hedging; quoting for liquidity versus for risk (tighten when you want the flow, widen when the flow is probably informed).

**Structure (one session in phases, ~7 decisions).**
1. *Morning*: a research note ("we expect 10Y to rise 3bp by the afternoon"; its stated reliability, see open choice 4), a two-way
   quote, a client request.
2. *Pre-event*: a data release in one step; a position decision (pre-position on the view, flatten, or hold) and a quote-width decision.
3. *Event*: the release (jump move).
4. *After the release*: requests from named clients, some returning for the second or third time in the same direction; the trainee has seen what
   the market did after each of their earlier trades.
5. *Late*: the risk manager cuts the limit by a third (or liquidity drains); a forced decision about what to keep.

**Shown before each decision.** As level 3 for a single focus tenor plus its hedge tenors; the research note and its track record; the event calendar;
client names with their trades today and the market's move after each (the evidence); limits and their changes; conditions. Never shown: whether a client
is informed, whether the research view is right this time, sigma or benchmarks.

**New state.** A client registry with persistent identity and a latent informed flag per client per day; the evidence history; a `Signal` (direction,
size, stated reliability, latent correctness); an event schedule (step, vol multiplier); regime changes (step, new vol / liquidity / limit).

**Client flow and market.** Named clients drawn from the type mix with a per-client latent flag (P(informed | type)); informed clients trade in the
direction of the coming move and tend to return; the market moves with the factor model plus informed drift, plus the signal's drift if the signal is
correct (drawn with its stated reliability from the market stream), plus the event's jump vol. All of it is drawn before any decision.

**Assessment.**
* *Prices*: the reference splits into its three parts and each is graded for direction and relative size: inventory skew (as before), information
  widening using the **posterior** P(informed | the evidence the trainee has seen), computed with the same model that generates the flow (so "no hindsight"
  still holds: it uses only what was observable), and a view lean of reliability x conviction (the quote model already has `view_bp`, `conviction`
  and `adverse_selection`).
* *Position decisions*: the efficiency band with E including the expected drift = view x reliability (a call either carries information, with the
  stated probability, or is noise; consistent with section 8) and sigma including any event in the horizon;
  oversizing relative to reliability and vol is poor, a sensible size in either direction of zero can be sound.
* *Limit cuts*: ending over the new limit is an error.

**Debrief.** Decisions grouped by reason (inventory / information / view); outcome by factor; revealed afterwards: which clients were informed and how the
posterior evolved against the truth, whether the view was right; luck with a **many-path distribution** for this level (where outcome noise is largest):
the reference policy's P&L over 200 paths with the same setup, and where the trainee's expected and realised P&L sit in it; same-path policies: ignore the
view, follow the view fully, ignore client evidence, reference.

**Builds on levels 2-3**: the same pricing loop, but the price now has three drivers to tell apart, and the trainee must infer one of them.

**Reuse.** The flow model (types, P(informed)), the quote model's view, conviction and adverse-selection inputs, the streams, the efficiency band, the
level 3 hedge menu.

**Genuinely new.** Client identities and evidence; the Bayesian posterior (one closed-form update per observed trade); signals and events in the market
stream; mid-episode regime changes; the position decision type; the many-path debrief (first-order P&L over simulated paths for the reference policy:
milliseconds per path).

**Open choices (recommendation first).**
1. *Book*: **single focus tenor with the level 3 hedge menu** / the full level 3 curve book (more bookkeeping, same lesson).
2. *Evidence*: **show each named client's trades today and the market move after each, but no posterior** / show a desk "toxicity score"
   (makes the inference for the trainee).
3. *Position decisions*: **allowed, within limits, assessed by the band** / not allowed (inventory only, which removes conviction from the lesson).
4. *Signal reliability*: **stated and honest** (the generator realises it at the stated rate) / stated but sometimes overstated (teaches scepticism, but
   breaks "assess on the information available"). Related wording choice: **"about 60% of this desk's calls have carried real information"** (maps exactly
   onto E = view x reliability) / a hit rate ("right 60% of the time", familiar but implies a different and smaller edge, 2 x 0.6 - 1 = 0.2).
5. *Many-path debrief*: **level 5 only** / all levels.

### 17.5 Cross-cutting decisions

* **Skills.** Level 3 → activate `risk.key_rate`; level 4 → a new skill `mm.cross_product_hedging` (prereqs `futures.dv01`, `rv.cash_vs_swaps`,
  `bonds.repo`); level 5 → `mm.adverse_selection` and a new `mm.views_and_events`. The `portfolio.*` skills stay planned until mixed books are
  questioned directly.
* **Checkpoints**: one per level (level 3 slope exposure; level 4 futures contracts for a DV01 hedge; level 5 none, or a posterior question).
* **Performance**: level 3 adds bucketed key-rate risk (~0.25s per step); level 4 adds one rolled market and carry calculations per overnight
  (~0.1s); level 5's many-path debrief is first-order (~1s for 200 paths). All within an interactive budget.
* **Validation** adds, per level: level 3 — beta inventory properties (an offsetting trade in another tenor lowers the reference charge), curve-limit
  errors, bucket sums equal parallel DV01; level 4 — materialised prices equal printed prices, CF-weighted futures hedges neutralise level and leave exactly the
  swap-spread exposure, the overnight ledger reconciles to full revaluation of the rolled and shocked book, carry signs; level 5 — the posterior against
  simulation, no hindsight with events and signals (assessments unchanged when the signal's realisation or a client's flag is flipped), view sizing monotonic
  in reliability, limit-cut errors. Mutation checks on each new sign convention.
* **Build order** (after approval): level 3, review, level 4, review, level 5.

---

## 18. As built (levels 3-5)

### 18.1 One runner, planned rounds

Levels 1-5 share one runner. A level is an `EpisodeSpec` whose `Setup` carries a `Desk` (hedge tenors, products, limits, factor set, whether
pricing uses the whole-book risk-equivalent) and a tuple of `RoundPlan`s: an optional pricing step (two-way quote or client request), one risk
decision (`hedge`, `position`, `overnight`, `rehedge`), a move (`intraday`, `event`, `overnight`), plus announcements, regime and limit changes and
an optional checkpoint. Levels 1-2 are plans of identical rounds, so their behaviour and random-stream order are unchanged (their 41 tests pass
unmodified apart from the shared test helper). Every level keeps: the four seeded streams drawn before any decision; commit-before-reveal; the four-way
debrief; same-path counterfactual policies (now per level).

| Level | Episode ids | Rounds and decisions |
|---|---|---|
| 3 | `mm.ep3_curve_book_ldi`, `mm.ep3_curve_book_corporate` | 5 x (request in 2/5/10/30Y, hedge); slope checkpoint before pricing in round 2 (graded after pricing) |
| 4 | `mm.ep4_products_overnight` | 16:00 request + hedge (futures-contracts checkpoint); 16:30 request + hedge; close: overnight decision; 08:30 re-hedge; 09:30 request + hedge |
| 5 | `mm.ep5_information_views` | morning two-way quote + hedge; request + position decision into the release; request + hedge; limit cut: request + hedge |

### 18.2 New infrastructure

* `episodes/products.py`: `SpreadMarket` (an engine `MarketCurves` plus an overlay `{"asw", "fut"}`; every method that returns a market returns a
  SpreadMarket with the same overlay, so engine risk and carry functions work unchanged) and `BondPosition` / `FuturePosition`, which re-bind to the
  overlay when priced. A future is margined: its value is contracts x EUR 1,000 x (price - entry). A bond purchase is paid in cash (financed in repo).
* `episodes/factors.py`: two SPREAD factors (swap spread, futures basis) beside level/slope/curvature, moved by `apply_moves`.
* `episodes/evidence.py`: the posterior P(informed | evidence) by Bayes from observed post-request moves (section 18.4).
* `assess.py`: one `DecisionContext` for all levels with `Info` (observable or stated information only), the risk-equivalent inventory, product hedges,
  switch, flatten (cheapest triple of tenors), position alternatives, curve-limit errors, overnight time P&L in E, and the level 5 price decomposition.
* `episode.py`: plan-driven runner, overnight step (carry, roll-down, funding, futures convergence booked by cause), cash ledger, bucketed key-rate
  display, deferred checkpoint feedback, per-level policies, `render=False` counterfactual runs, the 200-path report.
* `decisions.py`: `sell 300 fgbl`, `buy 50m ctd`, `switch [10y]`, `flatten`, `target +100k` / `flat` / `keep`.

### 18.3 Assumptions and calibration added (all stated in code)

| Assumption | Value | Where |
|---|---|---|
| Client tenor preferences | pensions mostly 30Y, corporates 5-10Y, bank treasuries 2-5Y, macro anywhere | `specs.TENOR_PREFS` |
| L3 structural flow | LDI: pensions receive 75%; corporate: corporates pay 75% | `specs.L3_VARIANTS` |
| Curve limit | 0.5 x DV01 limit (L3, L5); equal to the DV01 limit at L4 | specs |
| Exit cost of a curve position | half the 2Y and 30Y spreads x |slope exposure| (a 2s30s package; not netted by flow) | `assess.other_exit_cost` |
| Exit cost of a swap-spread position | unwind the futures + trade swaps later, per unit of ASW exposure | `assess.other_exit_cost` |
| Swap-spread / futures-basis vols | 0.8bp / 1 tick per day | `factors.FACTORS` |
| Futures and bond costs | half a tick a contract; 1 cent per 100 for the CTD | `specs.FUT_HALF_TICK`, `BOND_HALF` |
| Late session | swaps cost 2x their spread now, plus impact: a hedge of D DV01 costs (1 + D / (0.25 x limit)) x that; exits later at normal cost | `specs.LATE_SWAP_COST`, `LATE_DEPTH`, `Regime.swap_depth_dv01` |
| Overnight risk | 0.5 day of normal vol; the curve rolls statically one business day | `episode.OVERNIGHT_DT` |
| Special repo | the CTD 20-40bp special in 40% of L4 episodes | specs |
| Named clients | 3 per L5 session (5 names), latent flag from the type prior, each with a direction it repeats 80% of the time | specs |
| Research view | 2-4bp over the session, reliability 30/50/70%, honest: right with the stated probability, then drifting view/rounds per step | specs |
| Release | vol x3 in the step after the position decision | specs |
| Limit cut | to two thirds of both limits, with thin liquidity, for the last round | specs |

### 18.4 Choices made where section 17 left details open

1. **Risk-equivalent inventory.** Variance-minimising position in the request's tenor under the factor covariance; "reduces risk" means the book's
   variance falls (so a 30Y request can reduce a curve book's risk at one size and add to it at four times that size: tested).
2. **Breach semantics.** A request is a breach only if it creates or worsens a limit excess; one that shrinks an existing excess is an axe.
3. **Curvature is shown.** Level 3 displays curvature exposure alongside level and slope (no limit) because it moves P&L; hiding it would have
   graded trainees on invisible risk.
4. **The slope checkpoint is graded after pricing.** Its answer is the trade's effect on the whole book; revealing it first would do the L3 skill for the trainee.
5. **Futures are temporary hedges in E.** Holding futures against swaps leaves a swap-spread position whose eventual close (futures unwind + swaps) is
   charged as exit cost; whether that is worth it depends on size, session and vol, which the late-session impact assumption makes real.
6. **Posterior evidence = the level move after each of a named client's requests.** The research view's drift is treated as known mean and its
   uncertainty as extra noise per step (an approximation: the view is in fact right or wrong for the whole session). Calibrated against simulation.
7. **The 200-path distribution holds the trainee's decisions, clients and fills fixed** and redraws the market, the view's truth and the clients'
   flags, valuing first-order P&L from the recorded exposures. It shows what the decisions could have produced; it is printed after, and labelled as a
   supplement to, the same-path comparison.
8. **Level 5 focus tenor is the 10Y** (the slope factor's pivot), so a view is a pure level view and a large outright position does not register as
   slope risk.

### 18.5 Validation

`tests/episodes/test_invariants.py` runs every registered episode through: exact replay; clients, fill draws, market path and evidence identical under
different policies; no hindsight under a different market path AND under flipped informed flags and a flipped view outcome; ledger = full revaluation
+ cash; no assessment content (ratings, sigma, benchmarks, posterior, "behaves like") in any observation; reference policy never poor or an error and
mostly sound; the four debrief sections. Level files add: L3 risk-equivalent behaviour, size-dependence of "reduces", curve-limit errors, flatten,
bucket sums, the withheld checkpoint, no whole-book effect on the request screen, variants' structural flow; L4 overlay repricing, futures hedge
leaves exactly swap-spread risk, wrong-way futures error, late versus morning costs, switch, repo and specialness overnight, the carry report before the
overnight decision, the contracts checkpoint, product parsing, spread P&L of kept futures; L5 posterior direction and calibration, evidence from
observables only, no inference shown, view sizing monotone in reliability and shrunk by the release, oversizing a weak view rated poorly, the price
decomposition sums and moves with the posterior, ignoring strong evidence not sound, limit-cut errors, the 200-path report (deterministic, L5 only,
after the same-path section, mean equal to a direct expectation), views right and wrong across seeds.

Mutation checks for levels 3-5 (20, all caught): risk-equivalent sign; "reduces" by variance reversed; breach that ignores whether the excess
worsens; curve-limit error disabled; curve exit cost dropped; the slope checkpoint's answer revealed before pricing; futures not margined; bond
purchase cash not booked; ASW overlay sign; futures ignoring swap spreads; late-session impact ignored; overnight funding sign; posterior evidence
sign; three information leaks (the assessment using the hidden informed flag, the assessment using the view's realised truth, a probability printed
next to a client); the release missing from the assessment; view-lean sign; the limit cut not applied; the many-path distribution ignoring the view.
The plumbing pass (section 19) adds its own mutation checks: hidden key added to a view, informed flag leaked, research view depending on the view's truth,
checkpoint answer exposed, a future move leaking into the ladder, dust legs not suppressed (and assessed but not skipped), rendered text drifting from view data,
the two expectations conflated, and the codec dropping a field.

---

## 19. The frontend interface (pre-UI plumbing; frozen)

The terminal is one adapter over a boundary that carries only plain data. A future frontend uses `episodes/api.py` and nothing else from `episodes/`.

### 19.1 The contract

    sess = Session.start(episode_id, seed, market_seed=None)     # or Session.for_level(level, seed), Session.replay(record)
    sess.observe()          -> ObservationView     what the trainee may know now, and what is being asked
    sess.parse(text)        -> decision            the one canonical text -> decision entry point (decisions.parse); ValueError/KeyError = readable message
    sess.submit(decision | text | encoded dict) -> StepResultView
    sess.debrief(compare=True) -> DebriefView      after the episode is done
    sess.record()           -> replay record       JSON
    catalogue(), episode_for_level(level, seed)    what can be played

Everything returned is JSON-ready (dicts, lists, strings, numbers, booleans, null; no engine objects). `Episode`, `Observation.ctx` and `Observation.part` are
engine-side (policies, assessment, tests) and are not part of the contract.

### 19.2 The views (`views.py`; `render.py` turns them into the terminal's text)

* **ObservationView**: `kind` (quote, rfq, checkpoint, hedge, position, overnight, rehedge); `episode`; `header` (title, round, briefing and notes on the first
  screen of a round, `show_risk_card`); `risk_card`; `market` (single-tenor curve and focus quote, or the swap ladder with mid, street bid/offer, DV01 per EUR 1m
  and cost to cross, plus futures and bond lines); `book` (swap rows, net product hedges, DV01 and limit, bucket DV01, slope exposure and limit, curvature,
  curve position, swap-spread and futures-basis exposure, P&L so far); `conditions` (volatility, liquidity, flow, late-session swap cost, desk expectation,
  `research`, named-client evidence, calendar, extra lines); `clients_today`; `inquiry` (the request and its OWN DV01, never its effect on the book);
  `last_inquiry`; `hedge_menu`; `overnight` (the carry report); `next_step`; `checkpoint` (never the answer); `prompt`; `input` (type, hint, and for hedges the
  allowed swap tenors, products and whether flatten, switch and target apply). Blocks the screen does not show at that point are `null`.
* **StepResultView**: `events` (typed dicts: `client_arrives`, `fill`, `passed`, `checkpoint_recorded`, `checkpoint_grade`, `flat_book`, `hedge_trade`,
  `skipped_trade`, `no_trade`, `overnight`, `market`, `round_pnl`), `assessment`, `grade`, `done`.
* **AssessmentView**: `kind`, `rating`, `reasons`, `expected_pnl`, `variance`, `table` (label, expected, sigma, rating: the benchmark alternatives, revealed only
  after commitment) and `metrics` (plain data; the quote's reference is a dict, not an engine object).
* **DebriefView**: `decisions` (decision quality), `calculation_checks`, `outcome` (realised, by cause), `luck`, `clients` (the truth), `evidence_vs_truth`,
  `view_truth`, `counterfactuals` (same-path policies), `market_paths` (level 5 only, after the same-path section).

### 19.3 How hidden information stays hidden

The views are built from an explicit list of observable facts (`views.observation_view`), not by serialising engine state, so there is no field to forget to
remove: no context, informed flags or probabilities, research-view truth, future moves, random streams, seeds or checkpoint answers. The evidence a
trainee sees is the name, the side and the move they saw. `tests/episodes/test_plumbing.py` asserts: every view is plain JSON; no hidden key appears in any
observation or step result at any step of any level; observations up to the first move are byte-identical when the informed flags, the view's truth and the
market path are changed; the research line is independent of the view's truth at every round; the checkpoint view has exactly its allowed keys; and mutations
that add a hidden key, leak a flag, make the research view depend on its truth, expose the checkpoint answer or let a future move into the ladder are caught.
What a view reveals after commitment is as designed: the rating, the benchmark table and, by default, the evidence-based P(informed) in the reasons (never before). A `Session` started with `reveal_inference=False` (the web live desk) omits that probability from results; the debrief's `decisions[].reasons` always carries it.

### 19.4 Replay

A record is `{"format": "rates-trainer-episode-replay", "version": 1, "episode", "seed", "market_seed", "decisions": [...], "complete"}`. A decision is stored as
`serial.encode_decision` writes it (quote: bid, offer; rfq: level or null; checkpoint: raw text; hedge: label and trades, each a swap with tenor, side and notional,
a future with code and contracts, or a bond with code and face), one per prompt, in order. The id and the two seeds fix the clients, fills and market (four seeded
streams drawn before any decision), so the same decisions reproduce the episode exactly. It is tested in-process, partially (`upto`), and in subprocesses with
different `PYTHONHASHSEED`. The record names the seeds that generate the hidden market and clients: keep it server-side until the episode is finished.

### 19.5 The four fixes made with the interface

* **Zero-size legs.** A hedge leg whose DV01 is below 0.2% of the DV01 limit (the threshold `hedge_trade_for` already used to choose a hedge) is dropped before
  assessment and execution and reported as `skipped_trade`; a decision of only such legs is "no trade". The assessed, traded and recorded decision are the same one.
  Same-path counterfactual P&Ls therefore move by a few euros where a dust leg used to be traded; nothing else about the policies changed.
* **The research view.** Kept as designed: the view is a drift spread evenly over the session's steps, whether or not it is right and whatever has been seen, so
  what is left at round r is view x (rounds - r) / rounds. That remainder, the per-step amount, the stated reliability and the expected next-step drift are now
  shown with the standing sentence and are exactly what the assessment uses (tested equal to `Info.view_bp` and `Info.signal_drift_bp`). It depends only on the
  round, so it cannot carry hindsight. (The approximation that the realised part of the view is not subtracted is recorded in 18.4.)
* **The factor assumptions.** `risk_card` (and one standing sentence on the first screen) gives each factor's normal daily vol (level 5bp, slope 2bp, curvature
  1bp; at level 4 swap spread 0.8bp and futures basis 1 tick), today's multiplier, the step-length scaling and each curve factor's loadings, labelled as training
  assumptions rather than market estimates.
* **Two expectations.** The LUCK section's "expected" is the *expected P&L from execution uncertainty* (each client counted at its probability of dealing with you,
  plus hedge and exit costs and expected drift). The level 5 paths are the *market-path P&L distribution conditional on these decisions and fills* (the edge the fills
  actually paid is in it). They answer different questions, are separate fields with separate labels, and the debrief says the two means are not meant to match.

### 19.5b Two additive fields (levels 3-5 UI)

Both are derived from numbers the engine already had; neither touches a grade, a seed stream, a decision or the replay record. The `market` event carries
`tenor_moves` (`[{tenor, bp}]` for 2, 5, 10 and 30Y: the par change implied by the factor moves, using the same loadings as `move_bp`), so that the result can
draw how the curve moved without the browser combining loadings and factor moves. Level 5's `market_paths.yours` and `.reference` carry `samples` (the 200 path
outcomes in whole euros) next to mean, p05 and p95, so the debrief can draw the distribution. `tests/episodes/test_ui_additions.py` checks both against their
sources.

### 19.6 Not frozen, left to the UI

Screen density and repetition, wording consistency (for example "DV01 ~0" against "-EUR 1/bp"), where the risk card and sign conventions live, how the benchmark
table is shown, and any charting.
