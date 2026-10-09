"""Dump real episode transcripts (public views only) as JSON fixtures for the frontend's tests and stories.

    .venv/bin/python scripts/dump_fixtures.py

Each fixture is a real Session played with the reference policy: {steps: [{observation, decision, result}], debrief, debrief_full}.
The browser's types and component tests are built from these, so the UI cannot drift from the Python contract without a test failing.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from rates_trainer.episodes.api import Session, episode_for_level  # noqa: E402
from rates_trainer.episodes.episode import reference_decision  # noqa: E402
from rates_trainer.episodes.serial import encode_decision  # noqa: E402
from rates_trainer.questions.model import ChoicePart  # noqa: E402
from rates_trainer.questions.practice import QuestionSession  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "fixtures"
CASES = {"l1_seed3": (1, 3), "l1_seed1": (1, 1), "l2_seed3": (2, 3), "l2_seed5": (2, 5),
         "l3_seed1": (3, 1), "l3_seed2": (3, 2), "l4_seed1": (4, 1), "l5_seed1": (5, 1), "l5_seed2": (5, 2)}


def _scripted(level: int, seed: int, texts: dict[str, list[str]]) -> dict:
    """A real session in which the hedge-like prompts (hedge, overnight, rehedge, position) are answered with typed text, in order per kind, and the rest by the
    reference policy: covers futures, the bond, switch and target, which the reference policy never uses."""
    s = Session.start(episode_for_level(level, seed), seed, reveal_inference=False)
    steps, used = [], {}
    while not s.done:
        obs = s.observe()
        k = obs["kind"]
        if k in texts:
            i = used.get(k, 0)
            used[k] = i + 1
            dec = encode_decision(s.parse(texts[k][min(i, len(texts[k]) - 1)]))
        else:
            dec = encode_decision(reference_decision(s._ep, s._current()))
        steps.append({"observation": obs, "decision": dec, "result": s.submit(dec)})
    return {"steps": steps, "debrief": s.debrief(compare=False), "debrief_full": s.debrief(compare=True)}


def _train(sess: QuestionSession, answers) -> dict:
    """Walk a QuestionSession with answers(part_index, part) -> raw | None (None = skip); keeps every public view it returned."""
    steps = []
    start = {"id": "fx", **sess.state()}
    n = 0
    while not sess.done:
        q = sess._q(sess._qi)
        part = q.parts[sess._part_index()]
        raw = answers(n, part)
        result = sess.skip() if raw is None else sess.submit(raw)
        after = {"id": "fx", **sess.state()}
        sess.next()
        steps.append({"answer": raw, "result": result, "after": after, "next": {"id": "fx", **sess.state()}})
        n += 1
    return {"start": start, "steps": steps, "summary": sess.summary()}


def _ref(part) -> str:
    return chr(65 + part.correct) if isinstance(part, ChoicePart) else repr(part.answer)


def train_fixtures() -> None:
    def multi(n, part):                      # right, right size but wrong sign, skipped
        return [_ref(part), repr(-part.answer) if not isinstance(part, ChoicePart) else _ref(part), None][n]

    def focus(n, part):                      # right, then a wrong option
        return _ref(part) if n == 0 else chr(65 + (part.correct + 1) % len(part.options))

    cases = {"train_multi": _train(QuestionSession.single("basis.irs_vs_ois", 1), multi),
             "train_focus": _train(QuestionSession.start(skills=["swaps.dv01"], kind="conceptual", count=2, seed=1), focus)}
    from rates_trainer.questions.api import catalogue
    cases["train_catalogue"] = catalogue()
    for name, fx in cases.items():
        (OUT / f"{name}.json").write_text(json.dumps(fx, indent=1))
        print(name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (level, seed) in CASES.items():
        s = Session.start(episode_for_level(level, seed), seed, reveal_inference=False)
        steps = []
        while not s.done:
            obs = s.observe()
            dec = encode_decision(reference_decision(s._ep, s._current()))
            steps.append({"observation": obs, "decision": dec, "result": s.submit(dec)})
        (OUT / f"{name}.json").write_text(json.dumps({"steps": steps, "debrief": s.debrief(compare=False), "debrief_full": s.debrief(compare=True)}, indent=1))
        print(name, len(steps), "steps")
    scripted = {"l4_products": _scripted(4, 1, {"hedge": ["sell 5000 fgbm", "sell 40m ctd"], "overnight": ["none"], "rehedge": ["switch"]}),
                "l5_position": _scripted(5, 1, {"position": ["target 150k"], "hedge": ["none"]})}
    for name, fx in scripted.items():
        (OUT / f"{name}.json").write_text(json.dumps(fx, indent=1))
        print(name, len(fx["steps"]), "steps")
    train_fixtures()


if __name__ == "__main__":
    main()
