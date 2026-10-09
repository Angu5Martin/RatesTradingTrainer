# Live Desk guide: how to trade the desk

A practical playbook for the Live Desk episodes (levels 1–5): how to price a client, read your risk, decide whether to hedge, and tell a good decision from a lucky one. It is written from the code that runs the desk (`src/rates_trainer/episodes/`, `marketmaking/`). Where it gives a number, that number is either a convention of the desk, a parameter of its training model, or arithmetic you can check. The design and the full model are in [`docs/EPISODES.md`](EPISODES.md); the conventions in [`docs/DESIGN.md`](DESIGN.md).

**Contents:** [Conventions](#conventions-to-make-automatic) · [The decision process](#the-decision-process) · [Quoting and market making](#quoting-and-market-making) · [Rates risk and hedging](#rates-risk-and-hedging) · [Advanced decisions](#advanced-decisions) · [How the desk grades you](#how-the-desk-grades-you) · [Worked examples](#worked-examples) · [Checklists](#checklists)

---

## Conventions to make automatic

Every number on the desk follows these. Get them wrong and every decision after is wrong in sign.

| Term | Definition on this desk |
|---|---|
| **DV01** | the P&L for a **1bp fall** in rates. Receiving fixed (or owning a bond, or buying futures) is **long duration**: DV01 **positive** |
| **P&L for a move** | `P&L ≈ −DV01 × Δr` (Δr in bp). A **1bp fall** in rates makes a position with DV01 = +€100k **gain €100k**; a 1bp rise loses €100k |
| **Bid** | the fixed rate at which **you pay fixed** (the lower rate) |
| **Offer** | the fixed rate at which **you receive fixed** (the higher rate) |
| **Slope exposure** | the P&L for a 1bp **flattening** of a 2s30s twist about the 10Y |
| **Curvature exposure** | the P&L for a 1bp **fall of the 5Y belly** against the wings |
| **Swap-spread exposure** (level 4) | P&L per bp of bond ASW **tightening** |
| **Futures-basis exposure** (level 4) | P&L per tick of futures **richening** |

Which way a client trade leaves you:

| Client… | Trades at your… | You… | Your DV01 | You make money if rates… | You want this flow when… |
|---|---|---|---|---|---|
| **pays** fixed | **offer** (higher rate) | **receive** fixed | **+** (long) | fall | you are short, or bullish on rates (expect a fall) |
| **receives** fixed | **bid** (lower rate) | **pay** fixed | **−** (short) | rise | you are long, or bearish (expect a rise) |

Think of the swap rate as the price of *paying fixed*. You are long duration when you are *short* that price, so a long book wants to **buy it back**: quote **higher** (both bid and offer up) to attract clients who receive.

## The decision process

Run the same seven questions at every screen. The point is not the list. It is noticing when the answers pull in different directions.

| # | Question | Where the desk shows it |
|---|---|---|
| 1 | What is fair value? | the mid on the ladder or focus quote; the street around it |
| 2 | How uncertain is it, and how fast does it move? | conditions: volatility (calm / normal / stressed = ×0.6 / ×1.0 / ×1.8), any release on the calendar |
| 3 | Where should I quote, and how wide? | street width, liquidity, the client's type |
| 4 | What risk do I already have? | DV01 against its limit; at level 3 and above, buckets, slope and curvature |
| 5 | Which side is likely to trade, and what does the flow tell me? | flow text, desk expectation, client type, named-client record (level 5) |
| 6 | Trade, reprice, hedge or wait? | the ticket; hedge menu costs |
| 7 | What could change my view next? | calendar, research view, limit changes, the next client |

**How they interact.** Each question can override the one before it:

- An attractive price (Q3) is a poor trade if it takes a full book over its limit (Q4).
- A trade that adds DV01 (Q4) can *reduce* risk if it offsets curve exposure (level 3).
- A small position (Q4) is cheap to keep in a calm, two-way market (Q2, Q5), and expensive to keep through a release (Q7).
- A client who is probably informed (Q5) changes the price even when your inventory is flat.

```text
Is the trade (or the risk I keep) inside my limits after it happens?
├── no  → pass, or price wide enough that a fill pays for the immediate hedge
└── yes → does it reduce my risk?
          ├── yes (an axe) → price to win it: up to the cost of hedging in the street
          └── no  → charge for: inventory (skew) + information (client type) + conditions (vol, liquidity)
                    then: keep, hedge part, or hedge all? → compare hedge cost with the risk I would keep
```

## Quoting and market making

### Bid, offer and fair value

**Principle.** Your quote is not a statement of fair value. It is a choice about which trades you want, at what margin, given what you hold.

**Reasoning.** The mid on screen is the desk's fair value for the tenor; the **street** is the competitors' market around it. A client deals with whoever shows the best price on its side. Your edge on a fill is the distance from mid in your favour, which the desk calls the **charge**:

```text
client pays (you receive at your offer):     charge = your offer − mid      (bp; positive = you earn)
client receives (you pay at your bid):       charge = mid − your bid
edge at fill (EUR) = charge (bp) × |DV01 of the trade|
```

Marked at mid, a fill shows its edge at once. Example from `docs/DESIGN.md`: 10Y at 2.843 / 2.847, a client pays €300m; you receive at 2.847, DV01 about +€261k, edge 0.2bp × €261k ≈ **€52k**.

### Spread capture is not the whole expected value

**Principle.** Edge at fill is the *first* term. What the trade is worth also depends on who the client is and what you do with the risk.

**Reasoning.** The desk values a fill as:

```text
expected value of a fill ≈ P(fill) × (charge − expected informed drift) × |trade DV01|
expected informed drift  = P(informed | client type) × 1.5bp × volatility multiplier       (training model, flow.py and state.py)
```

then subtracts the hedge cost of anything you lay off, and the exit cost of what you keep. The informed-drift term is large next to typical charges:

| Client type (as shown) | P(informed) | Expected drift against you, normal vol | Fill chance at the street | Price sensitivity |
|---|---|---|---|---|
| Corporate treasurer | 2% | 0.03bp | 35% | 0.15bp |
| Pension fund (LDI) | 5% | 0.075bp | 35% | 0.12bp |
| Bank treasury | 10% | 0.15bp | 35% | 0.10bp |
| Real-money asset manager | 15% | 0.225bp | 35% | 0.10bp |
| Macro hedge fund | 45% | 0.675bp | 45% | 0.30bp |
| Fast money | 60% | 0.9bp | 50% | 0.35bp |

Compare with a 10Y street half-width of about 0.2bp. **A price that matches the street is roughly break-even against an asset manager, and loses on average to a macro fund**, before any inventory consideration. That is the model's version of adverse selection, and it is why the client type is on the ticket.

**Fill probability** (training model): `P(fill) = logistic(logit(p at street) + improvement / sensitivity)`, where improvement is how much better than the street your price is for the client, in bp. For a pension fund: 0.1bp worse than the street → 19% chance; at the street → 35%; 0.1bp better → 55%. Fast money barely cares (43% / 50% / 57%): it needs to trade.

**Best practice.** Charge more to the types more likely to be informed, and know that a wider price loses less flow from them than from price-sensitive real money.

**Common mistake.** Treating every fill as the same edge. The same 0.2bp charge on a €170k-DV01 trade is worth about (0.2 − 0.03) × 170k ≈ +€29k in expectation from a corporate, and about (0.2 − 0.9) × 170k ≈ −€120k from fast money.

### Width and competitiveness

Width protects against volatility, poor liquidity and informed flow; it costs flow on both sides. The desk's reference quote widens with each of them, and the assessment compares your width with the reference: within 0.6–1.8× is sound, 0.35–3× defensible, beyond that poor. **A market that crosses the street** (your bid above the street offer, or your offer below the street bid) is an error: other dealers can lay the risk off against you at a profit at once.

**When it changes.** Uncertainty about fair value itself (a release in the next step, a stressed regime) is a reason to widen. A risk-reducing trade is a reason to tighten the side you want.

### Inventory and skew

**Principle.** Skew moves both sides together to attract the trade that reduces your risk. Width changes how many trades you get; skew changes which ones.

| Book | Want clients to | Skew the market | Side made attractive |
|---|---|---|---|
| long DV01 | receive fixed (you pay) | **higher** in rate | your bid (a higher bid is better for a receiver) |
| short DV01 | pay fixed (you receive) | **lower** | your offer |

The reference skew grows with inventory relative to the limit, with expected client flow and with a stated view. Worked example from `docs/DESIGN.md`: long €300k DV01 with a €500k limit, 2.843 / 2.847 becomes 2.8444 / 2.8484 (+0.14bp). A receiver dealing there brings inventory down and the next skew eases; a payer dealing there pushes inventory up and the next skew grows.

**Common mistake.** Skewing the wrong way: a long book quoting *lower* attracts more payers and more long risk. The assessment rates it poor.

### Information revealed by trading

Flow is evidence. A client that has been *right* on its last trades (level 5: the named-client record shows the side and what rates did next) is more likely to be informed. The desk's own inference is a Bayes update of P(informed) from that evidence; you see the evidence, never the probability, until the debrief. One trade proves nothing; a pattern across a client's requests does.

### Why repeated spread capture is not a strategy

A book that collects 0.2bp on every trade and keeps all the risk is a directional position with a small rebate. Over a session the market move on the inventory dwarfs the edge (a €200k DV01 book over a normal level-2 step has a one-σ move of about €350k, against perhaps €40k of edge). Profit comes from edge **and** keeping risk inside what the edge pays for.

## Rates risk and hedging

### DV01 by product

| Product | DV01 sign | Size it as |
|---|---|---|
| Receiver swap | + | notional (€m) × DV01 per €1m from the ladder |
| Payer swap | − | the same, negative |
| Bond, long | + | face (€m) × DV01 per €1m face from the product line |
| Bund / Bobl future, long | + | contracts × DV01 per contract |
| Short any of the above | the opposite | |

DV01 per €1m on the desk's markets is about **€190 (2Y), €460 (5Y), €830–900 (10Y), €1,800–2,250 (30Y)**. It depends on the rate level, so read it from the ladder. Bund and Bobl futures were about **€88** and **€48** per contract in a typical level 4 market. A bond's DV01 is its price × modified duration × 1bp.

### The arithmetic to make automatic

```text
P&L for a parallel move:           P&L ≈ −DV01 × Δr                        (Δr in bp; first order, ignores convexity)
aggregate risk:                    DV01_book = Σ DV01_i                       (signed: receivers +, payers −)
hedge to neutralise:               notional = −DV01_book / DV01 per €1m      (sign tells you pay or receive)
futures hedge:                     contracts = −DV01_book / DV01 per contract
risk left after hedging fraction f: (1 − f) × DV01_book
one-σ P&L for a step:              |DV01| × σ_move,  σ_move = 5bp × vol multiplier × √(step length in days)
hedge cost:                        cost-to-cross (bp, on the ladder) × |DV01 hedged|
```

The **first-order** P&L (−DV01 × Δr) is what you compute in your head; the desk also shows the **full revaluation**, and the difference is convexity: small for a few bp, positive for a long-duration book.

**Step σ on the desk** (training model; a level move is 5bp a day at normal vol): one step is 0.25 day at level 1, 0.125 day at levels 2, 3 and 5, 0.0625 day intraday at level 4, and an overnight is 0.5 day. So a normal-vol level-2 step has σ ≈ 5 × √0.125 ≈ **1.8bp**, and a €100k DV01 book has a one-σ step P&L of about **€180k**.

### Buckets, slope and curvature (levels 3–5)

Risk is a vector, not one number. The desk shows DV01 by bucket (2Y, 5Y, 10Y, 30Y) and three factor exposures. With KR_t the bucket DV01s, and the factor loadings from the risk card (slope: 2Y −1, 5Y −0.625, 10Y 0, 30Y +1; curvature: 2Y −0.125, 5Y +1, 10Y +0.25, 30Y −0.5):

```text
level  (DV01)      = KR2 + KR5 + KR10 + KR30
slope  exposure    = KR30 − KR2 − 0.625 × KR5               (P&L for a 1bp flattening)
curvature exposure = KR5 + 0.25 × KR10 − 0.125 × KR2 − 0.5 × KR30   (P&L for a 1bp fall of the belly)
```

Normal daily vols in the model: level 5bp, slope 2bp, curvature 1bp. **Neutralising DV01 does not neutralise slope:** a book that is +€89k in 10Y and −€68k in 2Y has a DV01 of +€21k but a slope exposure of +€68k (see [example 3](#worked-examples)).

**Risk-equivalent inventory.** At level 3 the desk prices a request in tenor T by how the trade changes the *whole book's* risk, using the variance-minimising equivalent position in T. So a 2Y request that offsets a 10Y long can deserve an aggressive price even though your 2Y bucket was flat, and a trade that cuts your DV01 can still *add* risk once the curve is counted. The result tells you which.

### Products, carry and basis (level 4)

- **Futures** are the cheapest hedge late in the day (half a tick a contract, about €5) but they hedge *bond* rates, not swap rates. A swap book hedged with futures is left with **swap-spread** risk (bond ASW against swaps) and **futures-basis** risk (the future against its cheapest-to-deliver bond). Size by DV01 per contract, which the desk derives from the CTD (DV01 of the CTD ÷ its conversion factor).
- **The CTD bond** hedges rates too, but it must be financed in repo. When it is **special** (repo below ESTR), it is cheap to own and expensive to be short.
- **Late-session swaps** cost twice their normal spread, plus an impact term that grows with size (`× (1 + hedge DV01 ÷ depth)`); the next morning they are back to normal. That is the case for a temporary futures hedge, switched into swaps later.
- **Overnight**, the desk shows the book's carry, roll-down and funding on an unchanged curve before you decide what to keep, and books them by cause.

### Cross-product hedging and residual risk

A hedge is a trade with its own risks. Choose it by: what it costs now, what risk it leaves (curve, swap spread, basis), what it carries, and how long you will hold it. The assessment names the residual risk a hedge leaves; the debrief prices it ("the futures hedge lost €38k when swap spreads tightened 3bp").

## Advanced decisions

### Several tenors and a curve book

Price each request by its effect on the book, not on its own bucket. Choose hedge tenors deliberately: the cheapest tenor to cross (2Y) is rarely the one that removes your curve risk. A two-leg level-and-slope hedge or *Flatten* removes more risk for more cost. Running a curve position is a legitimate choice if it is small against its limit and you know its size.

### Client information and research views (level 5)

The research view is stated with a reliability: "about 60% of this desk's calls have carried real information". The model is honest about it, so the **expected** move is the view times its reliability, spread over the session's steps (the desk shows what is left and the expected drift per step). A 2bp view at 30% reliability is worth 0.6bp in expectation over the whole session; it justifies a lean, not a bet. Size a view-driven position by its expected drift against the step σ, inside your limits.

### Scheduled releases

A release multiplies the next step's vol (×3 at level 5). One-σ P&L triples and variance rises ninefold. Before it, decide what you keep: hedging costs a fixed amount now; keeping costs variance. **This is not "always flatten into an event".** A small position with offsetting expected flow can be worth keeping; a large one near the limit rarely is. Widening your quote protects against being filled at a price that is stale after the release.

### Changing conditions and limits

Conditions can change mid-session: a stressed regime (vol ×1.8), thin liquidity (hedging costs ×1.5), or a limit cut (to two thirds at level 5). After a change, reassess what was sound a step ago: a position inside the old limit can be over the new one, and ending a decision over a limit is an error.

### Near a limit

A request is a **breach** if it creates or worsens a limit excess; one that shrinks an existing excess is not. So the right price depends on the direction:

- **Risk-adding** request with the book already well into its limit: price wide, or pass. A pass is sound when a fill would breach.
- **Risk-reducing** request (an axe): price to win it. Going *through* mid is defensible only up to about the street cost of hedging (the cost-to-cross); beyond that you are paying more than the street would charge to take the risk off.

### Genuine change or noise?

Fair value is the screen mid. It moves with the market, not with one client's trade. Distinguish:

| Signal | Is it a change in fair value? | What to do |
|---|---|---|
| The screen mid moves (market step, release) | yes | reprice from the new mid at once; mark your book |
| One client trades in one direction | no; possibly information | price the next request from that client with its record in mind |
| A named client keeps trading ahead of moves | evidence of information | widen to that client, not to everyone |
| A research view | partly: its expected drift is view × reliability | lean, size modestly |

**Common mistake.** Reacting to every move by repricing your *view*. Reprice your *quote* (it is relative to mid); change your *position* only for a reason.

## How the desk grades you

Every decision is graded **before** the market moves, on what you could see (commit-before-reveal). The outcome is reported separately. Four separate things, never merged: **decision quality**, **risk taken**, **realised outcome**, **luck**.

| Rating | Meaning |
|---|---|
| **Sound** | efficient for some reasonable risk appetite in the scenario's band |
| **Defensible** | not optimal for any appetite in the band, but close, or a stated, consistent trade-off |
| **Poor** | dominated: another choice has better expected P&L and less risk for every appetite in the band |
| **Error** | wrong-sign hedge, a market that crosses the street, ending over a limit |

Several hedges are usually sound at once (warehouse, 50%, 100%). The assessment shows each alternative's expected P&L and σ *after* you commit, so you see the trade-off you chose. Quotes are graded on **direction and relative size** (skew the right way, width in the right band), never against one magic number. RFQ prices are sound within about half the base half-spread (+0.05bp) of the reference charge.

**Read the debrief like this:** the decision card first, the outcome by factor second, luck (realised minus expected, in σ) third, and the same-path policies last (what "always hedge fully", "never hedge" and the reference would have made on *this* path). A sound decision that lost money is still sound.

## Worked examples

Each example is built on the desk's conventions and model; the round numbers are illustrative.

<details>
<summary>1. A client trade that is attractive on spread but bad for the book</summary>

**Information.** Level 2, 10Y, street 2.843 / 2.847 (mid 2.845), DV01 per €1m €850. Your book is **short €240k DV01** against a €300k limit. A pension fund asks to **receive** fixed on €200m 10Y.

**Calculation.** The client receives, so it hits your bid and you **pay** fixed: trade DV01 = −200 × 850 = **−€170k**. After the fill: −€410k, over the limit. At a street bid of 2.843, your charge is 0.2bp: edge = 0.2 × 170k = **€34k**, less a pension fund's expected informed drift of 0.075bp × 170k ≈ €13k. To get back inside the limit you would have to receive at least €110k DV01 in the street at once: about 0.10bp × 110k ≈ **€11k** at normal vol and liquidity.

**Action.** Price it **wide** (well below the street bid), so that if it fills the extra charge pays for the immediate hedge and the risk while you do it; or **pass**. A pass is graded sound because a fill would breach.

**When it changes.** If the same client wanted to **pay** fixed, the trade would *reduce* your short: an axe. Then price to win it, even slightly through mid.

**Common mistake.** Seeing €34k of edge and taking the trade at the street, then discovering the hedge, the limit and the risk ate it.

</details>

<details>
<summary>2. The market moves: reprice from the new mid, mark the book</summary>

**Information.** Level 2. Last step the 10Y mid was 2.845 and you priced a client at 2.847. The market then sells off **3bp**: mid 2.875. You are long €150k DV01. A new client asks to **pay** fixed.

**Calculation.** Your book lost about −DV01 × Δr = −150k × 3 = **−€450k** on the move (the result panel also shows the full-revaluation figure). For the new request, an offer of 2.847 would be **2.8bp through mid**.

**Action.** Price from the **new** mid: 2.875 plus your charge. You are long, so a payer *adds* to your risk: charge a little more than a flat book would. For a receiver you would charge less.

**When it changes.** If the move came in a release step and vol is stressed, widen as well as reprice.

**Common mistake.** Anchoring on the last level you quoted. The assessment rates a price through mid on a risk-adding trade as poor: you would pay to take risk you do not want.

</details>

<details>
<summary>3. A hedge that neutralises DV01 but leaves curve risk</summary>

**Information.** Level 3. Book: **pay €350m 2Y** (KR2 ≈ −€68k) and **receive €100m 10Y** (KR10 ≈ +€89k). DV01 = **+€21k**; slope exposure = KR30 − KR2 − 0.625 × KR5 = 0 + 68k − 0 ≈ **+€68k** (a 2s10s flattener); curvature ≈ 0.25 × 89k + 0.125 × 68k ≈ +€31k.

**Calculation.** "Hedge" the €21k by paying €25m 10Y (≈ −€21k). DV01 → 0. But KR10 is now +€68k and KR2 is still −€68k: **slope exposure +€68k** and curvature about +€25k. Slope vol is 2bp a day; one level-3 step (0.125 day) has σ ≈ 0.7bp, so the curve position carries about **€48k** of one-σ step risk. A 2bp steepening loses 2 × 68k = **€136k** with a DV01 of zero.

**Action.** Decide deliberately. **Flatten** (receive in 2Y, pay in 10Y against the buckets) costs about 0.05bp × 68k + 0.10bp × 89k ≈ **€12k** at normal liquidity, and removes most of the risk. **Keep the flattener** if it is small against the curve limit (here €68k against a limit of half the DV01 limit) and you are content to run it. Both can be sound; the assessment shows the expected P&L and σ of each after you commit.

**When it changes.** Near the curve limit, or with thin liquidity making the flatten expensive and stressed vol making the curve risky, the balance shifts.

**Common mistake.** Reading "DV01 ~0" as "no risk".

</details>

<details>
<summary>4. A scheduled release increases uncertainty</summary>

**Information.** Level 5. Book **+€150k DV01** in 10Y, limit €300k. The next step contains a release: vol **×3**. The research view says "10Y to RISE about 2bp over the session", reliability 30%.

**Calculation.** Normal step σ ≈ 1.8bp, so one σ on the book is about €265k; through the release it is about **€795k** (variance ×9). The view's expected drift is 2bp × 30% = 0.6bp over the whole session: about **−€90k** expected on a +€150k book if it all came now. Hedging all of it in 10Y costs about 0.10bp × 150k = **€15k**.

**Action.** Cutting the position before the release is efficient here: €15k removes a large variance, and the view points against the position as well.

**When it changes.** With a small book (say €20k DV01) the release adds little absolute risk and the hedge cost is a larger share of it; keeping it can be sound. With a view pointing *with* your position and room in the limit, keeping part is defensible. Widening any quote into the release is a separate decision from hedging.

**Common mistake.** "Always flatten before data", or the reverse, "the view says so, so double up into the release". Size from σ, cost and the view's reliability.

</details>

<details>
<summary>5. Near a limit: the same client, two directions</summary>

**Information.** Level 2. Book **+€270k DV01**, limit €300k. A request for €150m 10Y (≈ €128k DV01).

**If the client pays fixed** (you receive, +€128k → €398k): risk-adding and a breach. Price wide or pass.

**If the client receives fixed** (you pay, −€128k → €142k): it takes risk off you. Price to **win**: at or slightly better than the street bid. Going through mid by up to the cost to cross (about 0.10bp in 10Y at normal conditions) is still cheaper than hedging in the street; beyond that it is not.

**Two-way quote version** (levels 1 and 5): skew the whole market **higher** (better bid for receivers, worse offer for payers), and do not tighten the risk-adding side.

**Common mistake.** Pricing both directions the same because "the client is the same". Your book makes them different trades.

</details>

<details>
<summary>6. When waiting beats both an aggressive quote and an immediate hedge</summary>

**Information.** Level 1. Calm vol (×0.6), deep liquidity, two-way flow. After the fill you are **short €60k DV01** in 10Y, limit €300k. Sales expects a pension fund to **pay** fixed later today (80% likely), which would take your short off.

**Calculation.** Hedging now costs about 0.05bp × 60k ≈ **€3k** (the cost to cross scales with vol and liquidity: 0.5 × 0.20bp × 0.6 × 0.8 ≈ 0.05bp in the 10Y). The step σ is 5 × 0.6 × √0.25 = 1.5bp, so the position's one-σ risk is about €90k, with a meaningful chance that the expected flow offsets it for free.

**Action.** **Warehouse** (no trade). The desk's exit-cost model treats a small position as mostly netted away by the day's two-way flow, so keeping it is nearly free, and the expected payer offsets it. Paying €3k to remove it is defensible; doubling down with an aggressive quote to *add* short risk is not.

**When it changes.** Size near the limit, stressed vol, thin liquidity or a release in the next step all make waiting expensive.

**Common mistake.** Hedging every fill by reflex. The hedge cost is certain; the risk it removes may be small and partly offset by flow you expect.

</details>

## Checklists

**Before pricing a client**

- [ ] Which side does the client trade, and what does that do to my DV01 (and my curve)?
- [ ] Inside my limits after a fill?
- [ ] Risk-reducing (price to win) or risk-adding (charge for it)?
- [ ] Client type: how likely informed? Charge accordingly
- [ ] Conditions: vol, liquidity, a release next step?
- [ ] Price from the **current** mid; not through mid on a risk-adding trade

**Before a hedge decision**

- [ ] DV01, buckets, slope against limits after the trade
- [ ] Cost to cross for each candidate hedge; is the late session making swaps expensive?
- [ ] What risk does each candidate leave (curve, swap spread, basis)?
- [ ] Expected offsetting flow, the view, the next step's vol
- [ ] Keep, part, all: which is efficient here, and why?

**After the result**

- [ ] P&L by factor: did the risk I chose to keep do what I expected?
- [ ] Rating and reasons: which input did I misjudge?
- [ ] Luck, in σ: was the outcome a surprise given my decision?
