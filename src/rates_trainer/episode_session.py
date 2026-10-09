"""Thin terminal adapter for episodes: renders views and results as text, turns typed text into decisions via the Session. I/O is injected.

All wording is in episodes/render.py and all parsing in episodes/decisions.py; this file only prints, prompts and colours.
"""

from __future__ import annotations

from typing import Callable

from .episodes.api import Session
from .episodes.episode import Episode
from .episodes.render import assessment_lines, debrief_lines, observation_lines, result_lines
from .session import Quit, _wrap


def run_episode(ep: Episode | Session, ask: Callable[[str], str] = input, say: Callable[[str], None] = print, color: bool = False,
                compare: bool = True) -> bool:
    """Play one episode. Returns False if the trainee quit early."""
    sess = ep if isinstance(ep, Session) else Session.from_episode(ep)

    def c(code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if color else s

    try:
        while not sess.done:
            view = sess.observe()
            say("")
            for i, line in enumerate(observation_lines(view)):
                say(c("1", line) if i == 0 and line.startswith("──") else _wrap(line))
            say(c("36", _wrap(view["prompt"])))
            say(f"   [{view['input']['hint']}; 'q' quits]")
            while True:
                raw = ask("> ").strip()
                if raw.lower() in {"q", "quit", "exit"}:
                    raise Quit
                try:
                    decision = sess.parse(raw)
                except (ValueError, KeyError) as e:
                    say("   " + str(e).strip("'\""))
                    continue
                break
            res = sess.submit(decision)
            if res["assessment"] is not None:
                colour = {"sound": "32", "defensible": "33", "poor": "31", "error": "31"}[res["assessment"]["rating"]]
                for role, text in assessment_lines(res["assessment"]):
                    if role == "headline":
                        head, _, tail = text.partition("  (")
                        say(c(colour, "   " + head) + "  (" + tail)
                    elif role == "reason":
                        say(_wrap(text, "   "))
                    elif role == "note":
                        say(c("2", _wrap(text, "   ")))
                    elif role == "row":
                        say(c("2", "   " + text))
                    else:
                        say(c("2", "   " + text))
            for line in result_lines(res["events"]):
                say(_wrap(line, "   "))
        say("")
        say(c("1", "═" * 30 + " DEBRIEF " + "═" * 30))
        for line in debrief_lines(sess.debrief(compare=compare)):
            say(_wrap(line))
        return True
    except (Quit, EOFError, KeyboardInterrupt):
        say("")
        return False
