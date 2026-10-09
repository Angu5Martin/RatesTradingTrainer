# TRAIN curriculum: coverage, audit and sources

This document records what the standalone question bank covers, how the original sources were judged, what public book material informed the expansion (and what could not be
verified), how the new sources are built and checked, and what is deliberately left to the Live Desk or to later work. The architecture is in `docs/DESIGN.md`; the stateful
episodes in `docs/EPISODES.md`.

## 1. What the labels in the catalogue mean

Both labels are read from the code, not from a description:

| Label | Source of truth | Meaning |
|---|---|---|
| **planned** (TRAIN chip; `./trainer list` prints `planned`) | `Skill.planned` in `curriculum/skills.py` | On the roadmap. The skill has **no questions of any kind**, standalone or episode. A test fails if a planned skill gets a source or an episode. |
| **no standalone questions** (TRAIN chip; `./trainer list` prints `NO QUESTIONS` when it is not planned either) | `sources == 0` in `questions/api.catalogue()` | The skill is active, practised **only in the Live Desk episodes**. It cannot be selected in TRAIN. |

They are not interchangeable: a *planned* skill is unbuilt, a *no standalone questions* skill is built but only as a stateful episode.

Before this expansion: 7 skills were planned (`math.bootstrapping`, `math.interpolation`, `bonds.money_market`, `risk.convexity`, `curve.butterfly`, `portfolio.aggregation`, `portfolio.scenarios`)
and 4 had no standalone questions (`risk.key_rate`, `mm.requote_loop`, `mm.cross_product_hedging`, `mm.views_and_events`). After it, **every one of the 41 skills has standalone
questions** and none is planned. The `planned` mechanism stays in the code and is still tested (`tests/test_session.py` adds a temporary planned skill to check the tag).

## 2. Coverage by track and skill

`T` = parameterised template (numbers from the engine), `C` = curated conceptual question. "Before" is the original bank (62 sources: 26 T, 36 C); "added" is this pass.

| Track / skill | Before (T/C) | Added (T/C) | Total | Calc / concept | Live Desk episodes |
|---|---|---|---|---|---|
| **Rates mathematics** | | | | | |
| `math.forward_rates` | 1/0 | +2/+2 | 5 | 3 / 2 |  |
| `math.bootstrapping` *(was planned)* | 0/0 | +1/+3 | 4 | 1 / 3 |  |
| `math.interpolation` *(was planned)* | 0/0 | +1/+2 | 3 | 1 / 2 |  |
| **Swaps, OIS and FRAs** | | | | | |
| `swaps.dv01` | 1/2 | +1/+2 | 6 | 2 / 4 |  |
| `swaps.forward_start` | 1/0 | +1/+2 | 4 | 2 / 2 |  |
| `swaps.ois_vs_ibor` | 1/0 | +2/+3 | 6 | 3 / 3 |  |
| `swaps.fra` | 1/0 | +1/+2 | 4 | 2 / 2 |  |
| `swaps.basis` | 1/0 | +1/+1 | 3 | 2 / 1 |  |
| **Bonds, money markets and repo** | | | | | |
| `bonds.duration_convexity` | 1/0 | +2/+2 | 5 | 3 / 2 |  |
| `bonds.money_market` *(was planned)* | 0/0 | +2/+3 | 5 | 2 / 3 |  |
| `bonds.carry` | 1/1 | +0/+0 | 2 | 1 / 1 |  |
| `bonds.repo` | 1/2 | +0/+0 | 3 | 1 / 2 |  |
| **Interest-rate futures** | | | | | |
| `futures.conversion_factor` | 1/1 | +0/+0 | 2 | 1 / 1 |  |
| `futures.dv01` | 1/1 | +1/+0 | 3 | 2 / 1 |  |
| `futures.ctd` | 2/4 | +0/+0 | 6 | 2 / 4 |  |
| `futures.stir` | 1/2 | +0/+0 | 3 | 1 / 2 |  |
| **Risk and hedging** | | | | | |
| `risk.hedge_ratio` | 1/1 | +0/+2 | 4 | 1 / 3 |  |
| `risk.key_rate` *(was episode-only)* | 0/0 | +3/+3 | 6 | 3 / 3 | 2 |
| `risk.convexity` *(was planned)* | 0/0 | +1/+3 | 4 | 1 / 3 |  |
| **Curve trades** | | | | | |
| `curve.steepener` | 1/0 | +1/+2 | 4 | 2 / 2 |  |
| `curve.direction` | 0/2 | +1/+2 | 5 | 1 / 4 |  |
| `curve.butterfly` *(was planned)* | 0/0 | +1/+3 | 4 | 1 / 3 |  |
| `curve.carry_rolldown` | 1/3 | +0/+0 | 4 | 1 / 3 |  |
| `curve.carry_curve` | 1/0 | +0/+0 | 1 | 1 / 0 |  |
| **Relative value and basis** | | | | | |
| `rv.swap_spread` | 0/2 | +1/+0 | 3 | 1 / 2 |  |
| `rv.asw` | 1/2 | +0/+0 | 3 | 1 / 2 |  |
| `rv.futures_basis` | 1/3 | +0/+0 | 4 | 1 / 3 |  |
| `rv.cash_vs_swaps` | 1/1 | +0/+0 | 2 | 1 / 1 |  |
| **P&L and attribution** | | | | | |
| `pnl.convexity` | 0/1 | +1/+0 | 2 | 1 / 1 |  |
| `pnl.warehousing` | 1/3 | +0/+0 | 4 | 1 / 3 |  |
| `pnl.attribution` | 1/0 | +1/+1 | 3 | 2 / 1 |  |
| **Market making and quoting** | | | | | |
| `mm.bid_offer` | 0/1 | +1/+3 | 5 | 1 / 4 |  |
| `mm.client_trade` | 1/0 | +1/+2 | 4 | 2 / 2 |  |
| `mm.skew` | 1/2 | +1/+3 | 7 | 0 / 7 |  |
| `mm.hedge_vs_inventory` | 1/1 | +0/+0 | 2 | 1 / 1 | 1 |
| `mm.adverse_selection` | 0/1 | +1/+3 | 5 | 1 / 4 |  |
| `mm.requote_loop` *(was episode-only)* | 0/0 | +2/+5 | 7 | 2 / 5 | 1 |
| `mm.cross_product_hedging` *(was episode-only)* | 0/0 | +1/+5 | 6 | 1 / 5 | 1 |
| `mm.views_and_events` *(was episode-only)* | 0/0 | +2/+7 | 9 | 2 / 7 | 1 |
| **Portfolio risk** | | | | | |
| `portfolio.aggregation` *(was planned)* | 0/0 | +1/+2 | 3 | 1 / 2 |  |
| `portfolio.scenarios` *(was planned)* | 0/0 | +1/+1 | 2 | 1 / 1 |  |

Totals: 62 sources before, 167 after (36 new templates and 69 new curated questions).

## 3. Audit of the original sources

Each source was read, generated at many seeds and judged against the questions in the brief. Measured facts (a 120-seed scan of every template):
every original template produced a distinct stem at nearly every seed (a fresh EUR market, direction, size and tenor each time), so none was a thin re-skinning of one instance; the
differences between sources are in depth and angle.

| Category | Original sources | Verdict and what was done |
|---|---|---|
| **1. Adequately covered** | `bonds.carry_rolldown`, `carry.swap_carry_roll`, `carry.warehousing`, `carry.curve_trade`, `carry.attribution`, `mm.warehouse_carry`, all six `futures.*` templates (conversion factor, DV01 hedge, CTD ranking, CTD switch, basis trade, STIR strip), `rv.asw_package`, `rv.bond_swap_hedge`, `bonds.repo_carry`, `basis.irs_vs_ois` | Multi-part, engine-driven, with a stated mental route and a tolerance derived from its error. Left unchanged. Three new sources touch the same ground from another angle (futures tick value, swap-spread P&L, tenor compounding). |
| **2. Worth more parameterisation** | `math.forward_1y` (one variable, the horizon) | Kept; two new sources solve the same identity from discount factors and from forwards in the other direction. |
| **3. Worth new types or depth** | `swaps.dv01_pnl`, `swaps.fra_dv01_pnl`, `swaps.forward_start`, `hedging.swap_swap`, `curves.curve_trade`, `bonds.duration_convexity_pnl`, `mm.client_trade_risk`, `mm.skew_and_width`, `basis.tenor_3s6s` | Each was one angle on a deep topic (always calculate forwards from a clean at-market instrument). New sources add: an off-market swap's value and unwind, FRA settlement, the inverse forward-start problem, forward-start hedging by key rate, the equal-notional trap, a butterfly, clean/dirty prices and price-to-yield, net edge after hedging, picking the right quote from four. |
| **4. Insufficient, new sources needed** | the seven planned skills, the four episode-only skills, and `rv.swap_spread`, `pnl.convexity`, `swaps.forward_start`, `curve.steepener`, `bonds.duration_convexity` (no calculation or no conceptual question on one side) | Built. See section 2. |
| **5. Intentionally outside scope** | informed-flow inference, hidden values, the progress of an episode over several decisions; nonlinear products; speed and adaptive difficulty | Stay in the Live Desk (or out of the application). See section 7. |

**The 36 original curated questions.** Their content is sound and they were not edited. One measured weakness: in 31 of 36 the correct option is also the longest (in 19 it is more than 1.6x
longer than every other), a test-taking tell that makes some of them answerable without the finance. Rewording would change what a replayed id shows (the option order and the correct letter would not
change), so it was left alone for the user to decide; the new curated questions are built to avoid it, and a test enforces it (the correct answer is neither the longest nor the shortest in more
than 40% of them; measured: 19/69 longest, 17/69 shortest).

**Calculation questions that were missing.** `rv.swap_spread` had only conceptual questions, `curve.steepener` and `mm.client_trade` only calculation, `pnl.convexity` one conceptual question, `mm.skew` seven
conceptual and no calculation. The first four are now balanced (see the table). `mm.skew` is deliberately conceptual: the quote model is a stylised teaching model graded on direction and relative size
(`marketmaking/quoting.py`), so no number in it would deserve to be called correct.

## 4. The public book material

*Pricing and Trading Interest Rate Derivatives* (J. H. M. Darbyshire; third edition 2022) was **not available locally and was not read**. What was inspected, and what each source can and cannot support:

| Source | What it gave | Limits |
|---|---|---|
| Companion repository `github.com/attack68/book_irds3` (cloned and read: README, `bookirds/` modules, ten notebooks, tests) | The notebook file names carry chapter numbers: **Ch11** curves and Jacobians (forward-to-par and par-to-forward risk transforms), **Ch12** advanced curves (mixed interpolation, B-splines, turns, IMM knots, layered curves, risk), **Ch14** covariance VaR, **Ch15** PCA, **Ch19** electronic trading and mid-market (equivalent portfolios, hedge-cost margin, volume and correlation add-ons, liquidity-assessed spread, Bayesian mid inference), **Ch22** cross-gamma, **Ch23** roll/vol and trade-directionality hedging. The code shows the methods; the notebook markdown shows the worked examples ("a 5Y5Y swap, a 5Y and a 10Y swap, and a 5s10s spread with a 10Y swap are equivalent portfolios"). | The repository is a code companion: no prose, no chapter list, no problem statements. The README says the code is "discussed and created within the text". Chapter numbers above come only from notebook names. |
| Bookseller listings reached by web search | A paraphrased list of subject areas: mathematical review, interest-rate definitions, product mechanics, users of the products, cash/collateral/credit inputs, single- and multi-currency curves, delta and basis risk, VaR and PCA, customised risk management for market makers, the market-making process and price-taking (margin), electronic trading, regulation, volatility. | No official table of contents. The listings disagree on chapter numbering after Ch14, so **no chapter number is attributed except the ones in the notebook names**. Google Books showed no preview. `tradinginterestrates.com` redirects to the repository above. |

How each topic was used. *Confirmed by the companion code* means the method is in the repository; it does not mean a TRAIN question reproduces a book exercise.

| Topic | Evidence | Where it landed in TRAIN |
|---|---|---|
| Forward swap = longer swap minus shorter swap, at equal notional ("equivalent portfolios"); forward-to-par risk Jacobians | Companion code and notebooks (Ch11, Ch19) | `risk.key_rate_hedge`, `swaps.forward_start_inverse`, curated `kr_forward_start_hedge`. The engine's `solve_key_rate_hedge` returns exactly equal notionals. |
| Interpolation, nodes and turns change forwards and risk | Companion code (Ch12) | `math.interp_log_linear` and curated interpolation questions. Log-cubic splines, turns and layered curves are **not** in the engine and have no questions. |
| Level/slope/curvature (PCA) and hedging a trade's residual directionality | Companion code (Ch15, Ch23) | `risk.factor_exposure` is a **stylised** factor decomposition with fixed loadings; it does not estimate principal components or VaR. `risk.key_rate_read` shows the residual curve position a mismatched hedge leaves. |
| Hedge-cost margin, equivalent hedge portfolios, liquidity-adjusted spread | Companion code (Ch19) | `mm.client_net_edge`, `mm.cross_product_hedge`. The volume and correlation add-ons and the Bayesian mid are not modelled in TRAIN. |
| Second-order risk, cross-gamma of a swap | Companion code (Ch22) | `pnl.convexity_asymmetry`, `risk.convexity_barbell` (the single-swap convexity asymmetry and the barbell). A cross-gamma **matrix** is not built; that is a remaining gap. |
| Roll-down versus volatility (Sharpe of a position) | Companion code (Ch23) | Already covered by the original warehousing sources. |
| Swaptions and volatility | Companion code (`swaptions.py`) and listings | **Excluded**, as the brief requires. Nothing from `swaptions.py` is used. |
| Curve definitions, product mechanics, collateral/discounting inputs, delta and basis risk | Bookseller descriptions only (not verified by chapter) | `math.*` sources, `swaps.cashflow_conventions`, `swaps.fra_settlement`, curated discounting and tenor-basis questions. |
| Multi-currency curves, regulatory capital, VaR estimation | Bookseller descriptions only | Not added: outside the EUR linear scope or not tied to a decision TRAIN trains. |
| Bills, ESTR compounding in arrears, day-count conversion, clean/dirty prices, FRA settlement, swap-spread P&L, event-risk sizing, bid/offer drills | General interest-rate knowledge (not from the book) | Added for the gaps in the brief's own checklist. |

## 5. How the new sources are built

* **Engine first.** Where the engine has the quantity (swap value, key-rate DV01, FRA value, bond accrued and yield, futures DV01, quote model) the answer is the engine's; the closed-form shortcut a trader would use
  is the `approx` (accepted only where the gap is inside the tolerance, and then a test checks it). Where a stylised textbook setup is clearer than the engine's calendar (annual bootstrapping, a week of ESTR, the
  stylised factor loadings), the stem says so and the tests recompute it independently.
* **Conventions in every stem.** Rate units, signs ("+ = receive fixed", "positive = long duration"), day counts and whose side a quote is on are stated whenever they change the answer. DV01 is P&L for a
  1bp fall; bid = you pay fixed.
* **Tolerances measure the mental route**, not the engine: each is set from the structure of the approximation (convexity, discounting divisor, rounding of printed figures) and checked in a 300-seed scan
  (headroom at most about 0.8 of the tolerance; most far below). A wrong route is *not* accepted: where a tempting wrong answer exists (naive `1/(1+S)^n`, year-weighting a forward, forgetting the
  Friday fixing counts three times, equal notionals, ignoring what is already priced) its value is shown after the answer and a test checks it lies outside the tolerance.
* **Significance.** A scenario is redrawn until every answer clears its tolerance, so a part cannot be answered with zero or the wrong sign, unless zero is the lesson.
* **Distractors are misconceptions** (the flipped skew, the equal-notional hedge, "DV01-neutral means risk-free", the clean price used as the cash amount), not arbitrary numbers.
* **Determinism and identity.** A question is still `(template, seed)`. A digest test pins 372 draws of the 62 original sources so none of them can drift.
* **Declared kind.** New templates declare `kind="calculation"` or `"conceptual"` so the catalogue need not generate each source to classify it; a test checks the declaration against the generated parts.

### Distinct variants

A template draws a fresh EUR market on every seed, so almost every seed is textually different: for 34 of the 36 new templates the seeds drawn gave 83-100% distinct stems (the exceptions are two pure-parameter models, `mm.adverse_selection_edge` at 19% and `mm.event_sizing` at 71%). That overstates the variety. The honest measure is
**structural variants**: distinct combinations of the discrete choices a trainee sees (instrument and tenor, side, size, move, mode, and which quantity is solved for). It was estimated by drawing seeds, counting the
distinct combinations observed and applying the Chao1 lower-bound estimator (observed + singletons squared over twice the doubletons); where many combinations were seen only once the true number is larger
than the estimate. Curated questions count as one variant each (their options reshuffle, which is not a new problem).

| Template | Skill | Level | What it asks | Structural variants (>=) | Distinct stems / seeds |
|---|---|---|---|---|---|
| `bonds.clean_dirty_accrued` | `bonds.duration_convexity` | 2 | Accrued (ACT/ACT), dirty price, settlement cash, clean price move, pull to par | 280 | 3000/3000 (100%) |
| `bonds.price_to_yield_move` | `bonds.duration_convexity` | 2 | Yield move implied by a price move, P&L, DV01, duration across maturities | 857 | 2992/3000 (100%) |
| `bonds.bill_price_yield` | `bonds.money_market` | 2 | Bill price, cash, DV01, P&L for a yield move, rich/cheap to OIS | 558 | 2488/3000 (83%) |
| `bonds.mm_day_count` | `bonds.money_market` | 2 | ACT/360 vs ACT/365 interest, conversion, annual-effective yield | 64 | 2730/3000 (91%) |
| `curves.butterfly` | `curve.butterfly` | 3 | 50:50 DV01 fly: wing sizes, P&L from a move, which scenario pays | 31,210* | 800/800 (100%) |
| `curves.move_decomposition` | `curve.direction` | 2 | Name a curve move, level and slope, P&L of a DV01-neutral curve trade | 1,034 | 2988/3000 (100%) |
| `curves.equal_notional_trap` | `curve.steepener` | 2 | Equal-notional curve trade: hidden DV01, parallel P&L, neutral size | 289 | 1280/1500 (85%) |
| `futures.contract_specs_pnl` | `futures.dv01` | 1 | Ticks, tick value, daily P&L, yield move, variation margin | 288* | 800/800 (100%) |
| `math.bootstrap_par_curve` | `math.bootstrapping` | 2 | Annual par rates to discount factors, zero and forward (or the reverse: DFs to par rates) | 8 | 2973/3000 (99%) |
| `math.df_forward_solve` | `math.forward_rates` | 2 | Forward from two DFs; DF from a quoted forward; zero rate; forward vs zero | 49 | 3000/3000 (100%) |
| `math.ois_policy_path` | `math.forward_rates` | 2 | 3x6 ESTR forward from OIS pillars, step in bp, cuts/hikes priced, forward-window trade | 6 | 2997/3000 (100%) |
| `math.interp_log_linear` | `math.interpolation` | 2 | DF between nodes (log-linear vs linear zero), flat forwards, which forwards a bump moves | 80 | 3000/3000 (100%) |
| `mm.adverse_selection_edge` | `mm.adverse_selection` | 2 | Expected edge with an informed share, break-even half-spread, when the share doubles | 576 | 574/3000 (19%) |
| `mm.bid_offer_drill` | `mm.bid_offer` | 1 | Which side a request hits, the position, total DV01, which client you want next | 4,442* | 3000/3000 (100%) |
| `mm.client_net_edge` | `mm.client_trade` | 3 | Captured spread vs hedge cost, net edge, mismatch cushion, whether to match a competitor | 4,502* | 1500/1500 (100%) |
| `mm.cross_product_hedge` | `mm.cross_product_hedging` | 3 | Futures contracts for a client swap, swap vs futures cost, basis P&L, break-even spread move | 261 | 800/800 (100%) |
| `mm.requote_sequence` | `mm.requote_loop` | 3 | Fill, new inventory, direction and size of the re-quote, skew grew/shrank/flipped, hedge or work | 1,260* | 1500/1500 (100%) |
| `mm.stale_quote` | `mm.requote_loop` | 2 | Market moves through your quote: who trades, the loss, the new market | 189 | 2994/3000 (100%) |
| `mm.quote_review` | `mm.skew` | 3 | Pick the right market of four; the mirrored skew; which client it favours | 13,234* | 2999/3000 (100%) |
| `mm.event_repricing` | `mm.views_and_events` | 3 | Data surprise to curve move and slope, book P&L, which outcome hurts | 1,085* | 1490/1500 (99%) |
| `mm.event_sizing` | `mm.views_and_events` | 3 | Event-day risk, volatility-scaled inventory, view net of what is priced, sizing decision | 4,058* | 2137/3000 (71%) |
| `pnl.realised_unrealised` | `pnl.attribution` | 2 | FIFO day: realised vs unrealised P&L, open average rate, open DV01 | 312 | 3000/3000 (100%) |
| `pnl.convexity_asymmetry` | `pnl.convexity` | 2 | Receiver/payer P&L in a big move both ways, convexity P&L, who benefits | 40 | 1487/1500 (99%) |
| `portfolio.bucket_book` | `portfolio.aggregation` | 3 | Aggregate per-trade bucket DV01s, curve P&L, hedge the largest bucket | 45,150* | 300/300 (100%) |
| `portfolio.scenario_pnl` | `portfolio.scenarios` | 3 | One book, three factor scenarios (parallel, bear steepening, swap-OIS spread), worst case | 45,150* | 300/300 (100%) |
| `risk.convexity_barbell` | `risk.convexity` | 3 | DV01-neutral barbell vs bullet: DV01 after a move, convexity P&L both ways, why not free | 32 | 500/500 (100%) |
| `risk.factor_exposure` | `risk.key_rate` | 3 | Level/slope/curvature exposures from buckets, scenario P&L, which factor drives risk | 719* | 500/500 (100%) |
| `risk.key_rate_hedge` | `risk.key_rate` | 3 | Hedge a forward-start swap bucket by bucket (equal notionals); what a one-swap hedge leaves | 590* | 300/300 (100%) |
| `risk.key_rate_read` | `risk.key_rate` | 2 | Read a bucket report: parallel DV01, position type, non-parallel P&L, single-bucket hedge | 78 | 500/500 (100%) |
| `rv.swap_spread_pnl` | `rv.swap_spread` | 2 | Swap spread now and after moves, P&L of long bond / pay swap, what the package is | 11,571* | 3000/3000 (100%) |
| `basis.tenor_compounding` | `swaps.basis` | 2 | Two 3M periods compounded vs 6M, the tenor premium, who gains if it widens | 4 | 3000/3000 (100%) |
| `swaps.mtm_off_market` | `swaps.dv01` | 2 | Value of a seasoned swap, value after a move, unwind cost, asset vs liability | 4,863* | 700/700 (100%) |
| `swaps.forward_start_inverse` | `swaps.forward_start` | 2 | Spot b-year rate from the a-year rate and the forward; sensitivity; equivalent portfolio | 28 | 3000/3000 (100%) |
| `swaps.fra_settlement` | `swaps.fra` | 2 | FRA settlement at the start (discounted), who gains, value before the fixing | 140 | 1500/1500 (100%) |
| `swaps.cashflow_conventions` | `swaps.ois_vs_ibor` | 2 | First float and fixed cash flows (ACT/360, 30E/360), who pays on the first date | 529* | 1500/1500 (100%) |
| `swaps.estr_compounding` | `swaps.ois_vs_ibor` | 2 | A week of ESTR compounded in arrears, Friday weighting, interest, Euribor vs ESTR timing | 64 | 3000/3000 (100%) |

Sum of the structural-variant estimates over the 36 new templates measured: about 173,600, of which about 90,000 come from two book templates whose count is only a floor (without them about 83,000). It is a lower bound; * marks a template where more than a fifth of the combinations seen were seen only once, so the true number is larger than the estimate. The 69 new curated questions add 69 fixed problems. These are structural variants, not exact counts: each is also drawn from a continuous EUR market state, so no two practice sessions repeat numerically.

## 6. Validation

* `tests/questions/test_expansion.py` (89 tests) recomputes each new template from first principles or by a different engine route and checks its tolerance window, the earlier sources by digest,
  skill coverage, filters, determinism of selection, the length tell in curated options, and that the session leaks nothing before an answer.
* `tests/questions/test_templates.py` (existing) runs the generic invariants over every source, including the new ones: finite answers, the exact and the mental answer grade correct, the negated answer gets the sign hint,
  deterministic regeneration, variety, and the correct choice is not always the same letter.
* `tests/web/test_train_api.py` plays every newly covered skill from start to summary over HTTP and checks the attempt is recorded in the private test home only.
* Mutation checks (caches cleared, one change at a time, 49 in all): signs, weights, divisors, day counts and the choice of which side a client hits were flipped in the templates. Three survived at first
  (a mental-route sign, a client-side sign, a model-quote swap, each checked only for self-consistency) and now have an assertion that ties them to the action or to a hand-built quote; one more survives
  because it removes a guard that never fires for the way the scenario is drawn (an equivalent mutant), which is left in as a safeguard.
* Frontend: the catalogue fixture was regenerated from the real catalogue and the unit and end-to-end tests that hard-coded the old counts now read them from the catalogue; a separate test keeps the
  `planned` and `no standalone questions` chips honest with an edited catalogue.

## 7. What remains, and what is better in the Live Desk

**Still thin (by design or for lack of engine support).**

* `curve.carry_curve` has one source; the carry of curve trades is deep in that one template.
* Cross-gamma matrices, log-cubic and spline curves, turns, VaR and PCA estimation, multi-currency curves and regulation (from the book's table of contents) have no engine support or are out of scope.
* A book that mixes swaps with bonds and futures in one risk report (the roadmap's portfolio item) is not built; TRAIN's portfolio sources use swap books.
* Quote-model questions grade direction and relative size only, never an optimal number.

**Better assessed in the Live Desk, and not duplicated.**

* Deciding under a hidden state: whether a client is informed, how much of a move was information, how to size a view with only the evidence a desk would have. Standalone TRAIN questions state their assumptions;
  the Live Desk makes the trainee infer them (and by the standing rules shows no informed-flow indicator).
* Multi-decision consequences: how today's hedge changes tomorrow's inventory, a run of fills against a limit, overnight carry on a real position.
* Judging a decision ex ante against its realised outcome and luck.

## 8. Adding to the bank

Follow `docs/DESIGN.md` ("Adding content"), and in addition: do not change what an existing `(template, seed)` produces; declare `kind`; keep curated option lengths comparable; add an independent check
to `tests/questions/test_expansion.py`; and if the skill was planned, clear `planned` in `curriculum/skills.py` in the same change.
