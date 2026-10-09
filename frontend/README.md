# Rates desk frontend

React 18 + TypeScript + Vite. It renders the public views of the Python engine (`docs/EPISODES.md` section 19, `docs/UI.md`) and computes no finance.

    npm install
    npm run build        # builds into ../src/rates_trainer/web/static, which the Python server serves
    npm test             # vitest: machine, formatting, drafts, store, screens, contract (against recorded real sessions in src/fixtures)
    npm run e2e          # playwright against the real server and engine (builds first; private port and history directory)
    npm run fixtures     # re-record src/fixtures from the Python Session (after any change to the views)
    npm run dev          # vite on :5173, proxying /api to a server already running on :8765 (../trainer ui --no-browser)

Layout: `src/api` (types and fetch client), `src/lib` (formatting, display arithmetic), `src/desk` (Live Desk: phase machine, store, tickets, result, debrief),
`src/shell` (areas and rail), `src/train`, `src/review` (placeholders on real data), `src/components` (panel, gauge, charts), `src/styles` (tokens first).


## TRAIN

`src/train/` is the practice area (catalogue and builder, one-problem practice screen, summary). It talks to `/api/train/*` only; grading and generation stay in Python (`questions/practice.py`). Fixtures `train_multi`, `train_focus`, `train_catalogue` are real sessions dumped by `scripts/dump_fixtures.py`.


## Levels 3-5

No level switch: the desk renders the blocks the observation carries (ladder market, bucket risk, product lines, research view, overnight). Fixtures `l3_*`, `l4_*`, `l4_products`, `l5_*`, `l5_position` are real sessions (the last two answer hedge-like prompts with typed text so futures, the bond, switch and target are covered). `src/__tests__/levels.test.tsx` renders them; `e2e/levels.spec.ts` plays all three levels through the real server.
