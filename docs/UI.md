# UI architecture and interaction design

Status: **design only, nothing built.** Grounded in the code as it stands: the question system (`questions/`, `curriculum/`, `session.py`), the episode system
and its frozen frontend contract (`episodes/api.py`, `views.py`, `serial.py`, `docs/EPISODES.md` section 19). The backend is treated as frozen except for the
small, additive gaps listed in section 16, each justified by a screen that cannot be built without it.

Contents: 1 Product · 2 Train and Live Desk together · 3 Live Desk hierarchy · 4 Question experience · 5 Review · 6 Screens · 7 L1-L5 in the UI · 8 Components ·
9 Charts · 10 Interaction · 11 Information rules · 12 Visual system · 13 Architecture · 14 State · 15 Contract mapping · 16 API gaps · 17 Build order · 18 Stack ·
19 Decisions for you.

---

## 1. Overall product

One application, three areas, one shared vocabulary (skills, DV01 sign convention, bid = you pay fixed) and one shared record of what you have done.

| Area | Purpose | Built on | Visual mode |
|---|---|---|---|
| **TRAIN** | Build a skill: focused or mixed question practice | `questions/` (167 sources: 105 curated, 62 parameterised templates; 41 skills in 10 tracks, none planned: see `docs/CURRICULUM.md`) | Focused: one problem, one answer workspace |
| **LIVE DESK** | Apply the skills together under desk conditions, levels 1-5 | `episodes/api.py` (`Session`) | Dense, terminal-like workstation |
| **REVIEW** | Answer "was that a good decision or did I get lucky?", find weak areas | stored question attempts and stored episode transcripts | Analytical, spacious |

The existing grain of the system is kept: a question is `(template id, seed)` and an episode is `(episode id, seed, market seed, decisions)`. Both are
exactly replayable, so the Review area can re-open anything that was ever played.

Navigation is a slim left rail (icons plus labels) with three sections. Inside TRAIN, the rail lists the ten real tracks from `curriculum/skills.py`, grouped for
the eye rather than renamed:

| Group in the UI | Tracks (sources today) |
|---|---|
| Foundations | math (12), swaps (23), bonds (15) |
| Risk and hedging | risk (14), portfolio (5) |
| Futures and relative value | futures (14), rv (12), curve (18) |
| P&L and carry | pnl (9) |
| Quoting and market making | mm (45) |
| Mixed | any combination, or everything |

When this section was written the thin tracks (math, risk, portfolio) showed as thin, with seven skills planned and four practised only in the Live Desk; the question bank has since been expanded so that every
skill has standalone questions (`docs/CURRICULUM.md`). The two chips remain in the interface for any future skill that is planned (no questions of any kind) or practised only in the Live Desk
("no standalone questions"): the catalogue shows a content gap instead of hiding it, and a test keeps the flag honest.

The illustrative names in the brief (Concepts, Calculations, ...) map onto a real axis the data already has: **difficulty** (1 = single concept, 2 = concept plus
calculation, 3 = multi-step trading situation) and **kind** (curated conceptual vs parameterised numerical). They become filters, not separate areas.

## 2. Standalone training and the Live Desk

They are two ends of one loop, joined by **static, non-adaptive links** drawn from structure that already exists:

1. **Each Live Desk level lists its skills** (every `EpisodeSpec` already carries a `skill`; levels also exercise `risk.key_rate`, `mm.cross_product_hedging`,
   `mm.views_and_events`). The level card shows them with a "Drill" link into TRAIN pre-filtered to that skill and its prerequisites.
2. **A debrief links back**: "your hedges added swap-spread risk" -> Drill: futures DV01 hedge / ASW package. The link target is chosen by a fixed table
   (assessment area -> skill), not by performance history. No adaptivity.
3. **A TRAIN session summary** may say "these skills feed Live Desk level N" using the prerequisite graph.
4. **Same language everywhere**: DV01 sign, bid/offer meaning, EUR formatting and number input rules (`225k`, `1.2m`, `3bp`) are one implementation used by both areas.
5. **One shell, one top bar, one design system, one record.** Switching area never loses state: a Live Desk session in progress stays resumable.

A question never goes through the episode machinery and an episode never uses a question as a checkpoint beyond the one numeric checkpoint the episode already owns.

## 3. Live Desk information hierarchy

The screen is organised around the decision loop **Read the market -> Read my risk -> Decide -> Commit -> See what happened**, not around the fields the backend
returns. Priority, from always-visible to on-demand:

1. **Always visible (top bar):** episode and level, round n/N and phase, session clock label (`header.round_title`), conditions (volatility, liquidity), headline
   P&L, book DV01 against its limit, curve-limit use where it exists, any announcement (limit cut, release).
2. **The decision in front of me:** the ticket in the centre; it changes with `observation.kind` (quote, rfq, checkpoint, hedge, position, overnight, rehedge).
3. **What I need to take it:** the market (curve plus swap ladder, products at L4) on the left and my risk on the right, each as compact tables with small graphics.
4. **Context on demand:** conditions detail, desk expectation, research view, named-client evidence, risk card (training assumptions), event tape.
5. **After the commit only:** the result panel (fill, trades, market move, P&L by factor, rating, reasons, benchmark table).

Question the layout must answer without paragraphs: *What risk do I have? What is being asked? What does it cost to change? What changed?*

## 4. Standalone question experience

The data the UI receives today is `Question(stem, parts, solution)` where a part is numeric (prompt, unit, tolerance, note, hint) or a choice (prompt, options). Stems
are pre-formatted text blocks that include small market screens (for example `EUR IRS curve: 2Y 2.690% | 5Y ...`). The UI renders the stem in a monospace
"market screen" block and does not try to parse it.

**Layout.** Two columns: *Problem* (left, about 60%) and *Workspace* (right).

* Problem: skill and difficulty tags, the stem as a market screen, the current prompt. Multi-part questions (for example `mm.client_trade_risk`, 6 parts) show a
  stepper; earlier parts stay visible with their results, because later parts build on them. This is what makes a multi-step scenario feel different from a
  one-line concept check.
* Workspace: for a numeric part, an input with the unit suffix, the accepted forms (`225k`, `-1.2m`, `3bp`) and a small scratch calculator (client-side arithmetic
  only, no financial functions). For a choice part, large keyboard-addressable options (A-D) and no calculator. Skip and Quit are always available; unreadable input is
  re-prompted and **not** penalised (the CLI already behaves this way).
* After answering: a result strip (correct / incorrect / skipped), the expected answer, the first-order vs precise detail where the question has one ("-DV01 x
  move = X, precise = Y"), sign and unit-slip feedback ("right size, wrong sign", "1000x too large"), the choice rationale, and after the last part the worked
  solution. Then Next.

**Kinds look different**, driven by data, not by new types: a choice-only difficulty-1 question is a clean card with options; a difficulty-2 numeric is the
problem-plus-workspace; a difficulty-3 multi-part question gets the stepper and a persistent "givens" strip pinned to the top so the numbers stay in view.

**Session modes** (all existing selection logic: tracks, skills, difficulty, max difficulty, count, seed, replay ids):
focused skill practice; track practice; mixed (all or chosen tracks); "replay what I missed" (the CLI's `--replay` ids); "by difficulty". A session is 5-20 questions. The
end screen shows parts correct by skill and the missed ids with a one-click replay. No adaptive difficulty, no streaks, no badges.

**Not invented:** there is no concept-reference content in the repo beyond question solutions and skill titles. The "relevant concept" panel in the brief is
therefore the worked solution plus the skill's title and prerequisites. Reference cards (short static notes per skill) are a content task for later; the layout
reserves a collapsed "Reference" slot.

## 5. Review and debrief experience

Two parts.

**Debrief** (end of every Live Desk episode, opened automatically; also re-openable). Built on `DebriefView`. Its organising idea is to keep four things apart and
visible at once, exactly as the engine does:

```
 DECISION QUALITY      REALISED OUTCOME       LUCK                   CONDITIONAL EXPECTATION
 8 decisions           P&L  +€20.1k           realised − expected    (L5) market-path distribution
 sound 7 · def 1       by factor + costs      +€48.4k  (+0.5 σ)      mean +€72.6k, 5–95% −€7.9k…+€159k
```

Below the strip, a round-by-round timeline. Each round is a row that expands to **Decision -> Risk -> Assessment -> Outcome -> Luck**:

* *Decision*: what was committed (the quote, the price, the legs).
* *Risk*: exposures after the decision (level, slope, curvature, spreads) against limits (`assessment.metrics`).
* *Assessment*: rating chip, reasons, and the benchmark alternatives table (revealed only now), each alternative with its own E, sigma and rating.
* *Outcome*: fill and edge, hedge cost, the market move, P&L by factor (level, slope, curvature, swap spread, futures basis, convexity), carry/roll/funding on overnight rounds.
* *Luck*: this round's realised minus expected.

Then: **same-path counterfactuals** (a table of policies with P&L and per-decision rating strips, "you" highlighted) and, at Level 5, **the distribution** (histogram of the
200 paths with markers for your realised P&L, your mean and the reference mean) with the two expectations labelled as different questions, as the backend now
does. A single quiet line states the conclusion pattern ("sound decisions, unlucky result" / "poor decision, lucky result") in words, not as a badge.

**Review area** (across sessions):

* *Questions*: accuracy by skill, track and difficulty; recent sessions; the missed queue; replay.
* *Live Desk*: list of sessions (level, date, P&L, decision-quality counts, luck); open any to re-render its debrief from the stored transcript.
* *Weak areas*: at first, counts of poor/error decisions by decision kind and level, and missed question skills. Richer weak-area tagging needs machine-readable reason
  codes the assessment does not emit yet (section 16, item 6).
* *Risk / P&L analysis*: cumulative P&L by factor and by cause across sessions, limit-use history.

## 6. Proposed screens

### 6.1 App shell

```
┌──────┬──────────────────────────────────────────────────────────────────────────────┐
│ TRAIN│  top bar (area-specific; Live Desk's is the dense one, section 6.2)           │
│  ·Foundations                                                                       │
│  ·Risk and hedging│                                                                 │
│  ·Futures and RV  │                    area content                                 │
│  ·P&L and carry   │                                                                 │
│  ·Quoting         │                                                                 │
│  ·Mixed           │                                                                 │
│ LIVE DESK                                                                           │
│  ·L1 … L5         │                                                                 │
│ REVIEW            │                                                                 │
│  ·Questions       │                                                                 │
│  ·Sessions        │                                                                 │
│  ·Weak areas      │                                                                 │
└──────┴──────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Live Desk (L3 shown; panels exist only when the view carries their block)

```
┌ L3 Curve book · round 2/5 · 11:00 ─ vol calm · liq deep ─ P&L −€15.9k ─ DV01 −€19 /500k ▕▏ ─ slope −€9 /250k ▕▏ ─ [ref] [tape] ┐
├──────────────────────────────┬───────────────────────────────────────┬────────────────────────────────────────────────┤
│ MARKET                       │ TICKET                                │ RISK                                           │
│ curve   ╭───●──●────●        │ ┌ client request ───────────────────┐ │ POSITIONS                                      │
│ (now vs │   2Y 5Y  10Y 30Y   │ │ Pension fund (LDI)                │ │  5Y  rec 275m @2.2565                          │
│  open)  │                    │ │ wants to RECEIVE fixed            │ │  2Y  pay 825m @2.1709                          │
│ ladder                       │ │ €175m 5Y  · own DV01  −€82.1k     │ │  …                                             │
│ T   mid   bid/off  DV01/m c  │ └───────────────────────────────────┘ │ BUCKET DV01          LEVEL / SLOPE / CURV      │
│ 2Y  2.142 …                  │ ┌ your price ───────────────────────┐ │  2Y ▕██ −80k        −€19  ▕·   0 /250k        │
│ 5Y  2.255 …                  │ │ you PAY fixed at  [ 2.2544 ] %    │ │  5Y ▕█████ +129k    slope −€9  ▕·             │
│ 10Y 2.460 …                  │ │ vs street 2.2544 / 2.2560  −0.0bp │ │ 10Y ▕██ −48k        curvature +€127k (no limit)│
│ 30Y 2.717 …                  │ │ [ arm ]   [ pass ]                │ │ 30Y ▕ 0                                        │
│                              │ └───────────────────────────────────┘ │ CONDITIONS  flow: LDI morning …                │
├──────────────────────────────┴───────────────────────────────────────┴────────────────────────────────────────────────┤
│ TAPE  r1 rfq Sound · filled €225m 10Y +€21k │ r1 hedge Sound · 10Y+2Y −€9k │ r1 move −1.2bp (curv −€28k) │ …             │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Left = what the market says, centre = what I am being asked and what I commit, right = what I am carrying. Everything is a compact table with small bars; no paragraphs
on the desk surface. Conditions, the research view, evidence and the risk card sit in collapsible strips so that the surface stays quiet until they matter.

### 6.3 Ticket variants (centre panel, by `observation.kind`)

* **quote** (L1, L5 morning): two-way ticket. Controls for *skew* (bp vs mid) and *width* (bp), with bid and offer as derived read-outs next to the street market and the
  mid; or direct bid/offer entry. A bid/offer pair is what is submitted. Commit arms a confirmation.
* **rfq** (L2-L5): the client card (name where named, type, side, size, tenor, **its own DV01**, never its effect on the book), and a single price field with
  offset-from-mid and offset-from-street read-outs. `Pass` is a first-class button.
* **checkpoint**: a compact numeric question over the desk (the book stays visible where the episode shows it): prompt, unit-suffixed input. The slope check says
  "graded after you price" because the backend defers it.
* **hedge / rehedge / overnight**: a leg builder (section 6.4).
* **position** (L5): target-DV01 stepper (keep / flat / target ±k) plus explicit legs.

### 6.4 Hedge ticket

```
 HEDGE   [ Swap ▾ ] [ Receive | Pay ] tenor [2 5 10 30] size [ 150 ]m   → leg DV01 +€124.8k   [ add leg ]
         [ Bund FGBL ] contracts [-1348]                                 → leg DV01 −€125.4k
         [ CTD bond  ] face [ 50 ]m  buy/sell                            → leg DV01 …
 legs:   1) sell 1,348 FGBL      2) …                                   [ clear ]
 helpers [ 50% ] [ 100% ] [ flatten ] [ switch ] [ target … ]   (macros: resolved by the engine, shown back as legs before commit)
 cost to cross  (static facts from the ladder: bp per tenor, ticks per contract)      [ arm ]   [ no trade ]
```

Per-leg DV01 is plain arithmetic on ladder numbers the trainee already has (notional x DV01 per EUR 1m, contracts x DV01 per contract); the RFQ screen already shows a
trade's own DV01 the same way. **The ticket does not show the hedge's effect on the book, the expected P&L or a rating before commit** (section 11, decision D-1).
Macros (`100%`, `flatten`, `switch`, `target`) are sent as text to `parse`, which returns the legs the engine resolved; they are shown as ordinary legs and can be
edited before commit.

### 6.5 Question screen (TRAIN)

```
┌ TRAIN · Futures and RV · futures.dv01 · level 2 ──────────────────── 3 / 10 ─ ✓ 1  ✗ 1 ─ [ quit ] ┐
├───────────────────────────────────────────────┬────────────────────────────────────────────────────┤
│ PROBLEM                                       │ WORKSPACE                                          │
│ ┌ market ──────────────────────────────────┐  │  (1/3)  How many FGBL contracts hedge this?        │
│ │ EUR IRS curve: 2Y 2.690% | 5Y 2.901% …   │  │  [        ]  contracts      accepted: 1,348  −1.3k │
│ │ FGBL price 117.93 · DV01 €93 / contract  │  │  scratch:  125000/93 = 1344.1                      │
│ └──────────────────────────────────────────┘  │  [ submit ]  [ skip ]                              │
│ You are long €150m 10Y receivers …            │                                                    │
│                                               │  earlier parts: (1) A ✓  (2) 1,348 ✓               │
└───────────────────────────────────────────────┴────────────────────────────────────────────────────┘
```

### 6.6 Debrief (REVIEW mode of the same data)

```
┌ DEBRIEF · L4 products and the overnight · seed 3 ──────────────────────────────────────────────────┐
│ [decision quality] [outcome] [luck] [conditional]                      (the four-part strip)       │
│ ┌ rounds ──────┐  ┌ round 3 · overnight ────────────────────────────────────────────────────────┐ │
│ │ 1 rfq   S    │  │ DECISION  warehouse (no hedge)                                              │ │
│ │ 1 hedge S    │  │ RISK      DV01 −€1 · swap-spread −€147.9k/bp · basis −€13.5k/tick           │ │
│ │ …            │  │ ASSESS    SOUND · reasons · alternatives table (E, σ, rating)               │ │
│ │ 3 overnight S│  │ OUTCOME   carry +9.4k · roll −11.7k · convergence −14.4k · move +97k        │ │
│ │ …            │  │ LUCK      realised − expected                                               │ │
│ └──────────────┘  └─────────────────────────────────────────────────────────────────────────────┘ │
│ SAME PATH, OTHER POLICIES  table with rating strips          L5: 200-PATH DISTRIBUTION histogram   │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 7. Levels 1-5 in the UI

The UI is **data-driven**: a panel renders if and only if its block in `ObservationView` is non-null, so the progression follows the backend rather than a
parallel level switch. A thin per-level preset sets the initial layout and which strips start collapsed.

| Level | New on screen | Notes |
|---|---|---|
| L1 | quote ticket; one focus-tenor quote (`market.mode = single`); book as 1-3 rows; DV01 vs limit; checkpoint input; result panel | Risk card collapsed; no bucket, no curve panel beyond the 4-point curve. Loop made explicit in the top bar: quote -> fill -> position -> hedge -> move -> P&L |
| L2 | inventory carried across rounds; repeated RFQs; skew visible against inventory; desk-expectation strip; running P&L chart | Same layout as L1 plus the tape |
| L3 | `book.buckets` -> bucket DV01 bars; `book.slope` and `book.curvature` with the curve limit; swap ladder across 2/5/10/30; slope checkpoint | Curve risk becomes the main risk graphic: bucket bars and a level/slope/curvature mini-panel |
| L4 | `market.products` -> futures and CTD lines; `book.hedges`; `book.spreads` panel; `overnight` carry report; late-session cost note; switch macro | Hedge ticket gets Swap / Futures / Bond legs; a "what this hedge leaves" line is shown only after commit. Overnight and next-morning screens reuse the same ticket |
| L5 | `conditions.named_clients` evidence table; `conditions.research` strip with remaining view; calendar banner for the release; limit-cut announcement; position ticket; distribution in the debrief | The inventory / information / view separation shows up in the debrief decomposition, not as a live indicator; no inference about informed flow is displayed |

Each level's briefing and notes (from `header`) show once, in a dismissible banner, at the first screen of the round.

## 8. Key components

| Component | Fed by | Notes |
|---|---|---|
| `TopBar` | `episode`, `header`, `conditions`, `book.pnl_so_far`, `book.dv01`, `book.limit_dv01`, `book.slope.limit` | limit gauges amber from 70%, red from 100%, always with the number |
| `CurvePanel` | `market.curve` or `market.ladder` mids; history kept client-side | 4 tenors; ghost line = open or previous step |
| `SwapLadder` | `market.ladder` | tabular numerals; click a row to prefill a hedge leg |
| `ProductLines` | `market.products` | futures and CTD rows; ASW, yield, crossing cost |
| `PositionsTable` | `book.swaps`, `book.hedges` | rows; client vs hedge origin from the label |
| `RiskPanel` | `book.dv01`, `buckets`, `slope`, `curvature`, `curve_position`, `spreads` | bucket bars, exposure bars with limit ticks |
| `ConditionsStrip` | `conditions` | volatility, liquidity, flow, swap-cost multiplier, desk expectation, calendar |
| `ResearchStrip` | `conditions.research` | stated reliability, remaining view, per-step amount |
| `EvidenceTable` | `conditions.named_clients` | client, what it did, what the market did next; **no probability** |
| `RiskCard` | `risk_card` | training assumptions; factor vols and loadings; labelled as such |
| `ClientCard` | `inquiry`, `last_inquiry`, `clients_today` | request details and own DV01 |
| `QuoteTicket` / `RfqTicket` | `input`, `market` | skew/width or single price; derived read-outs are display arithmetic only |
| `HedgeTicket` | `input` (tenors, products, flatten/switch/target flags) | leg builder; macros via `parse` |
| `CheckpointInput` | `checkpoint`, `input` | unit-suffixed number |
| `ResultPanel` | `StepResultView.events`, `assessment`, `grade` | stages the reveal (section 10) |
| `EventTape` | accumulated results | one line per round |
| `DebriefTimeline`, `DecisionCard`, `CounterfactualTable`, `Distribution` | `DebriefView` plus stored step results | analytical layout |
| `QuestionCard`, `PartStepper`, `AnswerBox`, `Scratchpad`, `SolutionPanel` | `QuestionView` (section 16) | TRAIN |
| `SessionSummary`, `SkillTable`, `MissedQueue` | stored attempts | REVIEW |

## 9. Charts and visualisations

Only where they carry trading intuition; all hand-built SVG from tiny scale/shape helpers.

* **Curve (Live Desk):** the 4-tenor swap curve now vs the previous step or the open; the step result shows the curve change bp by tenor. Whether it
  steepened, flattened or moved in parallel is read from the shape of the change bars, not from words. (Needs section 16, item 3.)
* **Bucket DV01 bars** with a zero line; **level / slope / curvature** exposure bars with limit ticks; **spread** bars at L4/L5.
* **P&L path** across the episode (a step line of total P&L by round with the round's P&L bars) for the live tape and the debrief.
* **P&L by factor** (stacked or waterfall per round and total): level, slope, curvature, swap spread, futures basis, convexity, edge, hedge cost, carry/roll/funding.
* **Position evolution:** DV01 and slope through the episode, built from each observation's `book`.
* **Level 5 distribution:** histogram of the 200 path outcomes with markers for realised, your mean, reference mean (needs section 16, item 5).
* **Carry/roll breakdown** at the overnight (bars for carry, roll-down, funding, convergence) from the carry report and the overnight event.
* **Futures basis / implied repo:** these belong to TRAIN question screens (the data is in the stem text today); deferred until questions expose structured screens.

Not charted on purpose: tick-by-tick anything, candlesticks, a free-floating PnL speedometer.

## 10. Interaction model

**Commit is a two-step action.** The primary button reads *Review* ("arm"); arming locks the ticket inputs, shows a one-line summary of exactly what will be committed,
and turns the button into *Commit*. `Esc` disarms. This applies to every decision (quote, price, pass, legs, no trade). Enter on a disarmed ticket arms; Enter on an
armed ticket commits.

**Reveal staging.** Nothing from the result is rendered until the commit has returned. The `ResultPanel` then shows, in order: fill/trades (events), the market move (events),
P&L, then the assessment and the benchmark table. The next observation is **not fetched or rendered until the user presses Continue**, so no post-decision state (new
book, new curve) can show alongside the old ticket. The panel is a distinct "settled" state with a clear visual frame (dimmed ticket, "decision submitted" header).

**No accidental leakage.** Back/forward and reload never skip the reveal: the server stores the last `StepResultView` per session, so a reload after commit lands on the result panel,
not on the next question. Browser history does not contain intermediate states.

**Minimal typing.** Pay/receive toggles, tenor chips, size fields with `k`/`m` parsing (same `parse_number`), keyboard stepping of skew and width (`[` `]`, shift for
bigger steps), tenor hotkeys (`2 5 0 3`), `P` to pass, `N` for no trade, `F` flatten, `S` switch, `Tab` order matching reading order. A command line at the bottom accepts
the CLI's typed grammar (`100% 10y`, `sell 300 fgbl`) for fast users: it goes through the same `parse`.

**Errors.** Parse errors are inline, in the ticket, and never penalised. Wrong decision kind is rejected by the API (already tested).

## 11. Information visibility rules

The browser receives only `ObservationView`, `StepResultView`, `DebriefView`, question views and stored copies of those. It never receives an engine object, `Episode`,
`DecisionContext`, a seed or a replay record of an unfinished session.

| Item | When it may be shown |
|---|---|
| Book, ladder, conditions, research view (with its remaining part), named-client evidence (name, side, move), own-trade DV01 of a request | in the observation, as given |
| Risk card (training assumptions) | always; first screen shows the sentence |
| Rating, reasons, benchmark table, evidence-based P(informed) in reasons | only in the `StepResultView` returned by the commit; the UI offers a "hide probability" setting off by default (it is the existing post-commit reveal) |
| Market move, fills, P&L by factor | the same result |
| Counterfactual policies, luck, 200-path distribution, client truth, view truth | `DebriefView`, after the episode is done |
| Checkpoint answer | in the result of the checkpoint, except the slope check which is deferred to the pricing result |
| Informed flags and probabilities (pre-commit), signal truth, future moves, random streams, seeds, `ctx`, expected-P&L of options, hedge effect on the book | never before the commit |
| Replay record | server-side while the episode is running; offered for download only after `complete` |

Hard rules for the code: components only read fields declared in the TypeScript types; the typed fixtures come from the backend; a contract test asserts that none
of the forbidden keys (the same list used in `tests/episodes/test_plumbing.py`) appear in any fixture or any response.

## 12. Visual design system

**Direction:** a restrained electronic-trading workstation. Quiet, dense, numerate. Colour carries state, not decoration.

**Tokens** (CSS variables; dark is the only theme at first):

| Token | Role | Starting value |
|---|---|---|
| `--bg-0` | app background | `#0b0d10` |
| `--bg-1` | panel | `#111519` |
| `--bg-2` | raised / input | `#171c22` |
| `--line` | hairlines | `#222a33` |
| `--text-1` / `--text-2` / `--text-3` | primary / secondary / disabled | `#d7dde4` / `#97a1ac` / `#5c6670` |
| `--accent` | interactive, focus | `#4c8dff` |
| `--pos` / `--neg` | P&L and exposure sign | `#3fb68b` / `#e5534b` |
| `--warn` | limit use 70-100% | `#d4a72c` |
| `--bid` / `--offer` | pay-fixed side / receive-fixed side | a cool blue and a warm orange kept distinct from `--pos`/`--neg` |
| `--rating-*` | sound / defensible / poor / error | green, amber, red, red with a hatch (never colour alone) |

Rules: sign is always shown as a glyph (`+`/`-`) as well as colour; limits show both a bar and the figure; at most one saturated colour per panel; no gradients; corner radius
2-3px; hairline borders instead of shadows; no animation other than a 120ms state fade and the arm/commit transition.

**Type:** a proportional UI face (Inter or IBM Plex Sans) at 12-13px for labels and a monospaced face with tabular numerals (JetBrains Mono or IBM Plex Mono) for every number,
rate and DV01; right-align numeric columns; 11px for secondary labels, 20-24px only for the headline figures in the top bar and debrief strip. Density: 24-28px rows, 8px gutters.

**Modes:** Live Desk = densest (24px rows, 3-column grid, no scroll of the main surface); TRAIN = one centred measure, larger type for the problem (15-16px) and a generous answer
field; REVIEW = analytical, 2-column, 8px extra spacing, tables with sticky headers. They share tokens and components, so the product reads as one.

**Accessibility:** WCAG AA contrast on the dark tokens; all state also in text/glyph; full keyboard operation; focus ring uses `--accent`; reduced-motion honoured.

## 13. Frontend and backend architecture

```
 Python (frozen)                         Python (new, thin)                         Browser
 engine/ questions/ episodes/   →   rates_trainer/web/  (HTTP + static)   ←→   React + TypeScript SPA
   Session, QuestionSession(*)        sessions in memory                       Live Desk / Train / Review
   views are plain JSON               attempt store (files)                    no finance, no grading, no parsing rules
```

* **No finance in the browser.** Pricing, risk, grading, parsing (`parse`), simulation and replay stay in Python. The browser performs display arithmetic only
  (a leg's own DV01 from ladder numbers, bid/offer from skew and width, formatting).
* **Server.** A small local HTTP server holds `Session` objects in memory by id and exposes JSON endpoints (section 15). It serves the built SPA. It is single-user and
  local; no authentication.
* **Persistence.** Plain files under `~/.rates_trainer/` (configurable): an append-only attempts log (JSON lines) and one JSON transcript per finished episode. No database:
  the volume (hundreds of questions, tens of episodes) does not need one; SQLite is the fallback if the log is ever queried heavily.
* **Resuming.** Every submit rewrites the session's replay record; reopening an unfinished session replays it (about 1-3.5 s for levels 3-5, measured) or finds it in memory.
* **Latency (measured).** `observe` up to 0.3 s, `submit` under 0.1 s, `debrief(compare=False)` about 0.05 s, `debrief(compare=True)` 0.6-4.8 s. The debrief therefore loads in two
  steps: the immediate sections, then the counterfactual and distribution sections with a skeleton.
* **Contract tests on both sides.** The backend dumps golden JSON for each level and for questions; the frontend's types and component tests are built from those fixtures,
  so the UI can be developed with no server running and cannot drift silently.

## 14. State management

Server owns truth; the client owns presentation.

* **Server state** (TanStack Query): catalogue, question session, episode `ObservationView`, `StepResultView`, `DebriefView`, review aggregates. Mutations: start, submit, answer.
* **Live Desk client state** (a small store, Zustand or a reducer): `phase` in {`awaiting`, `armed`, `submitting`, `settled`}, the ticket draft per `kind`, the transcript
  `[ {observation, result} ]` accumulated this session (used for the tape, the P&L path, the position-evolution chart and the curve history), and UI flags (panel
  collapse). A finite-state machine governs `awaiting -> armed -> submitting -> settled -> awaiting`, and nothing else can reach `settled -> next observation`
  except Continue.
* **Question client state:** current part index, draft answer, per-part results, scratchpad text.
* **Review state:** filters and the selected session; aggregates computed on the server from the files.
* **Derived, never stored:** limit use, bar lengths, formatted strings.

## 15. Mapping the `Session` contract into the UI

| UI need | Contract | Notes |
|---|---|---|
| Start a level | `episode_for_level(level, seed)`, `Session.start/for_level` | seed chosen by the server; random per run, entered for replays |
| Resume | `Session.replay(record, upto)` | at most a few seconds |
| Render the desk | `Session.observe()` -> `ObservationView` | one call per phase |
| Ticket input -> decision | explicit legs/prices: send the **encoded decision dict** (`serial.encode_decision` schema); macros and typed fast-entry: send text to `parse`, receive the resolved decision (encoded), show it, then send it | `Session.parse` returns an object; the web layer encodes it |
| Commit | `Session.submit(...)` -> `StepResultView` | server caches the result for reload safety |
| Settled panel | `events` (`client_arrives`, `fill`, `passed`, `hedge_trade`, `skipped_trade`, `no_trade`, `overnight`, `market`, `round_pnl`, `checkpoint_*`), `assessment`, `grade` | typed rendering per event; no text parsing |
| Continue | `Session.observe()` | not called until Continue |
| Debrief | `Session.debrief(compare=False)` then `compare=True` | the second call fills counterfactuals and the Level 5 distribution |
| Replay/save | `Session.record()` (when `complete`) | stored with the transcript |
| Level list | `catalogue()` | plus a static UI copy file for level goals and skill links |

Field-level map for the main panels is in section 8. The checkpoint ticket uses `checkpoint.prompt`/`note` and (after fix 1 in section 16) `input.unit`.

## 16. Genuinely necessary API additions

All additive; none changes a financial or assessment result.

1. **Fix `input.unit` for checkpoints.** `views.input_spec` currently stores the *hint text* in `input.unit`. The checkpoint ticket needs the real unit (`EUR`, `contracts`, ...).
   Add `unit` from `NumericPart.unit`; keep `hint`.
2. **`QuestionSession` / question views** (`questions/api.py`, the counterpart of `episodes/api.py`). There is no plain-data surface for questions today: `Question` carries
   the answer inside its parts and `grade()` is a Python method. Needed: `catalogue()` (tracks -> skills -> source counts, difficulty, planned/curated), `start(filters, n, seed)`
   / `replay(ids)`, `current() -> QuestionView` (id, skill, track, difficulty, index/total, stem, parts with kind, prompt, unit, note, options; **never** the answer, tolerance or `facts`),
   `answer(part, raw | skip) -> PartResultView` (status: `unreadable | correct | incorrect | skipped`, feedback, expected, detail, rationale), `solution()` after the last part, and `summary()`.
   It wraps existing `build_queue`, `generate`, `from_id` and `Part.grade`; no question logic changes.
3. **Curve change by tenor in the `market` event** (`tenor_moves`: the par change in bp at 2/5/10/30). Without it the browser would have to combine factor moves with the risk card
   loadings, which is finance in the front end. The engine already computes the shock.
4. **Attempt store** (`rates_trainer/store.py`, files only): log question attempts (id, skill, difficulty, per-part outcome) and finished-episode summaries plus the transcript. Required by
   Review and by "replay what I missed"; it is the roadmap's "attempt log + review queue" (`DESIGN.md` item 4), plain record only, no adaptivity.
5. **`samples` in `market_paths`** (the 200 outcomes, whole euros) so the distribution can be drawn. Today only the mean, 5% and 95% points and the rank are returned.
6. *(later, for Weak areas)* **reason tags** on assessments: a short machine-readable list (for example `adds_risk`, `over_limit`, `curve_limit`, `spread_risk`, `ignored_evidence`) next to the prose
   reasons. Until then, weak areas are counts by decision kind and rating.
7. *(web layer only)* encode parsed decisions for the browser, cache the last result per session, hold sessions by id. No change to `Session`.

Not needed: any change to `ObservationView`'s existing fields, to the replay format or to the assessment logic.

## 17. Recommended implementation order

0. **Groundwork.** Web layer (sessions, encode/decode, last-result cache), API items 1 and 7, fixture dumper for L1-L5, shell, tokens, component library with fixture-driven stories. Attempt store write path
   (so history accumulates from day one).
1. **Milestone 1: Live Desk L1-L2 vertical slice.** Quote ticket, RFQ ticket, checkpoint, hedge ticket (swaps), result panel with the staged reveal, running P&L, v1 debrief
   (decisions, outcome, luck, same-path table), transcript saved. This exercises every phase of the contract.
2. **Milestone 2: TRAIN.** API item 2, question screen with part stepper and scratchpad, session modes and summary, missed-queue replay; attempts logged.
3. **Milestone 3: L3.** Bucket DV01, slope and curvature panels, curve limit, ladder, deferred slope check. API item 3 (curve change).
4. **Milestone 4: L4.** Product lines and tickets (FGBL/FGBM/CTD), spread and basis exposures, overnight and morning screens, switch.
5. **Milestone 5: L5.** Evidence table, research strip, calendar and limit-cut banners, position ticket, 200-path distribution (API item 5).
6. **Milestone 6: REVIEW.** Question performance, session list with re-rendered debriefs, weak areas (item 6 if wanted), risk/P&L analysis.
7. **Hardening.** Keyboard map, accessibility pass, e2e tests against fixtures and the live server, packaging (`./trainer ui`).

Rationale: the vertical slice proves the boundary and the aesthetic early; TRAIN is second because it completes "two halves of one product" and is mostly independent of L3-L5; levels
then add panels, not architecture; Review comes last because it needs data, but it records from milestone 1.

## 18. Recommended frontend stack

Options considered:

| Option | Verdict |
|---|---|
| Streamlit | No. Rerun-the-script model fights a stateful ticket flow; weak control of dense layout and keyboard; the commit/reveal staging would be fragile |
| NiceGUI / Dash / Reflex (Python-only UIs) | Possible and zero JavaScript, but custom dense tables, SVG charts and keyboard-driven tickets become workarounds; styling control is limited |
| Textual (terminal UI) | Attractive for a "workstation" feel but poor for charts and for long use; not chosen |
| Next.js | Not needed: no SEO, no SSR, a local single-user app; extra weight and a second server |
| SvelteKit / Solid | Good fits technically; smaller ecosystem and fewer ready-made accessible primitives; viable if you prefer them |
| **React + TypeScript + Vite** | **Chosen**: static build served by the Python server, the largest ecosystem for tables, accessibility and testing, fast iteration |

Recommended: **React 18 + TypeScript + Vite**; **TanStack Query** for server state; **Zustand** for the Live Desk store with an explicit state machine; **CSS variables + CSS Modules**
(no CSS framework: the look is a design system of its own); charts as **hand-built SVG** over `d3-scale`/`d3-shape` (a handful of small charts, no charting library); **TanStack Table** only in
Review; **Radix primitives** for accessible popovers/tabs/dialogs; **Vitest + Testing Library** for components, **Playwright** for end-to-end against fixtures and the live server.
Backend: **FastAPI + uvicorn** as an optional `ui` extra (the engine keeps its stdlib-only runtime); the API is about a dozen JSON endpoints, so a stdlib `http.server` fallback is possible if you want zero
new Python dependencies. Types: TypeScript types written against the contract and verified by fixture tests (no Pydantic models in front of the views, so the Python contract stays the single definition).

## 19. Decisions for you

* **D-1: a pre-commit "what-if" on hedges.** The brief lists "expected risk effect" in the hedge area. Showing the resulting book (DV01, buckets, slope, spreads) of a *proposed* hedge before
  commit would do the L1/L3 skill for the trainee and cuts against the rule you set for commit-before-reveal. Recommended: **no what-if**; the ticket shows each leg's own DV01 and the static cost facts only,
  and the effect is revealed after commit. If you want it, the clean version is an explicit, per-level, off-by-default "desk what-if" toggle backed by a new `Session.preview(decision)`; that is a training
  decision and a backend addition, so it needs your approval.
* **D-2: the post-commit P(informed).** It is part of the existing reveal. Keep as is (recommended), or hide behind a setting.
* **D-3: concept reference cards.** None exist; add later as static notes per skill, or leave the slot out.
* **D-4: packaging.** Browser tab launched by `./trainer ui` (recommended first) versus a desktop wrapper (Tauri) later.

---

## 20. Milestone 1 as built (Live Desk L1-L2 vertical slice)

Decisions taken after the design review: no `Session.preview` (the hedge ticket shows each leg's own DV01 and the static cost facts, never the effect on the book);
the model's P(informed) is **not** shown on the live desk (it is in the debrief); no reference-card system; browser first, no desktop wrapper.

**Built.** Application shell (TRAIN, LIVE DESK, REVIEW; TRAIN and REVIEW are placeholders reading the real catalogue and the saved sessions). Live Desk for levels 1 and 2 through the
real `Session`: start / resume, market panel (curve with previous-step and open lines, change per tenor, street quote), quote ticket (bid/offer, skew and width), RFQ ticket (client card,
own DV01, price against mid and street, Pass), calculation check with its unit, hedge ticket (legs, 25/50/100% macros resolved by the engine, No trade), arm -> commit -> staged result ->
Continue, position and risk with limit gauge, conditions, tape, reference sheet (conventions and training assumptions, once), debrief (the four-part strip, round by round, P&L path,
P&L by cause, same-path policies loaded second, clients revealed). Levels 3-5 are listed as not in this build; panels for them are not drawn because the views do not carry their blocks.

**API changes (all additive).** `input.unit` now holds the unit (`%` for quote and rfq, the checkpoint's own unit for a number; it used to hold the hint text). `Session(...,
reveal_inference=False)` leaves the model's P(informed) out of results (default True, so the CLI and tests are unchanged). `DebriefView.decisions[].reasons` carries the full reasons
including the probability. `questions/api.catalogue()`. New: `web/` (FastAPI app, local store), `./trainer ui`, `scripts/dump_fixtures.py`.

**Server behaviour.** One in-memory `Session` per id with a lock; the last result is held until Continue so a reload cannot skip it; debrief and replay record are refused until the last result
has been continued past; finished episodes are written to `$RATES_TRAINER_HOME` (default `~/.rates_trainer/episodes/*.json`: replay record, transcript, summary, debrief).

**Known limits.** Sessions live in server memory (a restart loses unfinished ones; finished ones are saved). The information-widening figure in the Level 5 price decomposition still
reflects the inference even with the probability hidden. The curve panel shows the four tenors the views carry.

### 20.1 Live Desk composition (revised after first use)

The first version stacked panels at their natural height under the top bar and reserved the lower area for results, so an active decision left half the window empty. The desk is
now two compositions that each fill the space under the top bar (columns are flex stacks; `grow` panels take what is left; panel bodies scroll rather than push):

* **Decision** (market | action | book and risk): left, the street quote in the traded tenor as three large figures, the curve (takes the free height; previous-step and open lines) and a tenor
  table with change since previous step and open. Centre, one coherent action column: the briefing, the client request, the ticket (quote, price, calculation check or hedge) and the
  review/commit bar pinned at the bottom. The price tickets draw a **price ladder** (bp around the mid, the street band, your own bid/offer or price) in the space the inputs leave; the
  hedge ticket is an instrument table (mid, DV01 per EUR 1m, cost to cross, DV01 and cost for EUR 100m, quick Pay/Rec) over a legs area; the calculation check carries a scratch calculator.
  Right, risk first (DV01 headline, limit gauge and a vertical scale from -limit to +limit), then positions, then conditions.
* **Result** (move and P&L | judgement | position after): left, the market move as a headline and the factor moves, P&L attribution and the P&L path (or, for steps with no move yet, the
  outcome of the step above the dimmed market); centre, what happened, the assessment with its benchmark table, the session blotter (every decision committed so far) and Continue pinned
  at the bottom; right, risk after the decision on the same scale (at decision and after), the position with the new trades marked.

Persistent across both: top bar, trading-loop rail, tape and the risk/positions column. The ticket and the market panels are not shown under the result, and the result is not shown under the
ticket. Layout is fluid (fr columns with minimum widths, heights from the flex stack), verified at 1280x720, 1480x900 and 1920x1080 by an end-to-end test that fails if a column stops short of
the bottom or the page scrolls.

### 20.2 Leaving a level, and spacing polish (layout frozen)

The §20.1 composition is frozen. Two small changes followed first use:

- **‹ Levels** (top bar, left, ghost-weight; also **‹ Back to Levels** in the debrief) returns to the level menu from any Live Desk state. It is a navigation action in the existing store, not a new mechanism: `useDesk.leave()` goes through the phase machine (`RESET`), which is refused while a start, commit or continue is in flight (the button is disabled then). Leaving sends nothing: no parse, submit or continue. An unfinished episode asks first (`LeaveDialog`, focus on *Keep playing*; while it or the Reference sheet is open, no key can arm, commit or continue). The session is forgotten by this screen (so a reload does not drop the trainee back into it) but stays on the server and is listed under IN PROGRESS to resume deliberately, until the server restarts. A slow start/resume that returns after the screen was abandoned is ignored.
- Cosmetic only: condition labels no longer touch their values; the RFQ readouts are a label/value grid; street labels read as one aligned two-line block; the hedge table headers align to the bottom and the No trade button sits at the end of the row; ladder and thermometer labels are pushed apart when prices are close; panel titles no longer collide with their asides.

### 20.3 Deleting unfinished sessions

Unfinished Live Desk sessions exist **only in the server process** (`Desk` objects, at most 20, lost on restart); nothing about them is on disk. Finished episodes are the files in `$RATES_TRAINER_HOME/episodes` and belong to Review. Test runs never share the home: pytest uses `tmp_path`, Playwright a private home and port.
`GET /api/desk` lists unfinished sessions (level, short id, start time, round and phase, whether it is already in history; never the seed). `DELETE /api/desk/{id}` removes one (taking the session lock, so it cannot land between a commit and its result; 409 for a finished episode, 404 afterwards), `DELETE /api/desk` removes all unfinished ones. The menu's IN PROGRESS table has per-row *Delete* with an inline confirmation, *Delete all unfinished…*, a success line and an error line, and refreshes from the server. Nothing is submitted, continued or revealed. An episode whose last result is still waiting is already saved for Review; deleting its session leaves that file alone.

## 21. Milestone 2 as built (TRAIN)

**Backend.** `questions/practice.py` `QuestionSession` (exported from `questions/api.py`): `start(tracks, skills, difficulty, max_difficulty, kind, count, seed)` for focused and mixed practice, `single(template_id, seed?)`, `replay(ids)`; then `question_view()` / `state()`, `check(raw)`, `submit(raw)`, `skip()`, `next()`, `finish()`, `summary()`, `record()`. Generation is `registry.generate` (lazily, so a session starts instantly), grading is `Part.grade`, the queue is the terminal's own (`session.plan_queue`, which `build_queue` now calls: same order, same seeds). A multi-part question is asked one part at a time and the next part's prompt is not in any view until `next()`. A view never carries the answer, tolerance, first-order estimate, correct option, rationale, solution or `facts`; a part's result carries expected / detail / rationale, and the worked solution arrives with the last part's result. An unreadable entry (including an unknown suffix) is refused and not marked; skip is marked wrong. The catalogue now also lists each source (`items`) and counts conceptual / calculation sources.
**Web.** `/api/train/start | {id} | check | answer | continue | finish | summary | history` (see `web/app.py`); sessions are held by id and survive a reload; a practice session's record is rewritten to `$RATES_TRAINER_HOME/practice/<start>_<id>.json` after every graded part (so an abandoned session keeps what was answered).
**Frontend.** `train/`: `Catalogue` (tracks and skills from the real catalogue, planned skills marked, difficulty / type / count filters, per-skill source list with *Practise this one*, replay by id, recent practice), `Practice` (problem left: tags, stem as prose and market-screen blocks, part stepper, earlier parts; workspace right: choice options on A–E, or numeric entry with unit, the grader's own "read as" and a scratchpad; result block with your answer / result / expected / working / why as separate rows; worked solution; Next), `Summary` (parts correct, by skill, per question, replay what you missed, same selection again), `store.ts` (server state is the truth; busy flags; epoch guard). Ending a session asks first and keeps what was answered. Switching area and back keeps the session where it was, and a reload resumes it.
**Not done on purpose:** concept reference cards, adaptive difficulty, timers, streaks, the Live Desk "Drill" links (item 2.1 above), and Review analysis of practice attempts (the records exist; Review lists them).

## 22. Milestone 3 as built (Live Desk levels 3-5)

The desk is data-driven, as section 7 intended: a panel exists because its block is in the observation, and the two compositions of section 20.1 are unchanged. L1/L2 screens are byte-for-byte the same components; the new ones are selected by what the views carry (`market.mode = "ladder"`, `book.buckets`, `market.products`, `conditions.research`, `overnight`, `input.can_*`).

**Shared.** `derive.focusOf` picks the street of the tenor being asked about from a ladder, so the quote and RFQ tickets, the price ladder and the keys work unchanged. `MarketPanel` on a ladder: street hero (only when a tenor is being asked about), curve with the previous and open lines, a swap ladder with cost to cross and change since the previous step, and futures and bond lines at level 4. `CurveRisk` replaces the single-DV01 thermometer for a book that is a curve: DV01 and slope against their limits, DV01 by bucket, and the exposures with no limit (curvature, swap spread, futures basis); after a commit it shows the exposures the assessment reports for the decision (under the same rule as the DV01: a price that did not deal changed nothing). `PositionsPanel` lists the futures and bond hedges held and the ones a result adds. The top bar carries both limits (compact gauges), the research view's remainder and a release chip.
**L3.** Hedge ticket built from the ladder (four tenors, `Flatten` resolved by the engine into legs); the slope check shows the request it refers to ("not priced yet") and the slope loadings from the risk card; the result leads with the par change by tenor (`tenor_moves`), then P&L by factor.
**L4.** Hedge ticket with swap, futures and CTD-bond legs (units: contracts, EUR m face), per-leg DV01 and cost from the product lines' own numbers, `Switch to swaps` (the engine's `switch`) when product hedges are held; the close shows the book's overnight carry, roll-down and funding, and the result splits the overnight by cause; the swap-cost conditions state the late-day multiplier and the size term as the terminal does.
**L5.** Quote and RFQ tickets on the focus tenor; "Read the room" beside the market (research view with stated reliability and what is left of it; named clients' record: side, then what rates did), the returning client's own record on its request card; the release chip and the limit cut (banner and limits); the position ticket (`Keep`, `Flat`, a DV01 target in 50k steps, all resolved by `parse` into legs); the assessment shows what moved the price (inventory, information, view, in bp); the debrief adds the information revealed (model's P(informed) against the truth, the view) and the distribution over simulated paths with the realised result marked.
**Information flow.** Unchanged: the hedge or position ticket shows only its own legs; the effect on the book, the benchmark and the rating come with the commit; the next observation waits for Continue; the model's probability and informed flags are in no live view (the live desk uses `reveal_inference=False`) and appear only in the debrief. The additive API fields are `market.tenor_moves` and `market_paths.*.samples` (EPISODES.md 19.5b).
