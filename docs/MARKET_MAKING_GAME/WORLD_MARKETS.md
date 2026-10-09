# World markets: quoting what you are not sure of

How to make markets on questions about history, geography, politics, economics, sport, culture and science: forming an estimate, sizing your uncertainty, turning both into a quote, and handling the wording, units and redefinitions that decide what a market actually settles on. Read the [overview](OVERVIEW.md) first for how quotes, bots and P&L work. Dice, coins and cards are in [Probability markets](PROBABILITY_MARKETS.md).

The worked examples here use definitions, arithmetic or clearly labelled hypothetical figures. None of them is a question from the game's bank, and none should be read as an authoritative statement of a fact.

**Contents:** [How a world market works](#how-a-world-market-works) · [Estimating fair value](#estimating-fair-value) · [Quick estimation and mental arithmetic](#quick-estimation-and-mental-arithmetic) · [Quoting under uncertainty](#quoting-under-uncertainty) · [When you know better than the crowd](#when-you-know-better-than-the-crowd) · [Clues and redefinitions](#clues-and-redefinitions) · [Resolution and edge cases](#resolution-and-edge-cases) · [Worked examples](#worked-examples) · [Checklist](#checklist)

---

## How a world market works

Each market is one item from a curated local bank (`mmgame/data/world_questions.toml`). What you see:

| Field | Where | What it tells you |
|---|---|---|
| Question | card title and detail panel | what is asked, in words |
| Unit | card and detail | what the number is measured in ("year", "metres", "countries", a blank for a plain count) |
| Rule | detail: *Settles on the true value of: …* | **the exact definition the market settles on**: dates ("on 1 January 2026"), rounding ("to the nearest metre"), scope ("land borders only") |
| Range | detail: *quotes from … to …* | the settlement range. Every quote must lie in it and the answer lies in it. **It is a bound, not an estimate**: answers are not placed at its midpoint |
| Possible now | detail and card | the range narrowed by any confirmed clues |
| Tick | detail | the smallest price step (1 for years and counts, finer for measured quantities) |
| Lot value | detail | credits per lot per unit; `100 / lot value` ≈ the crowd's typical error at the start (see below) |

The answer and the reference source are shown only when the market resolves.

**The crowd.** For every world question the game holds a hidden *public belief*: a normal distribution centred on a crowd guess that is off the true answer by a random amount, typically about one "typical error" (the bank's `spread` for that item; the offset is a standard normal draw, capped at ±2). The belief is truncated to the range and to any confirmed clues. Its mean is the **fair value** the uninformed bots trade around, and the one the debrief measures your edge against. Three consequences:

- **The crowd is unbiased but not right.** Across many questions its errors average zero. On any one question it can be off by one or two typical errors.
- **You can know better.** If you are confident of the answer, the uninformed bots' disagreement with you is a source of profit (see [below](#when-you-know-better-than-the-crowd)).
- **At level 3 two informed bots know the true answer**, under whatever definition is in force. Their trades point towards it.

**Reading the crowd's uncertainty from the lot value.** The lot value is the nearest of 1, 2 or 5 × a power of ten to 100 ÷ the typical error. So:

```text
σ₀ (the crowd's typical error at the start) ≈ 100 / lot value      (within a factor of about 1.6)
lot value 20  →  σ₀ ≈ 5 units          lot value 1  →  σ₀ ≈ 100 units          lot value 0.5  →  σ₀ ≈ 200 units
```

That is the yardstick for your width. Once you hold a position, the portfolio's risk column gives the current value: σ now = risk ÷ (|position| × lot value).

## Estimating fair value

**Principle.** A defensible estimate is built from things you know, and every step can be checked. The number that first comes to mind is not an estimate.

### Separate what you remember from what you infer

| You have | Example of the thought | How sure |
|---|---|---|
| A remembered fact | "I have read this exact figure" | as sure as the memory; check the rule's definition and date |
| A remembered anchor | "it happened a few years after X, which I know" | the anchor's precision plus the uncertainty of "a few years" |
| A reference class | "buildings of this kind are usually 100–300 m" | the spread of the class: wide |
| A decomposition | "people × share × rate" | the product of each factor's uncertainty: often wider than you feel |
| Nothing | "no idea" | say so: wide and small, and let the flow teach you |

**Best practice.** Write the chain down mentally ("anchor 1950s, then 'a decade later', so 1960s"). Each link widens the range. If you cannot name a link, you are guessing.

**Common mistake.** Anchoring on the number in the question's neighbourhood: the range's midpoint, a nearby round number, or the previous question's answer. The range is set so the answer lies inside it, nothing more.

### Bracket before you centre

Start with numbers you are *sure* are too low and too high, then tighten each until you would no longer bet on it. For quantities that span factors of ten (populations, areas, distances), centre on the **geometric** middle of the bracket, not the arithmetic one:

```text
bracket 1,000 to 100,000      arithmetic middle 50,500      geometric middle √(1,000 × 100,000) = 10,000
```

If you are equally unsure about "×10 too high" and "×10 too low", the geometric middle is the honest centre. The arithmetic middle puts almost all your weight near the top.

### Recognise when you do not know enough

Ask: *could I be off by more than the crowd's typical error (100 ÷ lot value)?* If the honest answer is yes, the crowd probably knows more than you do. Then the right quote is wide and small, and the flow you receive is your best information (see [Quoting under uncertainty](#quoting-under-uncertainty)).

## Quick estimation and mental arithmetic

Each shortcut is exact or a stated approximation. Each says when it misleads.

| Shortcut | Derivation | When it misleads |
|---|---|---|
| x% of y = y% of x | x/100 × y = y/100 × x | never: use whichever is easier (8% of 25 = 25% of 8 = 2) |
| up x% then down x% is **not** zero | (1 + x)(1 − x) = 1 − x² | small for small x (−1% after +10%/−10%), large for big moves (−25% after +50%/−50%) |
| Percentage change from A to B | (B − A)/A, relative to the **start** | the change from B back to A has a different percentage |
| Percentage points versus per cent | 40% → 50% is +10 points and +25% | wording: "rose 10%" of a rate is ambiguous; read the rule |
| Doubling time ≈ 70 / growth rate in % | ln 2 = 0.693 and ln(1 + r) ≈ r for small r | rough above ~10%: at 10% the exact doubling time is 7.3 years (rule: 7). "Rule of 72" is closer near 6–10% |
| Compound growth over n years | (1 + r)ⁿ ≈ 1 + n r when n r is small | n r above ~0.2: 5% for 10 years is ×1.63, not ×1.5 |
| km/h to m/s | divide by 3.6 (1 km/h = 1,000 m / 3,600 s) | exact |
| Average speed over equal distances | harmonic mean: 2ab/(a + b) | the arithmetic mean is wrong: 60 out and 40 back averages 48 km/h, not 50 |
| Time = distance / speed | definition | mixed units: check hours against minutes |
| Weighted average | Σ wᵢ xᵢ / Σ wᵢ | weights that do not sum to what you think (shares of different totals) |
| Seconds in a year ≈ π × 10⁷ | 365.25 × 86,400 = 31,557,600 | 0.45% high: fine for orders of magnitude, not for a tight market |

**Exact unit conversions** (international definitions; use these, not memory of rounded versions):

```text
1 inch = 2.54 cm            1 foot = 0.3048 m           1 mile = 1.609344 km         1 nautical mile = 1.852 km
1 pound = 0.45359237 kg     °F = °C × 9/5 + 32           20 °C = 68 °F                1 hectare = 10,000 m²
1 km² = 100 hectares        1 day = 86,400 seconds (a civil day; see the edge case below)
```

<details>
<summary>Worked example: a Fermi decomposition with stated assumptions</summary>

*Hypothetical question:* how many primary-school teachers work in a country of 10 million people?

1. Children of primary age: if about 7 of 80 years of life are primary years, roughly 10m × 7/80 ≈ **0.9m** pupils. Assumption: a flat age distribution; a young or old population moves this by ±30%.
2. Pupils per teacher: assume **15 to 25**.
3. Teachers ≈ 0.9m / 20 ≈ **45,000**, bracket 0.9m/25 ≈ 36,000 to 0.9m/15 = 60,000, before the age-distribution uncertainty.
4. Combine: each factor is uncertain by ±20–30%, so the result is uncertain by roughly ±40% (independent errors add roughly in quadrature on a log scale). Centre 45,000; a one-σ range of roughly 30,000–65,000.

The point is the structure: every number above is an assumption, stated, and the width follows from them. In a market this belongs in the "wide and small" category unless you have a better anchor.

</details>

## Quoting under uncertainty

**Principle.** The quote has two jobs. The mid is your best estimate of where the answer is. The width covers two things: your uncertainty about that estimate, and the counterparties who may know more than you.

**Reasoning.** Write σ_you for how far off your estimate could be (one standard deviation, your honest view) and σ₀ ≈ 100 / lot value for the crowd's typical error.

| Your situation | Mid | Half-spread | Size |
|---|---|---|---|
| You know it (σ_you much smaller than σ₀) | your answer | about 0.5σ₀ | normal (1–2 lots) |
| Informed guess (σ_you ≈ σ₀) | your estimate | about 0.5–0.8σ₀ | 1 lot |
| Weak guess (σ_you > σ₀) | your estimate, adjusted by the flow | about σ_you or more | 1 lot |
| No idea | the middle of what you can rule in, *not* of the range | wide | 1 lot, or pause after you learn something from flow |

These are heuristics built on the bot model, not formulas. **Measured** across all market types (see [Choosing your width](OVERVIEW.md#choosing-your-width)): with a perfect mid, half-spreads of 0.5–0.8σ did best, and below 0.3σ lost money at level 3. With an uncertain mid, the true optimum is wider.

**Reading the flow.** Uninformed bots estimate around the crowd's fair value. So:

- **One-sided flow from careful counterparties** (the value fund: up to 2 lots, labelled *Value fund* at level 1 or *Fund* at level 2) means the crowd's fair value is beyond your quote on that side. Bots keep buying your offer? The crowd thinks the answer is higher.
- **Retail trades on both sides** are not informative: retail noise is large.
- **At level 3, size is a clue even without labels.** In normal flow retail trades 1 lot and the value fund and slow money at most 2. A **3- or 4-lot** trade can only come from the sniper (which estimates around the crowd) or an informed bot (which knows the answer). An informed bot trades only when the answer is at least 0.35σ beyond your price.

**Blend, don't flip.** If your estimate is good (σ_you < σ₀), one-sided flow is *the crowd disagreeing*, and the crowd is the one likely to be wrong: keep your mid and let the flow pay you. If your estimate is weak, move your mid part of the way towards the flow. Moving all the way means giving up your own information.

**Two kinds of uncertainty.** Uncertainty about the **answer** ("is it 1,850 or 1,950 m?") is solved by width. Uncertainty about the **question** ("does 'height' include the antenna?", "as of which date?") is solved by reading the rule. If the rule does not settle it, it is genuine extra risk that a shock may make worse (a [redefinition](#clues-and-redefinitions)): quote smaller.

**Common mistake.** Overconfidence after one correct estimate. A run of good results on easy questions says little about the next, harder one. Size by your uncertainty on *this* question.

## When you know better than the crowd

This is where world markets reward knowledge, and where the debrief's numbers need care.

**Principle.** If you are confident the answer is A and the crowd's fair value F differs from it, centre on A. The bots that disagree with you are the profit.

**Reasoning.** Suppose the crowd's belief sits above the truth: F > A. You quote around A. The value fund sees your offer below F and buys from you, so you sell, and at settlement the answer is A: you keep the difference. The more the crowd is off, the more flow you get, up to your position limit.

**What the debrief shows.** Edge is measured against F, the crowd's fair value. So these trades are booked as **negative mispricing**: you sold below "fair". The gain arrives as **positive settlement luck**: the answer came in below F. Read the two lines together. In world markets, persistent negative mispricing plus positive settlement luck in the same market means you beat the crowd. It is not two separate accidents.

**When it changes.**

- If you are *not* sure, the same pattern can just as easily be two separate accidents. Most of the time the crowd is closer than a weak guess.
- At level 3, the informed bots also know the answer. If they trade *against* your "known" answer, check the rule's definition and date before doubling down.
- Your position limit caps the reward: at the limit, the closed side means no more flow.

## Clues and redefinitions

Two kinds of shock hit world markets.

### NEW INFORMATION: a confirmed bound

Text: *"Information: it is confirmed that the answer is at least X"* (or *"below X"*). The statement is **true**. Its threshold is chosen from the crowd's guess (at the guess, or 0.6 typical errors either side of it), **never from the answer**, so the only information in it is its direction. The question and the settlement rule are unchanged.

**How to reprice.** Cut off the impossible side of your belief and take the mean of what is left. For a normal belief with mean μ and standard deviation σ (continuous formulas; the game uses the same model on a fine grid and also respects the range):

```text
"at least X":  α = (X − μ)/σ    new mean = μ + σ · φ(α) / (1 − Φ(α))
"below X":     β = (X − μ)/σ    new mean = μ − σ · φ(β) / Φ(β)
φ = standard normal density, Φ = its cumulative distribution;  φ(0) = 0.399, Φ(0) = 0.5;  φ(0.6) = 0.333, Φ(0.6) = 0.726
```

<details>
<summary>Worked example: a clue at the crowd's guess</summary>

Hypothetical: your belief is centred on 1900 with σ = 10 (years). A clue: *"it is confirmed the answer is at least 1900."*

- α = 0, so the new mean is 1900 + 10 × 0.399/0.5 ≈ **1908**, and σ shrinks to 10 × √(1 − 2/π) ≈ **6.0**.
- Your old market 1895 / 1905 (half-spread 0.5σ) now has its offer **3 years below** the new fair value. The sniper (levels 2–3) buys it in the shock round if the gap is more than 0.25σ of the new uncertainty; here it is 3/6 = 0.5σ.
- Re-quote around 1908 with the new σ: about 1905 / 1911.

If the clue had been *"below 1906"* instead (β = 0.6): new mean 1900 − 10 × 0.333/0.726 ≈ **1895.4**.

</details>

**Common mistake.** Moving only to the threshold ("at least 1900, so 1900"). The answer is now *at least* 1900, so its expectation is above 1900.

### RESOLUTION CHANGE: the market is redefined

Text: *"Resolution change: the market is redefined. It now settles on: … The underlying facts are unchanged, and earlier clues no longer apply."* Only 18 items in the bank have an alternative definition. Typical pairs are the date a treaty was **signed** against the date it **entered into force**, a count **with or without** a borderline member, or the same statistic on a **different date**.

**How to reprice.**

1. Read the new rule as a new question.
2. Use what you know about the *relationship* between the two definitions. A treaty enters into force on or after the date it was signed, often a year or more later after ratification. A count without a borderline member is one lower.
3. Discard earlier clues: they were about the old definition, and the game drops them.
4. Re-estimate your uncertainty. You may know one definition well and the other poorly.

**Common mistake.** Keeping the old mid "because the facts haven't changed". The facts haven't changed. The question has.

## Resolution and edge cases

Read the rule before you quote. Most expensive world-market mistakes are mistakes about the question, not about the facts.

| Edge case | What to check | Example of the trap |
|---|---|---|
| Ambiguous wording | the rule text, which is authoritative over the short question | "height" of a building: roof, architectural top or antenna tip |
| Boundaries and rounding | "to the nearest …", "to one decimal place", tick | an answer of 12.45 "to one decimal place" may settle at 12.4 or 12.5 depending on the stated rounding |
| Units | the unit field and the rule | feet against metres (× 0.3048); thousands of km/s against km/s; percentage points against per cent |
| Definitions | what is included | land borders only; a city proper against its metropolitan area; members against observers |
| Dates and changes | "on 1 January 2026", "as of" | membership counts, seat counts and borders change; the rule fixes the date |
| Records | "as of" date in the rule | a record broken after the as-of date does not count; one set just before it does |
| Calendars and days | the definition used | a civil day is 86,400 seconds by definition; a *sidereal* day is about 86,164 seconds. Same word, different market |
| Year questions | which event within a process | announced, signed, ratified, in force, completed, opened: often different years |

**Best practice.** When the rule leaves room for two readings, your uncertainty is the *mixture* of both. Quote wider, and smaller, until the resolution text or a shock settles it.

## Worked examples

<details>
<summary>1. A definitional fact: a tight market is defensible, if the definition is the one you think</summary>

*Hypothetical market:* "How many seconds are there in a day?", unit seconds, lot value 50 (so σ₀ ≈ 2 seconds), rule: "a civil day of 24 hours".

- **Information:** the rule fixes the civil day, which is exactly 24 × 60 × 60 = 86,400 seconds.
- **Reasoning:** your σ_you is zero, and the rule removes the definitional risk.
- **Action:** centre on 86,400 with a normal half-spread (0.5σ₀ ≈ 1): **86,399 / 86,401**, normal size. Flow from bots who estimate around a crowd that is slightly off is profit.
- **When it changes:** if the rule said "a sidereal day" or did not define "day", the answer could be about 86,164. That is 118σ₀ away. Without a rule that fixes it, this is not a tight market at all.
- **Mistake to avoid:** quoting from memory before reading the rule.

</details>

<details>
<summary>2. An uncertain statistic: a wider market is sensible</summary>

*Hypothetical market:* the population of a large city you have visited once, in millions, lot value 100 (σ₀ ≈ 1 million).

- **Information:** you remember "somewhere around 3 million", but not whether that was the city or the metropolitan area. The rule says "city proper, latest census".
- **Reasoning:** memory gives ±1 million at best (σ_you ≈ σ₀), and the definition adds risk on the high side (a metropolitan figure would be larger, so your 3 million may already include it).
- **Action:** mid a little below 3 (say 2.8), half-spread about 0.8σ₀ (**2.0 / 3.6**), 1 lot. Watch the flow: two value-fund purchases in a row suggest the crowd is above 3.6.
- **When it changes:** a clue "at least 3.0" removes your lower tail. Reprice to the truncated mean (above 3) and tighten.
- **Mistake to avoid:** a 2.9 / 3.1 market because "3 million" is the number in your head.

</details>

<details>
<summary>3. The answer depends on the definition or the date</summary>

*Hypothetical market:* "In what year did the treaty enter into force?", with your knowledge being the year it was **signed**.

- **Information:** you know the signing year, S. Entry into force is on or after S, commonly one to two years later.
- **Reasoning:** your belief is skewed: nothing below S, most weight on S + 1 and S + 2, a tail beyond.
- **Action:** mid around S + 1.5 and a half-spread of about 1.5 years on a 1-year tick: **S / S + 3**. Never *offer* at or below S − 1: the answer cannot be below S, so selling there is a sure loss.
- **When it changes:** if the market was about the signing year and a RESOLUTION CHANGE redefines it to entry into force, this is exactly the repricing to do, at once.
- **Mistake to avoid:** quoting S because it is the year you remember.

</details>

<details>
<summary>4. A plausible estimate without evidence: keep it wide and small</summary>

*Hypothetical market:* the year of an event you can place only "in the late 19th century", lot value 20 (σ₀ ≈ 5 years).

- **Information:** the bracket is roughly 1870–1900. Your σ_you ≈ 8–9 years, larger than σ₀: the crowd probably knows more than you do.
- **Action:** mid 1885, half-spread about σ_you (**1876 / 1894**), 1 lot. After the round, move your mid part of the way towards one-sided flow, and tighten only as the flow becomes two-sided.
- **When it changes:** if a clue says "at least 1890", your bracket is 1890–1900. Re-centre around 1894–1895 with σ about 3.
- **Mistake to avoid:** a 3-year-wide market on a 30-year bracket because tight markets "look professional". The value fund will trade it every round on the side where you are wrong.

</details>

## Checklist

- [ ] Read the rule: definition, date, rounding, unit
- [ ] Bracket the answer; centre geometrically if it spans factors of ten
- [ ] σ_you against σ₀ ≈ 100 / lot value: do I know more or less than the crowd?
- [ ] Width from my uncertainty; size from my confidence
- [ ] After a round: one-sided flow from careful counterparties, or 3–4 lot trades at level 3? Blend, don't flip
- [ ] After a clue: truncated mean, not the threshold
- [ ] After a redefinition: a new question; old clues gone
- [ ] Debrief: mispricing and settlement luck read together in each world market
