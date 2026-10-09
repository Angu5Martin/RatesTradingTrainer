"""The local HTTP API. Every response is a plain-data view from episodes/api.Session or questions/api (no engine objects, no seeds, no hidden state).

    GET  /api/health                       {ok, app, data_dir, pid}: liveness and identity (used by the launcher)
    GET  /api/catalogue                    episodes and the question catalogue
    GET  /api/desk                         unfinished sessions in this server (to resume or delete), newest first
    DELETE /api/desk/{id}                  discard one unfinished session (409 if it is finished: finished episodes belong to Review)
    DELETE /api/desk                       discard every unfinished session
    POST /api/desk/start {level, seed?}    -> state
    GET  /api/desk/{id}[?transcript=true]   -> state (a reload lands on the pending result, never on the next observation)
    POST /api/desk/{id}/parse {text}       -> {ok, decision | error}   typed text / macro -> the decision the engine resolves it to
    POST /api/desk/{id}/submit {decision | text} -> {result, state}    commit; the result is held until Continue
    POST /api/desk/{id}/continue           -> state                    the next observation, only after the result has been seen
    GET  /api/desk/{id}/debrief?compare=   -> DebriefView              only after the last result has been continued past
    GET  /api/desk/{id}/record             -> replay record            same condition
    GET  /api/review/sessions              -> finished episodes saved locally

TRAIN (question practice; the Live Desk's episode machinery is not involved):
    POST /api/train/start {tracks?, skills?, difficulty?, max_difficulty?, kind?, count?, seed?} | {template_id, seed?} | {ids: [..]}  -> state
    GET  /api/train/{id}                   -> state (a reload lands on the same part, and on its result if it has been answered)
    POST /api/train/{id}/check {text}      -> {ok, read_as | error}        can this be read? nothing is graded or recorded
    POST /api/train/{id}/answer {text} | {skip: true}  -> {result, state}  400 if unreadable (not marked), 409 if nothing is being asked
    POST /api/train/{id}/continue          -> state                        the next part or question, only after the result
    POST /api/train/{id}/finish            -> summary                      end now; what was answered stays recorded
    GET  /api/train/{id}/summary           -> summary
    GET  /api/train/history                -> saved practice sessions (for Review)

state = {id, phase: awaiting | settled | done, episode, observation | null, pending: {observation, decision, result} | null}.
The live desk runs sessions with reveal_inference=False: the model's P(informed) is not in any result (it is in the debrief).
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..episodes.api import Session, catalogue as episode_catalogue, episode_for_level
from ..episodes.serial import decode_decision, encode_decision
from ..questions.api import QuestionSession, catalogue as question_catalogue
from . import store

MAX_SESSIONS = 20


class StartBody(BaseModel):
    level: int
    seed: int | None = None


class ParseBody(BaseModel):
    text: str


class SubmitBody(BaseModel):
    decision: dict | None = None
    text: str | None = None


class TrainStartBody(BaseModel):
    tracks: list[str] = []
    skills: list[str] = []
    difficulty: int | None = None
    max_difficulty: int | None = None
    kind: str | None = None
    count: int = 10
    seed: int | None = None
    template_id: str | None = None
    ids: list[str] | None = None
    label: str | None = None


class TrainAnswerBody(BaseModel):
    text: str = ""
    skip: bool = False


class TrainCheckBody(BaseModel):
    text: str


@dataclass
class Practice:
    id: str
    session: QuestionSession
    lock: threading.Lock = field(default_factory=threading.Lock)

    def state(self) -> dict:
        return {"id": self.id, **self.session.state()}

    def save(self) -> None:
        store.save_practice(self.id, self.session.record(self.id))


@dataclass
class Desk:
    id: str
    session: Session
    lock: threading.Lock = field(default_factory=threading.Lock)
    observation: dict | None = None            # the current prompt (None while a result is pending or when done)
    pending: dict | None = None                # {observation, decision, result}: shown until Continue
    transcript: list = field(default_factory=list)
    debrief_basic: dict | None = None
    debrief_full: dict | None = None
    saved: bool = False
    started: float = field(default_factory=time.time)

    @property
    def phase(self) -> str:
        if self.pending is not None:
            return "settled"
        return "done" if self.session.done else "awaiting"

    def state(self, with_transcript: bool = False) -> dict:
        obs = self.observation or (self.pending["observation"] if self.pending else None)
        ep = (obs or {}).get("episode") or self.transcript[0]["observation"]["episode"]
        out = {"id": self.id, "phase": self.phase, "episode": ep, "observation": self.observation, "pending": self.pending}
        if with_transcript:                      # what the trainee has already been shown, to rebuild the tape and the curve history on resume
            out["transcript"] = self.transcript
        return out


def create_app(static_dir: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="Rates trainer", docs_url=None, redoc_url=None)
    desks: dict[str, Desk] = {}
    practices: dict[str, Practice] = {}
    registry_lock = threading.Lock()
    threading.Thread(target=question_catalogue, daemon=True).start()          # the first catalogue call generates each source once; do it now

    def get_practice(pid: str) -> Practice:
        try:
            return practices[pid]
        except KeyError:
            raise HTTPException(404, "unknown practice session") from None

    def get(desk_id: str) -> Desk:
        try:
            return desks[desk_id]
        except KeyError:
            raise HTTPException(404, "unknown session") from None

    @app.get("/api/health")
    def health():
        """Liveness, and who is answering: the launcher reuses a running server only if it is this application, on the same data directory."""
        return {"ok": True, "app": "rates-trainer", "data_dir": str(store.home()), "pid": os.getpid()}

    @app.get("/api/catalogue")
    def catalogue():
        return {"episodes": episode_catalogue(), "train": question_catalogue()}

    @app.get("/api/desk")
    def list_desks():
        """What a trainee needs to recognise a session: level, round, where it stands and when it was started. Never the seed (it names the market path)."""
        with registry_lock:
            live = [d for d in desks.values() if d.phase != "done"]
        out = []
        for d in live:
            with d.lock:
                out.append({"id": d.id, "phase": d.phase, "episode": d.state()["episode"], "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(d.started)),
                            "decisions": len(d.transcript), "in_history": d.saved})
        return out[::-1]

    @app.delete("/api/desk/{desk_id}")
    def discard(desk_id: str):
        """Forget an unfinished session. Nothing is submitted, continued or revealed; the session simply stops existing (GET then answers 404).
        An episode whose last result is still waiting has already been saved for Review; that saved file is left alone."""
        d = get(desk_id)
        with d.lock:                                  # waits for a commit in flight, so a delete never lands between a decision and its result
            if d.phase == "done":
                raise HTTPException(409, "this episode is finished: it is kept for Review")
            with registry_lock:
                desks.pop(desk_id, None)
        return {"deleted": desk_id}

    @app.delete("/api/desk")
    def discard_all():
        with registry_lock:
            ids = [i for i, d in desks.items() if d.phase != "done"]
        gone = []
        for i in ids:
            d = desks.get(i)
            if d is None:
                continue
            with d.lock:
                if d.phase != "done":
                    with registry_lock:
                        desks.pop(i, None)
                    gone.append(i)
        return {"deleted": gone}

    @app.post("/api/desk/start")
    def start(body: StartBody):
        try:
            seed = body.seed if body.seed is not None else secrets.randbelow(1_000_000)
            sess = Session.start(episode_for_level(body.level, seed), seed, reveal_inference=False)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        desk = Desk(secrets.token_hex(8), sess)
        desk.observation = sess.observe()
        with registry_lock:
            desks[desk.id] = desk
            while len(desks) > MAX_SESSIONS:                       # forget the oldest sessions (finished ones are already saved)
                desks.pop(next(iter(desks)))
        return desk.state()

    @app.get("/api/desk/{desk_id}")
    def state(desk_id: str, transcript: bool = False):
        d = get(desk_id)
        with d.lock:
            return d.state(transcript)

    @app.post("/api/desk/{desk_id}/parse")
    def parse(desk_id: str, body: ParseBody):
        d = get(desk_id)
        with d.lock:
            if d.phase != "awaiting":
                raise HTTPException(409, "nothing to enter now")
            try:
                return {"ok": True, "decision": encode_decision(d.session.parse(body.text))}
            except (ValueError, KeyError) as e:
                return {"ok": False, "error": str(e).strip("'\"")}

    @app.post("/api/desk/{desk_id}/submit")
    def submit(desk_id: str, body: SubmitBody):
        d = get(desk_id)
        with d.lock:
            if d.phase != "awaiting":
                raise HTTPException(409, "a decision is not being asked for now")
            try:
                decision = decode_decision(body.decision) if body.decision is not None else d.session.parse(body.text or "")
                observed = d.observation
                result = d.session.submit(decision)
            except (ValueError, KeyError, TypeError) as e:
                raise HTTPException(400, str(e).strip("'\"")) from None
            d.pending = {"observation": observed, "decision": encode_decision(decision), "result": result}
            d.observation = None
            d.transcript.append(d.pending)
            if d.session.done and not d.saved:
                d.debrief_basic = d.session.debrief(compare=False)
                rec = d.session.record()
                first = d.transcript[0]["observation"]
                store.save_episode(d.id, rec, d.transcript, store.summarise(first, d.transcript, d.debrief_basic), d.debrief_basic)
                d.saved = True
            return {"result": result, "state": d.state()}

    @app.post("/api/desk/{desk_id}/continue")
    def cont(desk_id: str):
        d = get(desk_id)
        with d.lock:
            if d.pending is None:
                raise HTTPException(409, "no result is waiting")
            d.pending = None
            d.observation = None if d.session.done else d.session.observe()
            return d.state()

    @app.get("/api/desk/{desk_id}/debrief")
    def debrief(desk_id: str, compare: bool = False):
        d = get(desk_id)
        with d.lock:
            if d.phase != "done":
                raise HTTPException(409, "the debrief opens after the last result")
            if not compare:
                return d.debrief_basic
            if d.debrief_full is None:
                d.debrief_full = d.session.debrief(compare=True)
            return d.debrief_full

    @app.get("/api/desk/{desk_id}/record")
    def record(desk_id: str):
        d = get(desk_id)
        with d.lock:
            if d.phase != "done":
                raise HTTPException(409, "the replay record names the seeds: available when the episode is over")
            return d.session.record()

    @app.post("/api/train/start")
    def train_start(body: TrainStartBody):
        try:
            if body.ids:
                sess = QuestionSession.replay(body.ids, body.label or "Replay")
            elif body.template_id:
                sess = QuestionSession.single(body.template_id, body.seed)
            else:
                sess = QuestionSession.start(tracks=body.tracks, skills=body.skills, difficulty=body.difficulty, max_difficulty=body.max_difficulty,
                                             kind=body.kind, count=body.count, seed=body.seed)
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e).strip("'\"")) from None
        p = Practice(secrets.token_hex(8), sess)
        with registry_lock:
            practices[p.id] = p
            while len(practices) > MAX_SESSIONS:
                practices.pop(next(iter(practices)))
        return p.state()

    @app.get("/api/train/history")
    def train_history():
        return store.list_practice()

    @app.get("/api/train/{pid}")
    def train_state(pid: str):
        p = get_practice(pid)
        with p.lock:
            return p.state()

    @app.post("/api/train/{pid}/check")
    def train_check(pid: str, body: TrainCheckBody):
        p = get_practice(pid)
        with p.lock:
            try:
                return p.session.check(body.text)
            except PermissionError as e:
                raise HTTPException(409, str(e)) from None

    @app.post("/api/train/{pid}/answer")
    def train_answer(pid: str, body: TrainAnswerBody):
        p = get_practice(pid)
        with p.lock:
            try:
                result = p.session.skip() if body.skip else p.session.submit(body.text)
            except PermissionError as e:
                raise HTTPException(409, str(e)) from None
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
            p.save()
            return {"result": result, "state": p.state()}

    @app.post("/api/train/{pid}/continue")
    def train_continue(pid: str):
        p = get_practice(pid)
        with p.lock:
            try:
                p.session.next()
            except PermissionError as e:
                raise HTTPException(409, str(e)) from None
            if p.session.done:
                p.save()
            return p.state()

    @app.post("/api/train/{pid}/finish")
    def train_finish(pid: str):
        p = get_practice(pid)
        with p.lock:
            p.session.finish()
            if p.session.summary()["parts_total"]:
                p.save()
            return p.session.summary()

    @app.get("/api/train/{pid}/summary")
    def train_summary(pid: str):
        p = get_practice(pid)
        with p.lock:
            return p.session.summary()

    @app.get("/api/review/sessions")
    def review_sessions():
        return store.list_episodes()

    if static_dir and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    return app


def default_static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


app = create_app(default_static_dir())
