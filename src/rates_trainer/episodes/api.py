"""The frontend boundary: a Session wraps one Episode and speaks only plain data.

    sess = Session.start("mm.ep5_information_views", seed=7)        # or Session.for_level(5, seed) / Session.replay(record)
    while not sess.done:
        view = sess.observe()                    # ObservationView: what the trainee may know and what is asked (views.py)
        decision = sess.parse(text)              # typed text -> decision (ValueError/KeyError with a readable message if not understood)
        result = sess.submit(decision)           # or sess.submit(text): StepResultView (events, assessment, grade, done)
    report = sess.debrief()                      # DebriefView: decisions, outcome, luck, clients, same-path policies, level-5 market paths
    record = sess.record()                       # the replay record (JSON-ready)

Nothing returned here is an engine object: no context, no Episode, no hidden state. The terminal renders these dicts with render.py; a graphical
frontend renders the same dicts its own way.

REPLAY FORMAT (version 1), JSON:
    {"format": "rates-trainer-episode-replay", "version": 1, "episode": "<episode id>", "seed": <int>, "market_seed": <int or null>,
     "decisions": [<encoded decision>, ...], "complete": <bool>}
An encoded decision is serial.encode_decision's dict: {"type": "quote", "bid", "offer"} | {"type": "rfq", "level": rate or null} |
{"type": "checkpoint", "raw"} | {"type": "hedge", "label", "trades": [{"kind": "swap", "tenor", "side", "notional"} |
{"kind": "future", "code", "contracts"} | {"kind": "bond", "code", "face"}]}, one per prompt in the order asked. The episode id and the two seeds
fix the clients, fills and market (four independent seeded streams, drawn before any decision), so replaying the same decisions reproduces the
episode exactly, in any process (tested across processes with different hash seeds). The record names the seeds that generate the hidden
market and clients: keep it server-side until the episode is finished.
"""

from __future__ import annotations

from .decisions import parse as _parse
from .episode import Episode, all_episodes
from .serial import decode_decision, encode_decision
from .state import CheckpointAnswer, HedgeDecision, QuoteDecision, RFQDecision
from .views import step_result_view

REPLAY_FORMAT = "rates-trainer-episode-replay"
REPLAY_VERSION = 1

_EXPECTED = {"quote": QuoteDecision, "rfq": RFQDecision, "checkpoint": CheckpointAnswer}


def catalogue() -> list[dict]:
    """The playable episodes: id, level, skill and title."""
    return [{"id": e.id, "level": e.level, "skill": e.skill, "title": e.title} for e in all_episodes()]


def episode_for_level(level: int, seed: int) -> str:
    """The episode a level plays for a seed (level 3 has two variants, chosen by seed)."""
    variants = [e for e in all_episodes() if e.level == level]
    if not variants:
        raise ValueError(f"no episode at level {level}")
    return variants[seed % len(variants)].id


class Session:
    def __init__(self, episode_id: str, seed: int, market_seed: int | None = None, reveal_inference: bool = True):
        self._reveal = reveal_inference          # False on the live desk: the model's P(informed) is left out of results (it stays in the debrief)
        self._ep = Episode(episode_id, seed, market_seed)
        self._id, self._seed, self._market_seed = episode_id, seed, market_seed
        self._log: list[dict] = []
        self._obs = None

    # ---- construction
    @classmethod
    def start(cls, episode_id: str, seed: int, market_seed: int | None = None, reveal_inference: bool = True) -> "Session":
        return cls(episode_id, seed, market_seed, reveal_inference)

    @classmethod
    def for_level(cls, level: int, seed: int, market_seed: int | None = None, reveal_inference: bool = True) -> "Session":
        return cls(episode_for_level(level, seed), seed, market_seed, reveal_inference)

    @classmethod
    def replay(cls, record: dict, upto: int | None = None, reveal_inference: bool = True) -> "Session":
        """Rebuild a session from a replay record (optionally only its first `upto` decisions)."""
        if record.get("format") != REPLAY_FORMAT or record.get("version") != REPLAY_VERSION:
            raise ValueError(f"not a version {REPLAY_VERSION} {REPLAY_FORMAT!r} record")
        s = cls(record["episode"], int(record["seed"]), record.get("market_seed"), reveal_inference)
        for enc in record["decisions"][:upto]:
            s.submit(enc)
        return s

    @classmethod
    def from_episode(cls, episode: Episode) -> "Session":
        """Wrap an Episode that has not been played yet (used by the terminal adapter and tests)."""
        s = cls.__new__(cls)
        s._ep, s._id, s._seed, s._market_seed, s._log, s._obs, s._reveal = episode, episode.spec.id, episode.seed, episode.market_seed, [], None, True
        return s

    # ---- the loop
    @property
    def done(self) -> bool:
        return self._ep.done

    def observe(self) -> dict:
        """ObservationView for the current decision."""
        return self._current().view

    def parse(self, text: str):
        """Typed text -> decision for the current prompt. Raises ValueError/KeyError with a readable message."""
        return _parse(self._current(), text)

    def submit(self, decision) -> dict:
        """Commit a decision (an object, its encoded dict, or typed text). Returns a StepResultView."""
        obs = self._current()
        if isinstance(decision, str):
            decision = _parse(obs, decision)
        elif isinstance(decision, dict):
            decision = decode_decision(decision)
        want = _EXPECTED.get(obs.kind, HedgeDecision)
        if not isinstance(decision, want):
            raise ValueError(f"this prompt ({obs.kind}) needs a {want.__name__}, got {type(decision).__name__}")
        enc = encode_decision(decision)
        res = self._ep.submit(decision)
        self._log.append(enc)
        self._obs = None
        return step_result_view(res.events, res.assessment, res.grade, self._ep.done, self._reveal)

    def debrief(self, compare: bool = True) -> dict:
        """DebriefView (after the episode is finished)."""
        return self._ep.debrief_view(compare)

    def record(self) -> dict:
        """The replay record so far (see the module docstring)."""
        return {"format": REPLAY_FORMAT, "version": REPLAY_VERSION, "episode": self._id, "seed": self._seed, "market_seed": self._market_seed,
                "decisions": list(self._log), "complete": self._ep.done}

    # ---- internals
    def _current(self):
        if self._obs is None:
            self._obs = self._ep.observe()
        return self._obs
