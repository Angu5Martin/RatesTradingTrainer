"""Command line entry point: `rates-trainer` (practise) and `rates-trainer list` (curriculum)."""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

from .curriculum.skills import SKILLS, TRACKS
from .episodes.episode import all_episodes
from .questions.registry import all_specs, from_id, select
from .session import build_queue, print_summary, run_session


def _list_curriculum() -> None:
    counts = Counter(s.skill for s in all_specs())
    curated = Counter(s.skill for s in all_specs() if s.curated)
    episodes = Counter(e.skill for e in all_episodes())
    for track, title in TRACKS.items():
        print(f"\n{title}  [{track}]")
        for sk in SKILLS.values():
            if sk.track != track:
                continue
            n, ne = counts.get(sk.id, 0), episodes.get(sk.id, 0)
            tag = (f"{n} source(s), {curated.get(sk.id, 0)} curated" if n else "") + (f"{', ' if n else ''}{ne} episode(s)" if ne else "")
            tag = tag or ("planned" if sk.planned else "NO QUESTIONS")
            print(f"  {sk.id:<30} {sk.title:<62} {tag}")


def _serve_ui(port: int, open_browser: bool) -> int:
    try:
        import uvicorn

        from .web.app import app, default_static_dir
    except ImportError:
        print("The web UI needs its optional dependencies:  pip install -e '.[ui]'", file=sys.stderr)
        return 2
    if not default_static_dir().is_dir():
        print("The frontend is not built yet:  cd frontend && npm install && npm run build", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{port}/"
    print(f"Rates trainer on {url}  (Ctrl-C to stop)")
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rates-trainer", description="EUR linear-rates trading trainer")
    ap.add_argument("command", nargs="?", choices=["practice", "list", "episode", "ui"], default="practice")
    ap.add_argument("--episode-level", "-L", type=int, choices=[1, 2, 3, 4, 5], default=1, help="episode level (with 'episode')")
    ap.add_argument("-n", "--count", type=int, default=5, help="number of questions (default 5)")
    ap.add_argument("--track", action="append", choices=sorted(TRACKS), help="restrict to a track (repeatable)")
    ap.add_argument("--skill", action="append", help="restrict to a skill id (repeatable)")
    ap.add_argument("--level", type=int, choices=[1, 2, 3], help="only this difficulty level")
    ap.add_argument("--max-level", type=int, choices=[1, 2, 3], help="at most this difficulty level")
    ap.add_argument("--seed", type=int, help="random seed for reproducible sessions")
    ap.add_argument("--port", type=int, default=8765, help="port for 'ui' (default 8765)")
    ap.add_argument("--no-browser", action="store_true", help="with 'ui': do not open a browser tab")
    ap.add_argument("--replay", action="append", metavar="ID", help="regenerate a specific question id (repeatable)")
    args = ap.parse_args(argv)

    if args.command == "list":
        _list_curriculum()
        print("\nEpisodes (./trainer episode -L N [--seed S]):")
        for e in all_episodes():
            print(f"  L{e.level} {e.id:<28} {e.title}")
        return 0

    if args.command == "ui":
        return _serve_ui(args.port, not args.no_browser)

    if args.command == "episode":
        from .episode_session import run_episode
        from .episodes.api import Session, episode_for_level
        seed = args.seed if args.seed is not None else random.randrange(1_000_000)
        eid = episode_for_level(args.episode_level, seed)           # level 3 has two variants, chosen by seed
        print(f"Episode {eid}#{seed}. DV01 = P&L for a 1bp FALL in rates. Bid = you pay fixed; offer = you receive fixed.")
        run_episode(Session.start(eid, seed), ask=input, say=print, color=sys.stdout.isatty())
        return 0

    rng = random.Random(args.seed)
    if args.replay:
        questions = [from_id(q) for q in args.replay]
    else:
        specs = select(all_specs(), set(args.track or []), set(args.skill or []), args.level, args.max_level)
        if not specs:
            print("No questions match those filters. Try `rates-trainer list`.", file=sys.stderr)
            return 2
        questions = build_queue(specs, args.count, rng)

    print("EUR rates trainer. Answer in EUR (225k, 1.2m), bp or % as asked; letters for multiple choice; "
          "'skip' reveals; 'q' quits.")
    print("DV01 = P&L for a 1bp FALL in rates (long duration positive). Bid = you pay fixed; offer = you receive fixed.")
    res = run_session(questions, ask=input, say=print, color=sys.stdout.isatty())
    print_summary(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
