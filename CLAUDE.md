
# Linear Rates Trading Trainer

## Project objective

Build a high-quality interactive training system in Python that prepares me to think and operate like a junior EUR linear rates trader.

The purpose is not to create a generic finance quiz.

The system should develop:

- Product knowledge
- Rates mathematics
- DV01 intuition
- Curve intuition
- Spread and basis intuition
- Convexity intuition
- Hedging ability
- P&L intuition
- Market-making judgement
- Bid/ask intuition
- Quoting intuition
- Inventory management
- Ability to connect trades, positions, risks, hedges, quotes and P&L

The ultimate objective is to make the following mental processes increasingly automatic:

**Trade → Position → Risk → Hedge → Market Move → P&L**

and, for market making:

**Fair Value → Quote → Client Trade → Position → Risk → Skew/Hedge → Market Move → P&L → Re-quote**

The system should progressively move from understanding individual concepts toward applying them in realistic trading situations.

---

## Target user and role

I am preparing for a junior role on a EUR rates swap trading desk.

Prioritise practical linear-rates trading knowledge and intuition over academic material that has little relevance to a rates desk.

Use realistic EUR rates terminology, products, conventions and market scenarios.

The finished system should feel like serious preparation for working on a rates trading desk rather than an educational quiz.

---

# Scope

Cover the major linear rates products and concepts, including but not limited to:

## Fixed income and money markets

- Government bonds
- Money-market instruments
- Treasury bills
- Zero-coupon instruments
- FRAs
- Repo
- Financing relationships

## Interest-rate derivatives

- Interest-rate futures
- OIS
- Interest-rate swaps
- Forward-starting swaps
- Basis swaps

## Relative value and packages

- Asset swaps
- Swap spreads
- Basis
- Cash versus futures
- Cash versus swaps
- Bond versus swap packages
- Futures basis
- Implied repo
- Cheapest-to-deliver
- Repo specialness

## Curves and rates

- Discount factors
- Zero rates
- Spot rates
- Forward rates
- Par rates
- Swap rates
- Yield curves
- Swap curves
- Curve construction
- Bootstrapping
- Interpolation where relevant

## Risk

- DV01
- PV01
- Key-rate DV01
- Duration
- Modified duration
- Convexity
- Hedge ratios
- Futures DV01
- Curve risk
- Spread risk
- Basis risk

## Curve and relative-value trades

- Steepeners
- Flatteners
- Curve spreads
- Butterflies
- Carry
- Roll-down
- Relative-value trades

## P&L

- Rate-move P&L
- Curve P&L
- Spread P&L
- Basis P&L
- Carry
- Roll-down
- Convexity
- P&L attribution

## Market making and quoting

Market making should be treated as a core part of the curriculum rather than a peripheral feature.

Cover:

- Bid and ask mechanics
- Fair value
- Bid/offer around fair value
- Quote skew
- Inventory skew
- Inventory management
- Adverse selection
- Liquidity
- Volatility
- Spread width
- Client flow
- Expected client flow
- Risk limits
- Market-making around fair value
- Dynamic re-quoting
- Hedging versus inventory management
- Relationship between quoting and hedging
- Balancing flow capture against inventory risk

Exclude swaptions and volatility products.

Use judgement to identify other important linear-rates concepts that should be included.

The list above is a scope baseline, not an exhaustive specification.

---

# Core learning philosophy

The system should teach understanding and application rather than memorisation.

Avoid relying primarily on questions such as:

> What is DV01?

Instead, favour questions such as:

> You receive €250m 10Y EUR IRS. The 10Y swap rate rises 4bp. What is your approximate P&L?

Then progressively move toward:

> You receive €250m 10Y, pay €X 2Y and are running a 10s30s position. The curve moves differently across maturities. Estimate the portfolio P&L.

The user should increasingly have to reason through the implications of a trade.

The system should deliberately connect:

**Product knowledge → calculation → risk → decision → P&L**

rather than teaching these as isolated topics.

---

# Question architecture

Do not build the system around a giant static bank of manually written questions.

Use an appropriate combination of:

- Carefully designed conceptual questions
- Parameterised calculation questions
- Dynamically generated numerical instances
- Structured trading scenarios
- Multi-step market-making scenarios

The same underlying skill should be capable of being tested through many different numerical instances and market situations.

Numerical questions must be generated from validated financial logic.

Do not rely on an LLM to perform financial calculations at runtime where deterministic Python calculations can be used instead.

The architecture should make it possible to expand the curriculum substantially without manually creating every individual question.

Use judgement about which questions should be:

- permanently curated
- template-based
- dynamically generated
- scenario-based

The goal is high-quality variety, not randomness for its own sake.

---

# What I want to be tested on

Test both knowledge and application.

## Calculation

Test the ability to calculate or estimate:

- DV01
- PV01
- Duration
- Modified duration
- Convexity
- Hedge ratios
- Swap DV01
- Bond DV01
- Futures DV01
- Curve-trade sizing
- P&L
- Carry
- Roll-down
- Spread P&L
- Basis P&L

Questions should progress from straightforward calculations toward situations where calculations must be embedded within a trading decision.

---

## Rates intuition

Test whether I understand:

- What happens when rates move
- What happens when the curve steepens or flattens
- What happens when swap spreads widen or tighten
- What happens when basis widens or tightens
- How convexity affects P&L
- How different instruments hedge one another
- How changes in one part of the curve affect relative-value positions
- How a position's risk changes after a market move

---

## Relative value

Test:

- Swap spreads
- Asset swaps
- Basis
- Curve trades
- Butterflies
- Futures versus cash
- Cash versus swaps
- Bond/swap packages
- Relative-value hedging
- Relative-value P&L

The user should understand both the mechanics and the directional intuition of each trade.

---

# Market-making and quoting intuition

A major objective of the system is to develop intuition for **making markets**, not merely understanding trades after they have occurred.

The system should teach:

- Bid versus ask
- Which side of the market I want to trade on
- How inventory affects quoting
- How to skew a bid/ask based on inventory
- How to skew based on my market view
- How to balance inventory reduction against attracting flow
- How spread width should change with risk
- How volatility affects quoting
- How liquidity affects quoting
- How client flow affects inventory
- How expected future flow affects quoting
- How risk limits affect quoting
- How urgency affects quoting
- How to distinguish a price that is attractive for taking risk from a price that is attractive for providing liquidity
- How hedging costs affect quoting decisions
- How adverse selection affects quoting decisions

The system should develop the intuition that a market maker's quote is not necessarily symmetric around theoretical fair value.

For example, if I am excessively long a rates risk:

- I should generally become more willing to sell
- My offer may become more aggressive
- My bid may become less attractive
- My quoted market may become skewed to encourage inventory-reducing trades

Similarly, if I have a strong market belief, the system should test how that belief interacts with inventory and quoting decisions.

The objective is not to teach one rigid quoting formula.

It is to develop the ability to reason about:

**Fair value → Inventory → Risk → Market view → Expected flow → Quote → Resulting inventory**

The system should distinguish between:

1. Quoting to manage inventory
2. Quoting based on market information
3. Quoting based on conviction
4. Quoting based on liquidity
5. Quoting based on risk limits
6. Quoting based on expected client behaviour

---

# Quoting scenarios

The system should eventually include realistic quoting exercises.

For example:

> EUR 10Y IRS fair value: 2.845%
>
> Current market: 2.843 / 2.847
>
> Your inventory: significantly long 10Y duration
>
> Market volatility: moderate
>
> Client flow: historically two-way
>
> Your market view: mildly bearish rates
>
> Risk limit: approaching maximum

Ask questions such as:

- Where should you quote?
- Should your market be symmetric?
- Which side should be more attractive?
- How should you skew the market?
- How wide should the market be?
- What inventory are you trying to encourage?
- What happens if the client trades on your bid?
- What happens if the client trades on your offer?
- How does your quote change after the trade?
- Would you hedge immediately or manage the inventory through subsequent flow?

Do not reduce these questions to a single predetermined formula unless there is a genuine mathematical model behind it.

The purpose is to develop market-making judgement.

---

# Inventory and skew

Create scenarios where the same theoretical fair value produces different optimal quotes depending on:

- Current inventory
- DV01
- Key-rate exposure
- Convexity
- Market volatility
- Liquidity
- Recent client flow
- Expected client flow
- Market direction
- Trader conviction
- Risk limits
- Hedging costs

The user should learn that the correct quote is conditional on the trader's current state.

For example, test situations where:

- Long inventory → skew toward selling
- Short inventory → skew toward buying
- Strong bullish view → alter quoting accordingly
- Strong bearish view → alter quoting accordingly
- High volatility → widen or otherwise adjust the market
- Poor liquidity → protect against adverse selection
- High inventory risk → prioritise inventory reduction

Where appropriate, introduce the tension between:

**getting flow vs protecting against adverse selection**

The system should not present these decisions as universally correct. It should teach the reasoning behind them and acknowledge where there are genuine trade-offs.

---

# Bid/ask intuition

Build exercises that force the user to identify:

- Which side is bid
- Which side is offer
- What happens when a client pays
- What happens when a client receives
- Which trade increases or decreases inventory
- Whether the trader wants to encourage or discourage a particular side
- How the quote should be skewed
- How the resulting inventory changes the next quote

The system should progressively move from simple bid/offer questions to multi-factor quoting decisions.

---

# Market-making decision loop

The system should eventually train the following mental process:

**Fair Value → Current Market → Inventory → Risk → Market View → Expected Flow → Quote Skew → Client Trade → New Inventory → Re-quote**

This should become a core component of the trading simulations.

---

# Market-making scenarios

This should be one of the most important parts of the system.

Eventually I want scenarios resembling:

> EUR 10Y IRS 2.843 / 2.847
>
> Client pays €300m.

I need to determine:

- What position do I now have?
- What is my directional rates exposure?
- What is my approximate DV01?
- How might I hedge it?
- What hedge size should I use?
- What residual risk remains?
- What happens if the market moves?
- What happens if the swap spread moves?
- What is my approximate P&L?

Scenarios should eventually combine:

- Multiple maturities
- Multiple instruments
- Existing inventory
- Client flow
- Curve movements
- Swap-spread movements
- Basis movements
- Hedging decisions
- Subsequent market movements
- Changing quotes
- Inventory constraints
- Market views

The objective is to develop the ability to translate a trading situation into risk, quoting decisions and P&L.

---

# Portfolio risk

Give me multiple positions and ask me to understand:

- Aggregate DV01
- Key-rate exposure
- Curve exposure
- Spread exposure
- Basis exposure
- Convexity
- Hedge requirements
- P&L under different market scenarios

Portfolio questions should eventually combine several products.

For example, a portfolio could contain:

- EUR swaps
- Government bonds
- Futures
- ASW
- Curve positions
- Basis positions

The system should test whether I can understand the portfolio as a collection of risk factors rather than as isolated trades.

---

# Financial correctness

Financial correctness is more important than superficial complexity.

For numerical calculations:

- Use explicit formulas
- Validate generated inputs
- Independently calculate expected answers
- Check units
- Check signs
- Allow sensible rounding
- Test edge cases

Be explicit about financial conventions.

Where multiple legitimate conventions exist, select a sensible convention, document it and use it consistently.

Do not invent conventions simply to make a question easier.

The financial calculation engine should be deterministic and independently testable.

---

# Architecture and technology

Python is the assumed implementation language.

Beyond that, use your judgement.

You have substantial flexibility over:

- Application framework
- Frontend
- Backend structure
- File structure
- Data model
- Question representation
- Financial calculation architecture
- Scenario architecture
- Persistence
- Testing strategy
- Supporting libraries

Choose the architecture that produces the best training system rather than following a predetermined structure.

Do not create files or abstractions merely because they sound architecturally sophisticated.

Prioritise:

1. Correctness
2. Training quality
3. Maintainability
4. Simplicity
5. Extensibility

## UI-agnostic core

The core training system (financial engine, curriculum, question and scenario generation, grading) must remain UI-agnostic during development. The current terminal interface is a thin presentation layer over it and should stay that way.

The design of the final user interface is deliberately deferred until the core curriculum, the financial engine and, especially, the stateful market-making episodes are sufficiently developed. The UI will then be designed around the actual training workflows rather than committing early to a framework or interaction model.

---

# Development philosophy

Do not attempt to build the entire system in one step.

First understand the requirements and explore the design space.

Then determine the appropriate architecture.

Then implement the foundational components.

Test them thoroughly.

Then progressively build the training experience.

At important stages, briefly explain major architectural decisions and assumptions.

If something is ambiguous but does not materially affect the outcome, use sensible judgement rather than repeatedly asking for clarification.

Do not prematurely optimise for features that are explicitly outside the current scope.

---

# Current scope exclusions

Do not implement the following yet:

- Speed-based training
- Adaptive learning
- Personalised difficulty based on historical performance
- Complex gamification
- Live market-data integration

These may be added in future iterations.

The current priority is building a strong foundation for:

**financial knowledge → calculation → intuition → trading decisions → risk → P&L**

and:

**fair value → quoting → inventory → skew → client flow → re-quoting**

---

# Quality bar

The finished system should be something I can use regularly over several months to prepare for my rates trading career.

It should eventually make concepts such as:

- DV01
- Hedge ratios
- Curve direction
- Swap-spread direction
- Basis direction
- Basic P&L
- Bid/ask direction
- Inventory skew
- Quote skew

increasingly intuitive.

The goal is not to make me good at answering the system's questions.

The goal is to make me better at **thinking about rates markets and making markets in them**.