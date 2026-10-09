import random

from rates_trainer.cli import main
from rates_trainer.questions.model import ChoicePart
from rates_trainer.questions.registry import all_specs, generate, select
from rates_trainer.session import build_queue, print_summary, run_session


def scripted(answers):
    it = iter(answers)
    return lambda prompt: next(it)


def solve_all(q):
    out = []
    for p in q.parts:
        out.append(chr(65 + p.correct) if isinstance(p, ChoicePart) else repr(p.answer))
    return out


def test_perfect_run_scores_full_marks():
    qs = [generate(s.id, 3) for s in all_specs()]
    lines = []
    res = run_session(qs, ask=scripted(sum((solve_all(q) for q in qs), [])), say=lines.append)
    assert res.parts_correct == res.parts_total > 0 and not res.missed and not res.quit_early
    assert any("Worked solution" in l for l in lines)


def test_wrong_skip_quit_and_input_errors():
    q = generate("swaps.dv01_pnl", 1)
    res = run_session([q], ask=scripted(["banana", "skip", "0"]), say=lambda s: None)
    # 'banana' is re-prompted without penalty; skip scores a miss; '0' is a wrong answer
    assert res.parts_total == 2 and res.parts_correct == 0 and res.missed == [q.id]
    res = run_session([q, q], ask=scripted(["q"]), say=lambda s: None)
    assert res.quit_early and res.parts_total == 0


def test_build_queue_has_no_immediate_repeats_and_is_seeded():
    specs = select(all_specs(), tracks={"mm"})
    q1 = build_queue(specs, 12, random.Random(5))
    q2 = build_queue(specs, 12, random.Random(5))
    assert [q.id for q in q1] == [q.id for q in q2]
    assert all(a.template_id != b.template_id for a, b in zip(q1, q1[1:]))


def test_cli_list_and_filters(capsys, monkeypatch):
    from rates_trainer.curriculum.skills import SKILLS, Skill
    monkeypatch.setitem(SKILLS, "math.roadmap_only", Skill("math.roadmap_only", "math", "A skill on the roadmap with no questions yet", (), True))
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "mm.client_trade" in out and "math.roadmap_only" in out and "planned" in out
    assert main(["--skill", "nonexistent.skill"]) == 2


def test_cli_replay_runs_end_to_end(monkeypatch, capsys):
    q = generate("mm.client_trade_risk", 11)
    monkeypatch.setattr("builtins.input", scripted(solve_all(q)))
    assert main(["--replay", q.id]) == 0
    assert "6/6" in capsys.readouterr().out


def test_summary_mentions_replay_for_misses(capsys):
    q = generate("swaps.dv01_pnl", 2)
    res = run_session([q], ask=scripted(["skip", "skip"]), say=lambda s: None)
    print_summary(res)
    assert f"--replay {q.id}" in capsys.readouterr().out
