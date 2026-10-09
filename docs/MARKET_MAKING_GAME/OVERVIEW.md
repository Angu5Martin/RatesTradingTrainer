# Market Making Game: how to play well

The shared playbook for both kinds of market in the game. It explains what a quote does, how the bots decide whether to trade with you, how to choose width, skew and size, how to run several markets at once and how to read the debrief.
The two specialist guides build on it:

- [World markets](WORLD_MARKETS.md): estimating facts and quoting when you are not sure of the answer.
- [Probability markets](PROBABILITY_MARKETS.md): exact probabilities, mental maths and repricing after shocks.

The rules of the game itself (statuses, levels, accounting) are in [`docs/MARKET_MAKING_GAME.md`](../MARKET_MAKING_GAME.md). Everything here is written from the code in `src/rates_trainer/mmgame/`. Where a number is a measurement rather than a rule, it says so.

**Contents:** [The loop](#the-loop) · [Your side of every trade](#your-side-of-every-trade) · [Fair value and expected profit](#fair-value-and-expected-profit) · [How the bots decide](#how-the-bots-decide) · [Choosing your width](#choosing-your-width) · [Inventory, skew and size](#inventory-skew-and-size) · [Shocks and stale quotes](#shocks-and-stale-quotes) · [Running several markets](#running-several-markets) · [What changes by level](#what-changes-by-level) · [Reading the debrief](#reading-the-debrief) · [Checklists](#checklists)

---

## The loop

Every market asks for one number. You post a **bid** (where you buy), an **offer** (where you sell) and a **size** (the most lots you will trade on each side in a round). Then you press *Play round*. Within a round, things happen in a fixed order:

| Step | What happens | What you can do about it |
|---|---|---|
| 1. Normal flow | Each bot may look at each open, quoted, unpaused market and trade at your bid or offer | Your quote, size and pauses, set before you pressed Play |
| 2. Shocks | Scheduled shocks land: rules, information or the settlement rule change | Nothing in this round: you learn about it in the report |
| 3. Fast reaction | The fast bots (sniper at levels 2–3, informed bots at level 3) trade in the shocked markets **against the quote you still have there** | Only what you chose beforehand: size, width, inventory, pausing |
| 4. Resolution | Markets due this round settle | Nothing: the position you hold is settled at the answer |

Then you read the report, re-quote, pause, resume or acknowledge, and play the next round. The game is turn-based: think as long as you like.

The mental loop to run on every market, every round:

**Estimate → How sure am I? → Quote (mid, width, size) → Who traded with me, and why? → Position → Re-quote**

## Your side of every trade

The game's accounting is the one in `markets.py`. You never have to guess the sign:

| A bot… | It trades at your… | You… | Your position | Your cash |
|---|---|---|---|---|
| buys | **offer** (it *lifts* your offer) | **sell** | −q | + q × offer × lot value |
| sells | **bid** (it *hits* your bid) | **buy** | +q | − q × bid × lot value |

At resolution: `cash += position × settlement × lot value`, and **P&L = cash**. Before then, *open P&L* marks your position at **your own mid**, never at a hidden fair value. So open P&L tells you nothing about whether you are right: a big open profit from a mid that is in the wrong place disappears at settlement.

**Lot value** is chosen so that one standard deviation of the question's starting uncertainty is worth about 100 credits per lot: the nearest of 1, 2 or 5 × a power of ten to `100 / σ₀`. Two useful consequences:

- **You can read the starting uncertainty from the lot value:** `σ₀ ≈ 100 / lot value`, correct to within a factor of about 1.6 (the rounding to 1, 2, 5). A world question with a lot value of 20 started with a typical error of about 5 units, so a 1-unit spread on it is very tight.
- **Risk is comparable across markets.** A lot of a dice sum and a lot of a historical year each carry roughly 100 credits of one-σ risk at the start.

The portfolio's **Risk** column is `|position| × lot value × σ now` (credits, one σ). When you hold a position, `σ now = risk / (|position| × lot value)`: the uncertainty the game says is left in the question after everything announced.

## Fair value and expected profit

**Principle.** The money in market making comes from trading at prices better than fair value. It does not come from your quotes being hit.

**Reasoning.** Let F be fair value (the expectation of the settlement given what is public), h your half-spread and m your mid. A bot that buys q lots at your offer m + h has given you, at that moment,

```text
edge (per trade) = q × (offer − F) = q × h  +  q × (m − F)
                   └ spread capture ┘   └ mispricing ┘
```

(signs mirror for a purchase at your bid). The edge is yours **on average**: the answer will land above or below F, and that part is luck. Two things turn a good-looking spread into a loss:

1. **Mispricing.** If your mid is 0.6σ below fair and your half-spread is 0.3σ, every lot sold at your offer is 0.3σ *below* fair: negative edge on every trade on that side. Worse, the bots that trade with you are the ones who can see it (next section).
2. **Adverse selection.** A counterparty who knows more than F trades with you exactly when you are wrong. Your edge at F looks positive, and the outcome is negative on average. The spread is what pays for this.

<details>
<summary>Worked example: the same spread, a good mid and a bad one</summary>

Sum of 3d6: fair value 10.5, σ ≈ 2.96, lot value 50, tick 0.1.

- **Good mid.** You quote 9.0 / 12.0 (mid 10.5, half-spread 1.5 ≈ 0.5σ). A retail bot buys 1 lot at 12.0: you sell 1, cash +600. Edge = 12.0 − 10.5 = 1.5 points × 50 = **+75 credits**: all spread capture.
- **Bad mid.** You quote 7.4 / 10.4 (mid 8.9, 0.54σ below fair, same half-spread). The value fund buys 1 at 10.4: edge = 10.4 − 10.5 = −0.1 × 50 = **−5 credits** = spread capture +75 + mispricing −80. Your offer is below fair, and the counterparties best placed to see it are the ones that take it.
- Either way, the settlement then adds or subtracts luck: a roll of 14 costs you (14 − 12.0) × 50 = 100 on the first trade and (14 − 10.4) × 50 = 180 on the second. On average the roll adds nothing. The edge stays with you.

</details>

**Best practice.** Get the mid right first, then choose the width. The spread is not a cushion that fixes a bad mid. It is a fee that pays for the trades you will lose to better-informed counterparties.

**Common mistake.** Judging a quote by whether it traded. A quote that never trades earns nothing. A quote that trades every round on the same side is usually telling you the mid is wrong.

## How the bots decide

All bots are deterministic: when a bot looks and how noisy it is are fixed by `(seed, round, market, bot)`. Only their *decision* depends on your quote. A bot forms an estimate of fair value and trades **only** at your bid or offer, and only if your price beats its estimate by at least its threshold (measured in the market's current σ, floored at two ticks):

```text
bot buys at your offer   if   estimate − offer ≥ threshold × σ
bot sells at your bid    if   bid − estimate   ≥ threshold × σ
size = 1 + gain × (edge − threshold)  (whole lots, capped by its maximum, your size, your limit and the risk budget)
```

| Bot | Looks (normal flow) | Its estimate | Threshold | Max lots | Levels | What it punishes |
|---|---|---|---|---|---|---|
| Retail flow | 75% | fair value ± 0.8σ noise | −0.05σ (pays a little to trade) | 1 | all (two of them) | nothing: it pays you the spread, and dries up as you widen |
| Value fund | 50% | fair value ± 0.25σ | 0.2σ | 2 | all | a mid that is off fair value |
| Slow money | 55% | fair value **two rounds ago** ± 0.3σ | 0.15σ | 2 | all | rarely anything: after a shock it trades on old information |
| Fast money (sniper) | 20%, and 100% just after a shock | fair value ± 0.08σ | 0.25σ | 4 | 2, 3 | stale quotes after a shock |
| Informed | 55%, and 80% just after a shock | **the true answer** under the rules in force, ± 0.05σ | 0.35σ | 4, and each at most 5 lots a round across all markets | 3 (two of them) | tight spreads, big size, quotes far from the truth |

What follows from the table (each is a consequence of the rule above, not a separate rule):

- **Retail is the income.** Its noise (0.8σ) is large, so it trades on both sides of a centred quote. The wider you are, the less often its estimate clears your price.
- **The value fund is the alarm.** With noise of 0.25σ and a threshold of 0.2σ, it rarely trades a reasonably wide quote whose bid is below fair and whose offer is above it. Repeated value-fund trades on one side mean that side has crossed fair by about 0.2σ or more: your mid is off by roughly your half-spread plus 0.2σ.
- **The sniper only matters after a shock.** It reacts in the same round, before you can, and trades size if the shock moved fair value past your stale price by more than 0.25σ.
- **The informed bots are rationed, not random.** At level 3 each takes its largest edges first, up to 5 lots a round across the table. Their *absence* is weak information: if a market keeps trading only small, two-way size, the truth is probably not far outside your quote.
- **Labels depend on level.** Level 1 shows the full type ("Value fund"), level 2 a coarse one ("Fund", "Prop"), level 3 none. Even without a label, the round report shows **size** and **timing** (⚡ marks a trade made just after a shock). Those two are the main clues to who traded with you.

## Choosing your width

**Principle.** Width trades frequency against edge and protection. The right width is a multiple of the uncertainty (σ), not a number of ticks.

**Reasoning.** Retail fills fall as the half-spread grows (fewer noisy estimates reach your price). The edge per fill rises one-for-one with the half-spread. Adverse selection, where present, takes a roughly fixed bite per informed trade, so it argues for more width. The game's own measurement shows the trade-off:

**Measured, not a rule:** mean P&L per game over 40 seeds per level, default table size, quotes centred **exactly** on fair value, re-quoted every round, 1 lot a side (`scripts/measure_game_policies.py`, which plays the real engine). A human's mid is noisier, so treat these as upper bounds.

| Half-spread (× σ) | Level 1 | Level 2 | Level 3 |
|---|---|---|---|
| 0.1 | +283 | +571 | −827 |
| 0.2 | +498 | +890 | −178 |
| 0.3 | +598 | +1,148 | +373 |
| 0.5 | +721 | +1,518 | +1,097 |
| 0.8 | +764 | +1,658 | +1,445 |
| 1.2 | +501 | +1,063 | +1,186 |

(Standard deviation across games is roughly 300–1,000 credits, so differences of a few hundred between neighbouring rows are not meaningful on their own.)

**Best practice.**

- Start around **0.5σ either side** of your estimate when you are confident in the mid; at level 3, nearer **0.8σ**. Below about 0.3σ, level 3 markets lost money on average: the informed bots take more than the spread earns.
- **Widen in proportion to your own uncertainty about the mid**, not just the question's σ. In a world market where you could be off by 2σ, a 0.5σ half-spread is a mispriced quote waiting to be found.
- Very wide (above about 1σ) is safe and dull: little flow, little learning.

**When it changes.** If you know something the public does not (a world fact you are certain of), you want the flow that disagrees with you: centre on your answer and keep the width moderate. That is covered in [World markets](WORLD_MARKETS.md#when-you-know-better-than-the-crowd).

**Common mistake.** Copying the width of one market to another. Ticks differ, and σ differs by orders of magnitude between "heads in 8 flips" (σ = 1.41) and "a year in the 1800s" (σ of several years).

## Inventory, skew and size

**Position limit.** Each market has a limit (±6 lots at level 1, ±5 at level 2, ±4 at level 3). When a trade would take you past it, that side is **closed**: the card shows *BID CLOSED* or *OFFER CLOSED*, and nobody can trade it. A closed side is not a safety net. It also means you collect no spread on that side.

**Risk budget (level 3).** All open positions together may carry at most 1,100 credits of one-σ risk (the sum of the Risk column). A trade that would add risk beyond it does not happen, and a trade that reduces risk always does. A full budget therefore silently shuts the risk-adding side of *every* market.

**Skew.** Moving both sides of your market together changes which side trades without changing the width.

| You are | You want | Skew | The side you make attractive |
|---|---|---|---|
| long (bought lots) | to sell | **down** (◀ on the card) | your offer: bots buy from you |
| short (sold lots) | to buy | **up** (▶) | your bid: bots sell to you |

**Measured:** at levels 1 and 2, skewing by 0.6σ × (position ÷ limit) cut the game-to-game standard deviation of P&L by about a sixth to a quarter, for a mean that was the same within noise (level 1: 721 → 710 mean, 424 → 354 sd; level 2: 1,518 → 1,424, 609 → 457). There, skew is a risk tool. At level 3 it also *raised* the mean (1,097 → 1,509): inventory that informed bots handed you is the inventory you most want to get rid of, and skewing unloads it onto uninformed flow.

**Size.** Size multiplies whatever edge you have, good or bad. Retail only ever trades 1 lot, so extra size mostly reaches the bots that trade bigger: the value fund, the sniper and, at level 3, the informed bots. **Measured:** at levels 1 and 2, quoting the maximum size instead of 1 lot changed mean P&L very little (level 2: 1,518 → 1,442). At level 3 it cost about a third (1,097 → 762 at a 0.5σ half-spread).

<details>
<summary>Worked example: the risk budget at level 3</summary>

Three open positions (risk = |lots| × lot value × σ now):

| Market | Position | Lot value | σ now | Risk |
|---|---|---|---|---|
| Sum of 3d6 | +3 | 50 | 2.96 | 444 |
| P(Sum of 3d6 ≥ 10) | −4 | 2 | 48 | 384 |
| A year question | +2 | 20 | 5 | 200 |
| **Total** | | | | **1,028** of 1,100 |

A bot that would sell you one more lot of the dice sum (adding 148 of risk) cannot: the budget would reach 1,176, so your bid there is effectively closed. A trade that shrinks a position can always happen: a bot buying from you in the dice sum or the year question, or selling to you in the event. The budget is in the summary strip, and the risk-adding side of every market goes quiet as it fills.

</details>

**Best practice.** Quote 1–2 lots unless you are confident in the mid and nothing is due to happen. Cut size first, before widening, in markets where a shock or an informed trader would hurt most.

**Common mistake.** Skewing *with* your position ("I'm long because it's cheap, let me buy more"). The debrief marks such quotes "skewed the same way as inventory (adds risk)".

## Shocks and stale quotes

Every shock has a category, shown as its heading:

| Heading | What changed | What did **not** change |
|---|---|---|
| RULE CHANGE | the experiment, for the trials not yet rolled (faces, sides, loading, number of dice, the deck, the number of draws) | anything already rolled or revealed; the settlement rule |
| NEW INFORMATION | something true about trials already rolled (a die's value or parity, cards drawn), or a confirmed bound on a world answer | the experiment and the settlement rule |
| RESOLUTION CHANGE | how the answer is read (threshold, what is counted, which dice count, a nearby definition of a fact) | the dice, cards or facts themselves |

What happens to you in the round a shock lands:

1. Your quote was set before the shock, so it is now **stale**: the card shows *STALE*, and the market turns *SHOCKED*.
2. In that same round, the sniper (levels 2–3) and the informed bots (level 3) may trade against it **before you can react**. Those trades are marked ⚡.
3. Next round, the market keeps the stale quote unless you **re-quote**, **acknowledge** (keep it deliberately) or **pause** it.

The stale-quote risk in a shock round depends only on decisions you took earlier: your **size**, your **width** and your **inventory**. You cannot see a shock coming. You can see that a market still has several rounds to run, and the planner only schedules a shock for a round in which the market stays open for at least one more round.

**Best practice after a shock:** read what changed, recompute (the specialist guides show how), then re-quote at once. **Measured:** at level 2, never re-quoting cut mean P&L from about 1,518 to 895 per game.

**When pausing is right.** Pause a market when you cannot price it yet (you need time to work out a new distribution) and holding a stale quote would cost more than the spread you would collect. A paused market keeps your position and your quote. It gets no flow, and quoting it again resumes it.

**Common mistake.** *Acknowledging* without recomputing. Acknowledge is for a shock that genuinely does not move your fair value (for example, information about a die that your market does not read).

## Running several markets

With five to eight markets, attention is the scarce resource. Triage in this order every round:

1. **Shocked markets** (amber cards, also listed in the banner under the summary strip, where each code opens the market): recompute and re-quote, or pause.
2. **Markets resolving next round** (*1 round left*): the position you hold now is settled at the answer. Reduce it by skewing if it is a bet you do not want.
3. **Markets near their limit or a closed side:** decide whether you *want* that inventory.
4. **Markets with one-sided flow** in the report: is your mid wrong?
5. Everything else: leave it unless you have a reason.

**Linked markets (level 3).** Two markets can read the **same dice**, for example the sum and the highest of 3d6. A rule change to the dice hits both at once, and both settle together. Their answers are positively correlated: a long position in both is close to one larger bet. Treat them as one risk when sizing.

**The risk budget couples everything.** At level 3, being long four lots of one market can shut the risk-adding side of another. Spend the budget where your edge is largest. That usually means a probability market you can price exactly, not a world question you are guessing.

## What changes by level

From `levels.py`:

| | Level 1 Beginner | Level 2 Intermediate | Level 3 Advanced |
|---|---|---|---|
| Markets (min / default / max) | 2 / 3 / 4 | 3 / 5 / 6 | 4 / 7 / 8 |
| Rounds | 8 | 12 | 14 |
| Markets that open late | 0 | 2 | 3 |
| Shocks per game | 0–1: information or rule changes | 2–4: all three kinds | 5–8: all three kinds, larger |
| Smallest move of a non-information shock | any | 0.35σ | 0.6σ |
| Bots | 2 retail, value fund, slow money | + sniper | + 2 informed |
| Counterparty labels | full | coarse | none |
| Position limit / max size | ±6 / 3 | ±5 / 4 | ±4 / 4 |
| Risk budget | none | none | 1,100 credits |
| Coach (edge of each trade shown live, probability markets) | on | off | off |
| World questions drawn from difficulty | 1 | 1–2 | 1–3 |
| Linked markets | no | no | one pair |

Where to focus at each level:

- **Level 1: get the mid right.** The coach shows the edge of each probability-market trade against fair value as it happens. A run of negative edges on one side is a mispriced mid. There are no informed bots, so the measured cost of being tight is only the lost edge.
- **Level 2: re-quote after shocks and manage inventory.** The sniper turns every stale quote into a loss, and shocks can move fair value by 0.35σ or more. Late-opening markets arrive while you already hold positions elsewhere.
- **Level 3: price the information.** Two informed bots, no labels, a shared risk budget and linked markets. **Measured** (same script as above): at a 0.5σ half-spread, adverse selection cost about 1,800 credits a game on average (about 1,200 at 0.8σ), and quoting the maximum size instead of 1 lot cut mean P&L from about +1,097 to +762. Width, size, skew and the budget are the levers.

## Reading the debrief

The debrief opens when the last market resolves. It names everything that was hidden: the seed, fair value at every trade, which bots were informed and the shock plan. It splits P&L exactly (in fractions, so the lines add up to the credit):

```text
P&L = edge + adverse selection + news drift + settlement luck
edge = spread capture + mispricing
decision result = edge + adverse selection
luck = news drift + settlement luck
```

| Line | Definition (per trade of q lots at price p, fair value F then, F_end just before settlement, settlement S) | Read it as |
|---|---|---|
| Spread capture | q × half your quoted spread | what the width earned |
| Mispricing | q × (your mid − F) on a sale, q × (F − mid) on a purchase | where your mid was: negative when it sat on the wrong side of fair |
| Adverse selection | (F_end − F) + (S − F_end), signed, **on informed trades only** | what better-informed bots took: the cost the spread must cover |
| News drift | signed q × (F_end − F) on uninformed trades | shocks and clues moving fair value after you traded: luck |
| Settlement luck | signed q × (S − F_end) on uninformed trades | the answer landing above or below its expectation: luck |

<details>
<summary>Worked example: one trade, split</summary>

You quote 9.0 / 12.0 on Sum of 3d6 (fair 10.5, lot value 50). A bot buys **2 lots at 12.0**: you are short 2. A shock later raises fair value to 12.0 (F_end), and the dice settle at 14 (S).

| Line | Calculation (points × lots × 50) | Credits |
|---|---|---|
| Spread capture | half-spread 1.5 × 2 | +150 |
| Mispricing | (mid 10.5 − F 10.5) × 2 | 0 |
| News drift | −2 × (12.0 − 10.5) | −150 |
| Settlement luck | −2 × (14 − 12.0) | −200 |
| **Total** | 2 × (12.0 − 14) | **−200** |

Decision result +150, luck −350. If the bot had been informed, the −350 would be reported as **adverse selection** instead of luck, and the decision result would be −200: the spread did not cover what it knew.

</details>

How to use it:

- **Judge yourself on the decision result, not the total.** A positive decision result with negative luck was a good game.
- **Quote verdicts** use fixed thresholds: *centred* if your mid was within 0.3σ of fair; *skewed to reduce inventory (sensible)* if it leaned against your position by up to 0.9σ; *skewed the same way as inventory (adds risk)* if it leaned with your position by more than 0.3σ; *off fair value* otherwise. Separately, the spread is *tight* if your half-spread was under 0.12σ and *wide* if over 1.3σ.
- **Trade causes** sort every trade: good (won at a fair-or-better price), luck (lost at a fair-or-better price), lucky (won at a poor price), stale, mispriced, informed, informed-priced (an informed bot traded with you but your spread covered its edge at the time).
- **Shock table:** for each shock, how far fair value moved (in σ), how far your quote was from the new fair value, and whether you re-quoted at once. *Key decisions* flags a shock that left your quote more than 0.5σ from the new fair value when you did not re-quote before the next round.
- **World markets are special:** their fair value is the crowd's belief, which is off the truth on purpose. If you knew better than the crowd, your trades look *mispriced* and the gain arrives as *settlement luck*. Read those two lines together ([World markets](WORLD_MARKETS.md#when-you-know-better-than-the-crowd)).

**A caveat at level 3 (measured, and worth knowing).** The debrief books every uninformed trade's later moves as luck, which averages zero only if that trade is unrelated to what the informed bots knew. At level 3 it is not always unrelated: when an informed bot fills you up and you then skew, the uninformed flow that unwinds your position does so at a time chosen by the informed trade. In the measurement above, the "luck" lines averaged about +730 credits a game with plain quoting and about +1,440 with skew, against −130 and −90 (within noise of zero) at levels 1 and 2. Part of what level 3 calls luck is recovered adverse selection: a reward for reacting to informed flow.

**Common mistake.** Concluding from one game. With a standard deviation of several hundred credits per game, a strategy needs several games before its results mean anything. The decision result is far less noisy than the total; use it.

## Checklists

**Before every round**

- [ ] Every shocked market re-priced, paused, or acknowledged on purpose
- [ ] Every mid where I believe fair value is, not where it was
- [ ] Width ≈ 0.5σ, wider where my estimate is shaky, never under 0.3σ at level 3
- [ ] Size small where a shock or an informed trader would hurt
- [ ] Positions I would not want settled now are skewed to reduce
- [ ] Risk budget (level 3) spent on the markets I can price best

**After every round**

- [ ] Which trades were ⚡ (just after a shock)? What did they cost?
- [ ] Any market where the same side traded again? Is my mid wrong?
- [ ] Any closed side? Do I want that inventory?
- [ ] What resolves next round?

**After the game**

- [ ] Decision result positive? If not: mispricing, stale quotes or adverse selection?
- [ ] Which shocks did I not re-quote after, and what did it cost?
- [ ] Which counterparties made money from me, and could I have seen it in size and timing?
