# Linear Rates Trainer

**An interactive training workstation for learning to think like a EUR rates trader.**

Linear Rates Trainer helps you build the product knowledge, quantitative intuition and trading judgement needed on a linear interest-rate trading desk. It combines standalone questions with stateful market-making simulations, covering the full process from pricing a trade to managing the resulting risk, hedging a book and understanding P&L.

The focus is practical: not just knowing the formulas, but understanding what they mean for a trading position.

## What you can do

### Train your rates knowledge

Practise across **41 skills and 10 curriculum tracks**, from foundational rate mathematics to desk-level trading decisions.

- **Curves and pricing:** discount factors, bootstrapping, interpolation, spot and forward rates, par swap rates and swap valuation.
- **Risk and hedging:** DV01, key-rate risk, curve exposures, hedge ratios, convexity and portfolio scenarios.
- **Rates products:** swaps, FRAs, basis swaps, government bonds, asset swaps, repo and interest-rate futures.
- **P&L and holding-period economics:** carry, roll-down, funding, breakeven analysis and P&L attribution.
- **Market-making:** bid/offer conventions, client flow, inventory management, quoting, requoting and adverse selection.
- **Relative value and macro:** curve steepeners, flatteners, butterflies, cross-product hedging and trading around market events.

Questions range from conceptual checks to numerical calculations and multi-step problems. Use the track, skill, difficulty, question-type and session-length filters to focus your practice. Parameterised questions provide variation across seeds, while worked solutions explain the reasoning behind the answer.

### Practise running a trading book

The Live Desk puts you into simulated trading situations where your decisions affect your position, risk and P&L.

| Level | Training focus |
|---|---|
| **L1 — Market-making basics** | Quote a market, handle a client trade, hedge or warehouse the risk, and manage the subsequent market move. |
| **L2 — Multiple clients** | Handle successive requests while carrying inventory and tracking cumulative P&L. |
| **L3 — Curve risk** | Manage a multi-tenor swap book, interpret bucket DV01 and choose hedges based on whole-book exposures. |
| **L4 — Cross-product hedging** | Use swaps, government bond futures and cash bonds to manage risk, then assess overnight carry, roll-down and funding. |
| **L5 — Information and views** | Manage client flow, research views, scheduled releases, changing risk limits and adverse-selection risk. |

Each episode follows a decision process: observe the market, make a decision, commit, see the result and continue. The debrief helps you examine the outcome, risk taken and consequences of your decisions.

The market and episodes are simulated rather than connected to live market data. The aim is to develop sound reasoning in a controlled environment.

## Getting started

You can use the trainer from Terminal or launch the web workstation in your browser.

### Option 1 — Terminal

Requires Python 3.11 or later.

```bash
git clone https://github.com/Angu5Martin/RatesTradingTrainer.git
cd RatesTradingTrainer

python3 -m venv .venv
.venv/bin/pip install -e .
```

Examples:

```bash
# Five mixed questions
./trainer

# Ten market-making questions
./trainer -n 10 --track mm

# Focus on a specific skill
./trainer --skill risk.hedge_ratio --level 2

# Browse curriculum and coverage
./trainer list

# Replay a particular question
./trainer --replay mm.client_trade_risk#249523

# Start a Live Desk episode
./trainer episode -L 3
./trainer episode -L 5 --seed 7
```

Use `./trainer --help` for the available options.

### Option 2 — Web workstation on macOS

The browser interface brings TRAIN and Live Desk together in one workstation.

**One-time setup**

From the project directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[ui]'
cd frontend
npm install
npm run build
cd ..
scripts/install_launcher.sh
```

If you already have the project's `.venv`, you do not need to recreate it. The launcher can also build the frontend when required, so the explicit build step is optional if you prefer to let it handle that on first launch.

**Every subsequent session**

1. Double-click **Rates Trainer** on your Desktop.
2. A Terminal window starts the local server, and your browser opens once the application is ready.
3. Leave the Terminal window open while using the workstation.
4. Press `Ctrl+C` in that window when you finish.

The workstation normally runs at [http://127.0.0.1:8765](http://127.0.0.1:8765). If that port is occupied, the launcher checks the existing server and may use another free port. It does not terminate unrelated processes.

If macOS blocks the launcher on first use, right-click it, select **Open**, and confirm.

You can also start the workstation directly from Terminal:

```bash
./trainer ui
```

The web interface requires the optional UI dependencies and a built frontend.

## A realistic rates engine

The trainer uses a Python financial engine as the source of truth for calculations and assessments. Its conventions include:

- TARGET calendars, ACT/360 and 30E/360 day counts
- €STR OIS discounting and 3M/6M Euribor projection curves
- Swap valuation, forward-starting swaps, FRAs and basis swaps
- Bond valuation, asset swaps, repo and specialness
- Bund, Bobl and Schatz futures, including conversion factors, CTD selection, futures DV01, implied repo and basis trades
- Carry, roll-down, funding and holding-period P&L attribution
- First-order DV01 estimates alongside full revaluation

Question generation is deterministic for a given template and seed, supporting reproducible practice and replay. Completed Live Desk episodes and TRAIN attempts can be saved locally for later review.

## Conventions worth knowing

- **DV01:** P&L for a 1 bp fall in rates; a long-duration position has positive DV01.
- **Swap bid:** the dealer pays fixed.
- **Swap offer:** the dealer receives fixed.
- **Client pays fixed:** the client hits the dealer's offer, leaving the dealer receiving fixed and long duration.

These conventions are used consistently throughout the questions and trading simulations.

## Local data and testing

The web application stores user data locally, normally under `~/.rates_trainer`, or under `$RATES_TRAINER_HOME` if configured. Practice history and completed episodes are separate from the source code.

Automated tests should use isolated temporary data directories so test sessions do not appear in your personal training history.

To run the Python test suite:

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

Frontend tests and end-to-end tests have their own dependencies and setup.

## Project documentation

- [`CLAUDE.md`](CLAUDE.md) — project brief and development constraints
- [`docs/DESIGN.md`](docs/DESIGN.md) — engine architecture and financial conventions
- [`docs/EPISODES.md`](docs/EPISODES.md) — Live Desk mechanics and episode design
- [`docs/UI.md`](docs/UI.md) — workstation interface and interaction design
- [`docs/CURRICULUM.md`](docs/CURRICULUM.md) — question coverage, curriculum mapping and source audit

## Scope

Linear Rates Trainer is a training and simulation tool, not a live trading system. It does not connect to a broker or use live market data. Its purpose is to help develop the product understanding, quantitative skills and decision-making discipline needed to manage linear interest-rate risk.