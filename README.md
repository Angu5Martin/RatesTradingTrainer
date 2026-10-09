# Linear Rates Trainer

Interactive trainer for thinking like a junior EUR linear-rates trader: trades, risk, hedges, P&L and
market-making. See `CLAUDE.md` for the brief and `docs/DESIGN.md` for the architecture and conventions.

```bash
./trainer                       # 5 mixed questions
./trainer -n 10 --track mm      # market-making only
./trainer --skill risk.hedge_ratio --level 2
./trainer list                  # curriculum and coverage
./trainer --replay mm.client_trade_risk#249523
./trainer episode -L 1          # market-making episode: quote, fill, hedge or warehouse, market move, debrief
./trainer episode -L 2 --seed 7 # five client requests, carrying your inventory and P&L
./trainer episode -L 3          # a curve book: price by whole-book risk, hedge where it matters
./trainer episode -L 4          # hedge with futures and bonds late in the day, hold risk overnight, re-hedge in the morning
./trainer episode -L 5          # named clients, a research view, a data release and a limit cut
./trainer ui                    # the web workstation (needs: pip install -e '.[ui]' and cd frontend && npm install && npm run build)
```

## Launching the workstation on a Mac (double-click)

One-time setup (creates the Python environment if you have not yet, builds nothing until first launch):

```bash
cd /path/to/Linear-Rates-Trainer
python3 -m venv .venv && .venv/bin/pip install -e '.[ui]'    # skip if .venv already exists
scripts/install_launcher.sh                                    # puts "Rates Trainer.command" on your Desktop
```

Each day: double-click **Rates Trainer** on the Desktop. A Terminal window opens, the server starts, and your browser opens at <http://127.0.0.1:8765> once it answers. Leave the window open while you use it.
To stop: press **Ctrl-C** in that window, or close it. (From another terminal: `.venv/bin/python scripts/launch.py --stop`.) The first time, macOS may ask you to confirm: right-click the file, choose Open, then Open.

What it does, in order: finds the project and its `.venv`; checks the port; builds the frontend only if its sources changed since the last build (needs Node/npm; the first launch installs the packages); starts `./trainer ui`; waits until `/api/health` answers; opens the browser.
* **Port taken?** It looks at what is answering. If it is this application on the same data, it just opens it. If it is anything else (or the trainer on a different data directory) it leaves it alone and uses the next free port (8766, ...), and says so. It never kills anything it did not start.
* **Your data** is in `~/.rates_trainer` (`episodes/` and `practice/`), or `$RATES_TRAINER_HOME` if you set it. The launcher never deletes, resets or moves it. Tests and the end-to-end suite use temporary directories, so their sessions never appear in the normal interface.
* **Errors** (no `.venv`, no npm, a failed build, the server stopping or not answering) are explained in the window, which stays open until you press Return.
* The Desktop file is a short stub pointing at the project's `Rates Trainer.command`, so pulling updates needs no reinstall. If you move the project folder, run `scripts/install_launcher.sh` again from the new place.

The question bank covers all 41 skills in ten tracks with standalone questions (curve mathematics and bootstrapping, money markets and bills, swap valuation and conventions, key-rate and factor risk, convexity,
butterflies, bucketed books and scenarios, quoting, re-quoting, cross-product hedging, events). `docs/CURRICULUM.md` has the coverage table, the audit of the sources and what could and could not be verified from the public book material.

Runs on stock Python 3.11+ with no dependencies. Answers: `225k`, `-1.2m`, `3bp`, `2.85%`, or a letter
for multiple choice; `skip` reveals the answer; `q` quits.

Tests (needs `pytest`): `python -m venv .venv && .venv/bin/pip install pytest && .venv/bin/python -m pytest`

Engine: real dates (TARGET, ACT/360, 30E/360), ESTR-OIS discounting with 6M and 3M Euribor projection curves, forward-start swaps, FRAs and basis swaps.
Asset swaps and swap spreads, cash-vs-swaps hedging, repo and specialness, bond carry and roll-down against repo.
Bund / Bobl / Schatz futures (conversion factors, futures DV01 and CF-weighted hedges, cheapest-to-deliver as a net-basis ranking, CTD switches, implied repo, the basis trade) and 3M Euribor futures strips.
Carry, roll-down and breakeven (static curve vs forwards realised), warehousing versus risk, and holding-period P&L attribution.
Every P&L answer shows two numbers afterwards: the fast first-order estimate (-DV01 x move) and the full revaluation.

Conventions to remember: **DV01 = P&L for a 1bp fall** (long duration positive); **bid = you pay fixed,
offer = you receive fixed**; a client who *pays* hits your offer and leaves you long duration.
