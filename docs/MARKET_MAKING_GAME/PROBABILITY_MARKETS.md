# Probability markets: pricing dice, coins and cards

How to price the game's probability and mental-maths markets exactly, turn the price into a quote, and reprice correctly after each kind of shock. Read the [overview](OVERVIEW.md) first for how quotes, bots and P&L work; this guide is only about markets generated from explicit random experiments. Facts about the world are in [World markets](WORLD_MARKETS.md).

Every probability in this guide is exact and was checked against the game's own engine (`src/rates_trainer/mmgame/probability.py`; the checks are in `tests/docs/test_guides.py`).

**Contents:** [What these markets are](#what-these-markets-are) · [The toolkit](#the-toolkit) · [Common experiments, exact numbers](#common-experiments-exact-numbers) · [From probability to a quote](#from-probability-to-a-quote) · [Shocks: what changed, and how to reprice](#shocks-what-changed-and-how-to-reprice) · [Linked markets](#linked-markets) · [Common mistakes and edge cases](#common-mistakes-and-edge-cases) · [Checklist after a shock](#checklist-after-a-shock)

---

## What these markets are

Each market is one number read off an **experiment** by a **target**.

| Experiment | What it is | Levels |
|---|---|---|
| Dice | 1–6 dice with faces 1–6 (level 1); 6, 8 or 10 sides (level 2); 6, 8, 10 or 12 (level 3) | all |
| Random integers | "random integers 1..N", which behave exactly like N-sided dice | 2, 3 |
| Coins | 4–16 flips; heads = 1, tails = 0; biased (heads twice as likely) in some level 3 games | all |
| Cards | 3–9 cards drawn **without replacement** from a shuffled 52-card deck | all |

| Target | The answer is | Example title |
|---|---|---|
| sum | the sum of all dice | `Sum of 3d6` |
| count | how many results meet a condition (odd, even, ≥ t, ≤ t, prime, multiple of 3; heads; hearts, red, face cards, aces, high cards) | `# odd in 3d6`, `Heads in 8 flips`, `Hearts in 5 cards` |
| max / min | the highest / lowest die | `Highest of 2d8` |
| top-2 sum | the sum of the highest two dice (level 3) | `Top-2 sum of 4d6` |
| event | any of the above turned into a yes/no statement. It **pays 100 if true, 0 if false**, so its price is a probability in percentage points | `P(Sum of 3d6 ≥ 10)` |

Practical details from the generator:

- **Tick:** 0.1 when the answer's σ is under 4, 0.5 otherwise; events trade in whole points (tick 1).
- **Quote range:** from 0 to about twice the largest possible answer (0 to 100 for events). The card also shows **possible now**, the smallest and largest values that can still happen.
- **When the dice are rolled.** Unrolled dice are rolled **at resolution**, under the rules in force then, from a hidden value fixed by the seed. A die can also be rolled earlier by an information shock. After that it never changes.
- **Rules in force** (the detail panel and the card) always list what is still to be rolled and with which faces, plus what has been rolled or revealed. After a shock, that list is the ground truth to price from.

## The toolkit

Each rule below is exact. The shortcuts after it say when they apply.

| Tool | Statement | Use it for |
|---|---|---|
| Complement | P(not A) = 1 − P(A) | "at least one": P(at least one 6 in 3 dice) = 1 − (5/6)³ = 91/216 ≈ 42.1% |
| Addition | P(A or B) = P(A) + P(B) − P(A and B); just P(A) + P(B) if they cannot both happen | adding up disjoint outcomes in a table |
| Multiplication | P(A and B) = P(A) × P(B \| A); just P(A) × P(B) if independent | separate dice and coin flips are independent; cards drawn without replacement are **not** |
| Conditional | P(A \| B) = P(A and B) / P(B) | new information: count only the outcomes still possible |
| Expectation is linear | E[X + Y] = E[X] + E[Y], **always**, even for dependent X and Y | sums of dice; counts as sums of 0/1 indicators |
| Variance of a sum | Var[X + Y] = Var[X] + Var[Y] **if independent** | σ of a dice sum; not for cards |
| Symmetry | a fair die's sum is symmetric about its mean | P(sum of 3d6 ≥ 11) = 1/2 exactly, because 11 is the first value above the mean of 10.5 |

**The standard results** (each exact; *n* dice or draws, *d* sides):

```text
one fair d-sided die:          mean (d + 1) / 2          variance (d² − 1) / 12
sum of n such dice:            mean n(d + 1) / 2          variance n(d² − 1) / 12       (independent: variances add)
count with probability p each: mean n·p                  variance n·p·(1 − p)          (binomial: dice and coins)
cards: count of a kind         mean n·K/N                 variance n·(K/N)·(1 − K/N)·(N − n)/(N − 1)
  (N cards in the deck, K of the kind, n drawn; hypergeometric: the last factor is why cards vary LESS than dice)
highest of n dice:             P(max ≤ k) = (k/d)ⁿ        so P(max = k) = (k/d)ⁿ − ((k − 1)/d)ⁿ
lowest of n dice:              P(min ≥ k) = ((d − k + 1)/d)ⁿ
an event paying 100:           price = 100 × p            σ = 100 × √(p(1 − p))
```

**When mental arithmetic is not enough, use an outcome table.** Two dice have 36 equally likely outcomes. Write the sums as a grid (rows die 1, columns die 2) and count. For three dice, condition on one die and reuse the two-dice counts. Counting beats guessing whenever the target is a max, a min, a threshold or a top-two sum.

**A normal approximation** (mean ± σ, with about 68% inside one σ) is a *heuristic* for sums of three or more dice. Use it for width, not for event prices: at the edges of the range it is badly wrong (the sum of 2d6 has no tails beyond 2 and 12).

## Common experiments, exact numbers

<details>
<summary>Two dice: the full distribution of the sum</summary>

| Sum | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Ways (of 36) | 1 | 2 | 3 | 4 | 5 | 6 | 5 | 4 | 3 | 2 | 1 |

Mean 7, variance 2 × 35/12 = 35/6, σ ≈ 2.42. P(sum ≥ 8) = (5 + 4 + 3 + 2 + 1)/36 = 15/36 = 5/12 ≈ 41.7%.

</details>

| Market | Fair value (exact) | σ | How |
|---|---|---|---|
| Sum of 3d6 | 21/2 = 10.5 | 2.96 | 3 × 3.5; variance 3 × 35/12 |
| P(Sum of 3d6 ≥ 10) | 62.5 (5/8) | 48.4 | symmetry: P(≥ 11) = 1/2, plus P(= 10) = 27/216 = 1/8 |
| Highest of 2d6 | 161/36 ≈ 4.47 | 1.40 | P(max = k) = (k² − (k − 1)²)/36 |
| Highest of 3d6 | 119/24 ≈ 4.96 | 1.14 | same with cubes |
| Lowest of 3d6 | 49/24 ≈ 2.04 | 1.14 | the mirror image of the highest: 7 − 4.96 |
| Top-2 sum of 3d6 | 203/24 ≈ 8.46 | 2.21 | outcome table; not 2 × 3.5 |
| # odd in 3d6 | 3/2 | 0.87 | binomial, p = 1/2 |
| # of 5 or more in 4d6 | 4/3 | 0.94 | binomial, p = 1/3 |
| Heads in 8 flips | 4 | √2 ≈ 1.41 | binomial, p = 1/2 |
| P(Heads in 8 flips ≥ 6) | 37/256 ≈ 14.5 | 35.2 | (28 + 8 + 1)/256 |
| Hearts in 5 cards | 5/4 | 0.93 | 5 × 13/52; P(no hearts) = 2109/9520 ≈ 22.2% |
| Red cards in 5 cards | 5/2 | 1.07 | 5 × 26/52 |
| Aces in 6 cards | 6/13 ≈ 0.46 | 0.62 | 6 × 4/52; P(no aces) ≈ 60.3% |

**Probability versus odds.** A probability of 1/4 is odds of 1 to 3 (one success for three failures), not "1 in 3". Prices in this game are always probabilities (in points out of 100).

**Percentage points versus per cent.** An event moving from 40 to 50 has risen **10 points** and **25 per cent**. Your P&L uses points (price units × lots × lot value).

## From probability to a quote

**Principle.** In these markets you can know fair value *exactly*. The only uncertainty left is the roll itself, and at level 3 the informed bots already know the roll. So your mid should be the exact expectation, and your width is a decision about flow and protection, not about doubt.

**Reasoning.** The bots measure everything in the market's current σ (see [How the bots decide](OVERVIEW.md#how-the-bots-decide)). A quote whose mid is exact and whose half-spread is about 0.5σ is hit by retail on both sides and rarely by the value fund. Any error in your arithmetic shows up as *mispricing* in the debrief, and the value fund finds it.

<details>
<summary>Worked example: Sum of 3d6, one lot at a time</summary>

1. **Fair value:** 3 × 3.5 = **10.5**.
2. **σ:** √(3 × 35/12) = √8.75 ≈ **2.96**. σ is under 4, so the tick is **0.1**.
3. **Lot value:** 100/2.96 ≈ 34, rounded to the nearest 1, 2 or 5 × 10ᵏ: **50 credits per point**.
4. **Width:** 0.5σ ≈ 1.5 points either side: **9.0 / 12.0**. One lot is worth about 50 × 2.96 ≈ 150 credits of one-σ risk.
5. **A retail bot sells you 1 at 9.0.** Position +1, cash −450 (9.0 × 50). Your edge at that moment is 10.5 − 9.0 = 1.5 points = **+75 credits**.
6. **Settles at 13:** cash +650. P&L = +200 = edge +75 + settlement luck (13 − 10.5) × 50 = +125.
7. **Settles at 7:** P&L = 350 − 450 = −100 = edge +75 + settlement luck −175. *Same decision, different luck.*

</details>

<details>
<summary>Worked example: an event, P(Sum of 3d6 ≥ 10)</summary>

1. **Fair value:** P = 5/8 → **62.5** points.
2. **σ:** 100 × √(5/8 × 3/8) ≈ **48.4** points. Event markets have very large σ in points: the outcome is 0 or 100.
3. **Lot value:** 100/48.4 ≈ 2.1 → **2 credits per point**.
4. **Width:** the bots' noise and thresholds scale with σ, so a sensible half-spread in this game is far wider in points than intuition suggests: 0.5σ ≈ 24 points. A 60/65 market is a 0.05σ half-spread, in the *tight* band of the debrief (under 0.12σ). Something like **45/80** is the equivalent of the 9.0/12.0 sum quote above. Treat this as a property of the game's bot model, not of real prediction markets.
5. **Sell 1 at 80; the event happens:** P&L = (80 − 100) × 2 = −40 = edge (80 − 62.5) × 2 = +35, plus settlement luck (100 − 62.5) × 2 × (−1) = −75.

</details>

**Best practice.**

- Compute the exact expectation before you type anything. If you cannot, use the [outcome table](#the-toolkit) or an upper and lower bound, and widen until you can.
- Use the coach at level 1: it shows each trade's edge against fair value, so a run of negative edges on one side tells you the mid is wrong.
- **Uncertainty about your estimate** (have I computed it right?) is a reason to widen. **Randomness in the experiment** is not, on its own: the spread is paid for by flow and lost to information, not to the roll.

**When it changes.** At level 3 the informed bots know the hidden roll. If they trade large in one direction, the roll probably lies that way. Hold a wider quote and a smaller size in that market, especially near resolution.

**Common mistake.** Pricing from the *last* outcome you imagined ("it feels like a high roll") instead of the expectation. Dice have no memory, and the hidden roll is unknown to everyone but the informed bots.

## Shocks: what changed, and how to reprice

The game has three categories of shock. Each carries a heading and a text that says what changed and what did not. A shock hits **one market**, or every market on the **same experiment** (linked markets). The planner only lands a shock that changes the expectation and leaves at least two possible outcomes, so **no shock in this game settles a market outright**. Some move it a long way (see the [edge cases](#common-mistakes-and-edge-cases)).

The process is the same for every type:

1. **Identify** what changed: the experiment, the information, or the reading.
2. **Rebuild** the outcome space: which dice are still to roll, with which faces and weights, and what is already fixed.
3. **Recompute** the expectation (and σ) of the answer under the rules now in force.
4. **Re-quote** the mid at the new fair value, with a width in the new σ.
5. **Reassess inventory:** your position's expected value changed by position × (new fair − old fair) × lot value.
6. **Check for staleness:** the quote you had during the shock round may already have been traded by the sniper or an informed bot (⚡ in the report).

### Experiment changes (RULE CHANGE)

These change **the trials not yet rolled**. Anything already rolled or revealed keeps its value. When faces are removed, the remaining faces keep their relative chances; on an unloaded die that means **equal chances over the faces left**. That is a **renormalisation**: the experiment itself is now different.

| Shock text (shortened) | Effect | Recompute |
|---|---|---|
| "No odd numbers: the 3 dice not yet rolled can no longer show 1, 3, 5" | each unrolled die is uniform on {2, 4, 6} | Sum of 3d6: 10.5 → **12**, possible 6–18 |
| "No numbers below 5" (excluding 1–4) | each unrolled die is uniform on {5, 6} | Sum of 2d6: 7 → **11**, possible 10–12, σ 2.42 → 0.71 |
| "No numbers above 4" | uniform on {1, 2, 3, 4} | Sum of 3d6: 10.5 → **7.5**; P(sum ≥ 11): 50% → **6.25%** (4 of 64) |
| "Range change: faces 1–10 instead of 1–6" | each unrolled die is uniform on 1–10 (any earlier restriction or loading is replaced) | Sum of 3d6: 10.5 → **16.5** |
| "Loaded: the 6 is now 2× as likely" | weights 1,1,1,1,1,2 out of 7 | die mean (1+2+3+4+5+12)/7 = 27/7; Sum of 3d6 → 81/7 ≈ **11.57** |
| "1 more die will be rolled at resolution" | one more trial with the base faces | Sum of 3d6 → 4 × 3.5 = **14** |
| "1 die will not be rolled after all" | one unrolled trial removed | Sum of 3d6 → **7** |
| "Deck change: all clubs … taken out before the draw" | 39 cards, 13 hearts | Hearts in 5 cards: 5/4 → 5 × 13/39 = **5/3** |
| "2 jokers shuffled into the deck" (a joker matches nothing) | 54 cards, 13 hearts | Hearts in 5 cards → 5 × 13/54 = 65/54 ≈ **1.20** |
| "Draw change: 2 more cards will be drawn" | n changes | Hearts: (n + 2) × K/N |

**Best practice.** Recompute from the *rules in force* list, which already shows the new faces. For a count market, recompute p per die first, then use n × p.

**Common mistake.** Treating a rule change as new information about the *old* experiment ("so the dice were probably high"). Nothing about the outcome was learned. The experiment is a different one.

### Information reveals (NEW INFORMATION)

These say something **true about trials that have now been rolled**. The experiment and the settlement rule are unchanged. That is **conditioning**: keep only the outcomes consistent with the statement, in their original proportions.

| Shock text (shortened) | What is now known | Recompute (Sum of 3d6, fair 10.5) |
|---|---|---|
| "Die 1 shows 1" | die 1 = 1, fixed for good | 1 + 2 × 3.5 = **8** |
| "Die 1 has been rolled and is odd. Its exact value is not shown" | die 1 is uniform on {1, 3, 5}; the others are unchanged | 3 + 7 = **10** |
| "Die 1 … is 4–6" (the high half) | die 1 uniform on {4, 5, 6} | 5 + 7 = **12** |
| "The first 2 cards drawn are ♥, ♥" | 2 hearts already counted; 3 more from 50 cards with 11 hearts | Hearts in 5 cards: 5/4 → 2 + 3 × 11/50 = **2.66** |

Why the conditioning is clean here: the type of statement (parity, high/low half, the value itself) is chosen **independently of the roll**, and the statement is always true. So "die 1 is odd" means exactly P(· | die 1 odd), with no "why did they tell me this?" adjustment.

**The key distinction.** Compare two shocks on Sum of 3d6:

- **"No odd numbers"** (experiment): *all three* unrolled dice become uniform on {2, 4, 6}. Fair value **12**.
- **"Die 1 has been rolled and is even"** (information): *only die 1* is restricted to {2, 4, 6}. Dice 2 and 3 are unchanged. Fair value 4 + 7 = **11**.

The two statements look alike, but they change the price by different amounts. And a later rule change affects dice 2 and 3 but never die 1, because die 1 has been rolled.

### Resolution changes (RESOLUTION CHANGE)

These change **how the answer is read**. The dice and cards are untouched, so you reprice the *new question* on the *same* experiment.

| Shock text (shortened) | Recompute |
|---|---|
| "The event now is 12 or more (it was 10)" | P(Sum of 3d6 ≥ 12) = 81/216 = 37.5% (down from 62.5%) |
| "Results now count if they are 4 or more (it was 5)" | # of 4 or more in 4d6: p from 1/3 to 1/2, fair value 4/3 → 2 |
| "The market now counts results that are 2 or less instead of odd" | # in 3d6: p from 1/2 to 1/3, fair value 3/2 → 1 |
| "The answer is now the sum of the HIGHEST TWO dice only" | Sum of 3d6 10.5 → top-2 sum 203/24 ≈ **8.46** |
| "The market now counts red cards instead of hearts" | Hearts in 5 cards 5/4 → red cards 5/2 |

**Common mistake.** Keeping the old denominator or the old indicator. After "counts 2 or less instead of odd", p is 2/6, not 3/6.

### Renormalise, condition, or rebuild?

| Situation | Method |
|---|---|
| Faces removed from dice still to roll | **Renormalise** each such die over the faces left (in proportion to their weights) |
| A rolled die's value or class is revealed | **Condition** that die on the statement; leave the others alone |
| Cards revealed | **Condition**: count the revealed cards, then draw the rest from what is left |
| Sides changed, dice added or removed, cards removed, draws changed | **Rebuild** the experiment from the rules in force |
| Threshold, condition or aggregation changed | **Re-read** the same experiment with the new question |

## Linked markets

At level 3, one pair of markets can read the **same dice**: for example the sum and the highest of 3d6, or the number of odd results and the sum. They open and settle together, and any rule change or information about the dice hits both. The answers are correlated: for 3d6, the sum and the highest have a correlation of about **0.76**. Being long both is close to one bigger long. The level 3 risk budget simply adds each market's one-σ risk, as if every position could go wrong at the same time. So it never understates a linked pair held the same way round, but it gives no credit for an offsetting position in the other market either.

## Common mistakes and edge cases

<details>
<summary>The wrong denominator after a restriction</summary>

"No odd numbers" on 2d6, then the event P(sum ≥ 10). Outcomes: 3 × 3 = 9 (each die on {2, 4, 6}). Sums ≥ 10: (4, 6), (6, 4), (6, 6). **3/9 = 1/3 ≈ 33.3%.** The mistake is 3/36: counting the surviving outcomes but dividing by the old total.

</details>

<details>
<summary>A shock that makes a sensible quote dangerous</summary>

You make 45 / 55 in P(Sum of 3d6 ≥ 11), fair 50. A rule change lands: "No numbers above 4". Fair value collapses to **6.25** (only (3, 4, 4) in three orders, and (4, 4, 4), reach 11 out of 64 outcomes). Your bid at 45 is now 38.75 points above fair. In that same round the sniper (levels 2–3) can sell to you at 45, up to 4 lots. Each lot loses about 38.75 × lot value on average. The lesson is not "you should have known". You could not have. It is to keep size small in markets where a single rule can move the price this far: events near 50%, and few dice with many possible restrictions.

</details>

<details>
<summary>"Impossible" is not "unlikely"</summary>

After "No numbers below 5" on 2d6, sums 2 to 9 are **impossible** (probability exactly 0), not merely unlikely; *possible now* shows 10–12. A bid above 12 or an offer below 10 is a guaranteed loss on every lot that trades: you pay more than any possible answer, or sell for less than any possible answer. The opposite mistake is just as common: treating a 3% event as impossible and offering it at 0 or 1. In this game the planner never makes a market's answer certain, so an event that is still possible never has a fair value of exactly 0 or 100.

</details>

<details>
<summary>Assuming independence for cards</summary>

Hearts in 5 cards is **not** binomial with p = 1/4. The mean is the same (5/4) but the variance is smaller: 5 × 1/4 × 3/4 × 47/51 ≈ 0.864, against 0.9375 for dice. And the first card being a heart changes the chance for the next one (12/51, not 13/52).

</details>

<details>
<summary>Confusing conditional and unconditional</summary>

P(sum of 2d6 ≥ 10) = 6/36 = 1/6. Given that *at least one die shows 6* it is 5/11 (of the 11 outcomes with a 6, five reach 10: (4,6), (5,6), (6,6), (6,5), (6,4)). Given that *die 1 shows 6* it is 3/6 = 1/2. The three answers differ because the conditions differ. Read the shock text exactly.

</details>

<details>
<summary>Treating a rule change as information, or the reverse</summary>

"No odd numbers" does not say the dice *were* even. They had not been rolled. "Die 2 is even" does not change die 3. Mixing the two moves your fair value the wrong amount (12 against 11 in the example [above](#information-reveals-new-information)).

</details>

<details>
<summary>Failing to reprice after a shock</summary>

The market keeps your old quote until you change it. **Measured** at level 2: never re-quoting cut mean P&L per game by about 40%. Acknowledge is for a shock that leaves your fair value where it was, never as a default.

</details>

## Checklist after a shock

- [ ] Which heading: RULE CHANGE, NEW INFORMATION or RESOLUTION CHANGE?
- [ ] Which dice or cards are affected: not yet rolled, rolled and partly known, revealed?
- [ ] Renormalise, condition or rebuild? Read the rules in force, not the old title
- [ ] New exact fair value, new σ, new *possible now*
- [ ] Mid at the new fair value; half-spread in the new σ; size reconsidered
- [ ] Linked market on the same dice repriced too
- [ ] ⚡ trades in the report: what did the stale quote cost, and is the position still one I want?
