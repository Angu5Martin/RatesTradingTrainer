# Market Making Game

A separate, standalone game inside the workstation: you make markets against bots on **several questions at once**, in the spirit of trading-floor "make me a market" games and multi-table poker. It is not part of TRAIN and not one of the Live Desk episodes, and it shares nothing with them but the local server, the left-hand navigation and the design tokens.

Open it from the left rail (**MARKET MAKING GAME**, `#/game`). From a terminal: `./trainer ui` (or the macOS launcher), then pick the area.

## How a game works

Each market asks for **one number**. You post a **bid** and an **offer** and a **size** (lots per side). Bots trade against your *actual* quotes; each market settles on the verified answer. You manage spread, skew and size across the whole table.

The game is **turn-based**; there is no clock. A **round** is one decision cycle, played when you press *Play round*:

1. **Normal flow.** Each bot may look at each open, quoted, unpaused market and trade at your current bid or offer.
2. **Shocks** scheduled for the round land. Affected markets turn **SHOCKED** and their public information, rules or settlement rule change.
3. **Fast reaction.** Fast bots (the sniper, insiders) trade in the shocked markets *in that same round*, against the quote you still have there, which is now stale. You could not have re-quoted yet; what you could do was choose your size, spread and inventory beforehand, or pause the market.
4. **Resolution.** Markets whose round it is settle on the verified outcome.

Then you see a report, may re-quote, pause, resume or acknowledge any market, and play the next round. Markets open and resolve at different times; the game ends with the last one.

| Market status | Meaning |
|---|---|
| ACTIVE | quoted and trading |
| SHOCKED | a shock hit since you last touched the quote (re-quote, or *Acknowledge* to leave it) |
| PAUSED | quote withdrawn (kept); no flow, positions stay. Quoting a paused market puts it back on |
| RESOLVED | settled; shows the answer, your position at settlement and the P&L |
| opening later | listed with its opening round; nothing about it is shown until it opens |

Limits: a **position limit** per market (a side that would breach it is *closed*: nobody can trade it) and, at level 3, a **firm-wide risk budget** (trades that would add risk beyond it do not happen; trades that reduce risk always do).

## Levels

| | 1 Beginner | 2 Intermediate | 3 Advanced |
|---|---|---|---|
| Markets (min / default / max) | 2 / 3 / 4 | 3 / 5 / 6 | 4 / 7 / 8 |
| Rounds | 8 | 12 | 14 |
| Markets that open late | 0 | 2 | 3 |
| Shocks in a game | 0–1, information or simple rule changes | 2–4, all kinds | 5–8, larger |
| Bots | 2 retail, value fund, slow money | + fast money (sniper) | + 2 informed |
| Counterparty labels | full ("Value fund") | coarse ("Fund", "Prop") | none |
| Linked markets (same dice) | no | no | yes |
| Position limit / max size | ±6 / 3 | ±5 / 4 | ±4 / 4 |
| Risk budget | none | none | 1,100 credits (1σ) |
| Coach (edge of each trade shown live) | on by default | off | off |
| World questions drawn from difficulty | 1 | 1–2 | 1–3 |

Difficulty comes from complexity and decisions, never speed. At the start you can customise the number of markets, the mix (mixed / probability only / world only), an optional seed and the coach.

## Market types

**Probability and mental maths** (generated from rules; exact distributions, no sampling):

- sum of 1–6 dice (d6, d8, d10, d12 and "random integers 1..N"), highest or lowest of several dice, sum of the highest two (level 3);
- number of results meeting a condition: odd, even, ≥ t, ≤ t, prime, multiple of 3; heads in n coin flips (biased coins at level 3);
- cards: number of hearts, a colour, face cards, aces, … among k drawn without replacement (exact hypergeometric);
- **events**: any of the above turned into "will it be at least t?", paying 100 if true, 0 if not; the price is a probability in percentage points;
- **linked markets** (level 3): two different readings of the same dice (for example their sum and their highest), resolving together.

**World knowledge and events**: a curated local bank of 497 numeric facts (history 83, geography 75, science 72, economics and rates-market conventions 71, culture 64, sport 63, politics 41, plus measurement, technology and games), 84 of them easy enough for level 1 and 18 with an alternative resolution for the resolution shock. It includes market-relevant items, such as the tick values, notionals, notional coupons and deliverable maturities of the Euro-Bund, Bobl, Schatz and Buxl futures, central-bank and benchmark-rate history, and Basel III minima. Each has the exact question, unit, an explicit resolution rule, a public settlement range, a tick, a difficulty, a source and an as-of date. No live data and no network during play. The answer and the source are shown only when the market resolves.

Adding a type later means adding a template in `generator.py` (and, for a new kind of experiment, a class beside `DiceExperiment` / `DeckExperiment` with `pmf`, `realise`, `apply`, `describe`); the game loop, bots, ledger and debrief only use that interface.

## Shocks

Shocks have precise semantics. Every shock has a **category**, shown to the player as a heading, and the text says what did *not* change:

| Category | What it does | Examples (all implemented) |
|---|---|---|
| **RULE CHANGE** (experiment) | changes the experiment for the trials **not yet rolled** | "No odd numbers"; "No numbers below 4"; faces 1–6 become 1–10; a face becomes 2–3× as likely; more or fewer dice; all clubs / red cards / face cards taken out of the deck; jokers added; more or fewer cards drawn |
| **NEW INFORMATION** (information) | reveals something *true* about trials that have **already been rolled**; the experiment and the settlement rule are unchanged | "Die 1 shows 5"; "Die 2 is odd" (the value stays hidden); the first cards drawn are shown; "it is confirmed the answer is at least 1800" |
| **RESOLUTION CHANGE** (resolution) | changes **how the answer is read**; the dice are unchanged | the event threshold moves; a different condition is counted (odd results → results of 5 or more); the sum now counts only the highest two dice; the deck count switches from hearts to red cards; a fact is redefined to a nearby version (signed → entered into force; with or without Pluto) |

Rules that matter:

- **Dice are rolled at resolution**, from the rules in force then, using a hidden per-trial tape value fixed by the seed. A rule change therefore re-rolls the unrolled trials under the new rule; a trial that has been rolled or revealed is never affected by later rule changes.
- Information is generated from the hidden value, always *true*, and its statement type is chosen independently of the value (parity, high/low half), so the update is exactly a conditioning. Clue thresholds for world questions come from the public guess, never from the answer.
- A shock hits one market, or every market that shares the experiment (linked markets); resolution changes hit one market. A shock is planned only for a round in which the market is open and has at least one more round before it resolves, so there is always a round in which to react.
- Every planned shock is validated on a working copy in time order: it must apply, change the distribution, and not leave the answer certain. Its size (how far it moves fair value, in standard deviations) is recorded for the debrief. At levels 2 and 3 non-information shocks are chosen to be consequential.
- The shock plan is hidden until each shock lands. The text of a shock never reveals unrolled outcomes.

## Bots

Deterministic; each looks at the market's *public* state, your quote and (informed kinds only) the hidden truth, and decides whether to trade, which side and how much. They trade only at your bid or offer, only up to your size, your limits and the risk budget. Their arrivals and noise are fixed by `(seed, round, market, bot)`; only their decisions depend on your quotes.

| Bot | Behaviour | Punishes |
|---|---|---|
| Retail flow | trades often and small around fair value with a noisy view; cares about the spread; dries up as you widen | pays you the spread |
| Value fund | good estimate of fair value; trades a quote that is clearly off it | mispriced quotes |
| Slow money | prices off the fair value of two rounds ago | trades stale prices after a shock; mostly harmless |
| Fast money (sniper, levels 2–3) | sharp estimate; reacts within the shock round, with size | stale quotes |
| Informed (level 3) | knows (nearly) the answer under the rules of the moment; trades only when the edge is large, bigger when it is larger, rationed to 5 lots a round across all markets | tight spreads and big size; its absence is information |

Measured over whole games (see `tests/mmgame/test_bots.py`): quoting at fair with a sensible spread beats a mispriced market at every level; never re-quoting after shocks costs money at level 2; informed counterparties cost money at level 3 and exactly nothing at level 1.

## Accounting and P&L

- A lot is a fixed quantity. Each market has a **lot value** (credits per lot per 1.0 of price), chosen so one standard deviation of the question's initial uncertainty is worth about 100 credits per lot, which makes risk comparable across a dice sum and a year.
- A bot *buying* from you lifts your offer: you **sell**, position −q, cash `+= q·p·lot value`. A bot *selling* to you hits your bid: you **buy**, position +q, cash `−= q·p·lot value`.
- At resolution: `cash += position × settlement × lot value`; the position goes to zero. **P&L = cash.**
- Before settlement, *open P&L* marks the position at **your own mid**; the game never marks you to a hidden fair value.
- Prices are integer multiples of the tick; quotes with floating-point noise are refused.

### Debrief attribution (after the last market resolves)

For a trade of q lots at price p, when the public fair value was F (the exact expectation of the answer given everything announced so far; the crowd's belief for world questions), with settlement S and F_end the fair value just before settlement:

- **Edge** = q·(F − p) if you bought, q·(p − F) if you sold. A *decision* result. It splits into **spread capture** (half your quoted spread) and **mispricing** (how far your mid was from fair on the traded side).
- **News drift** = signed q·(F_end − F) and **settlement luck** = signed q·(S − F_end). Against uninformed counterparties these are **luck** (zero on average).
- Against **informed** counterparties the same two terms are reported as **adverse selection**: the cost of trading with someone who knew more, which the spread is there to pay for.

`P&L = edge + adverse selection + news drift + settlement luck`, exactly (fractions), in every market and in total. **Decision result = edge + adverse selection**; **luck = news drift + settlement luck**. The debrief also shows, per trade, whether a loss was a stale quote, a mispriced quote, an informed counterparty, or just bad luck at a fair price; per quote, whether it was centred, skewed to reduce inventory (sensible), skewed with inventory (adds risk) or off fair value; per shock, how far fair value moved, how far your quote was off, and whether you re-quoted at once; the revealed counterparties; and the shock plan.

For world questions the fair value is the crowd's belief, which is deliberately off the truth by about one "spread" (a typical error of an informed guess). If you know the answer you can beat it; that gain shows up as luck in the attribution, and the debrief says so.

## Question verification

- **Probability**: every distribution is exact (fractions) and tested against brute-force enumeration (dice, coins, weighted faces, the top-two sum, hypergeometric card counts). Resolution is tested against the distribution over thousands of tapes; each effect is tested for what it changes and what it must not.
- **World bank**: each item is tested for completeness, unique questions, answer inside the public range, no answer stated in the question or rule, no invented links in sources, redefinitions inside the range; a sample of answers is asserted by hand. The facts were chosen as stable, public, objectively checkable ones and each carries a named reference and an as-of date. **The references are named, not fetched.** The bank was written from stable, widely documented facts and every new item was read through once for correctness and wording, but only a handful were checked against the web (the DAX has 40 constituents, the European Parliament has 720 seats in 2024–29 and had 705 before, the 100 m record is still 9.58 s as of September 2026, the Channel Tunnel is 50.45 km). The other ~480 items were **not** individually re-verified online. Facts that can change are phrased 'as of 1 January 2026' in their rule (records, memberships, seat counts), and some of those, such as athletics records, club or seat counts and tournament tallies, can drift after that date. Treat a source as a pointer to where the fact is documented, and re-check any item before relying on it outside the game.

## Determinism, replay and storage

- A game is `(level, seed, markets, mix, coach, bank version)` plus your actions; `Game.replay(record)` reaches the identical state. The question bank is **versioned**: items carry the version that added them (`added` in the TOML, absent = 1), a game is dealt from one version and records it, and a record without one replays from version 1. So the bank can grow without changing any saved game; to extend it, append items with the next version and never reorder or edit old ones. Two snapshot tests pin the generator, one per bank version, so saved games cannot silently become different games.
- One file per game under `<home>/mmgame/<id>.json` (`$RATES_TRAINER_HOME` or `~/.rates_trainer`), rewritten atomically after every action. A finished game is kept; an unfinished one can be resumed (the server replays it after a restart) or abandoned. TRAIN practice files and Live Desk episodes are never read, written or listed by the game, and the game's files never appear in them.
- The API never sends the seed, the tape, the shock plan, a fair value before the market resolves, an unrolled result, or which counterparty was informed.

## Where it lives

| | |
|---|---|
| `src/rates_trainer/mmgame/` | `rng`, `probability`, `world` (+ `data/world_questions.toml`), `levels`, `markets`, `bots`, `generator`, `game`, `debrief`, `store`. Imports nothing from the rates engine, the question bank or the episodes (a test checks it) |
| `src/rates_trainer/web/mmgame_routes.py` | the HTTP API (`/api/mmgame`), mounted by one line in `web/app.py` |
| `frontend/src/game/` | lobby, table, market cards, detail, portfolio, report, debrief |
| `tests/mmgame/`, `tests/web/test_mmgame_api.py` | engine, shocks, bots, hidden information, replay, debrief, HTTP |
| `frontend/src/__tests__/game*.ts(x)`, `frontend/e2e/game.spec.ts` | unit, component (real recorded payloads, `scripts/dump_game_fixtures.py`) and end-to-end against the real server |

## Not in scope

Review analytics for games, live data, speed or adaptive features, and any change to TRAIN or the Live Desk.
