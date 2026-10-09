#!/usr/bin/env python3
"""Start the Rates Trainer web application and open it in the browser. Standard library only, so it runs under any Python 3.9+ (the launcher uses the project's .venv).

    launch.py                 build the frontend if its sources changed, start `./trainer ui`, wait until it answers, open the browser, stay in the foreground
    launch.py --stop          stop this application's server (only one that identifies itself as the trainer, on the same data directory)
    launch.py --port 8800     a different preferred port (default 8765); RATES_TRAINER_PORT does the same

What it will not do: kill anything, delete or move any data, or reuse a server that is not this application on the same data directory.
The data directory is $RATES_TRAINER_HOME, else ~/.rates_trainer (the same rule as web/store.py).

Exit codes: 0 ok; 2 the setup is incomplete (virtualenv, npm, frontend); 3 the server did not start; 4 it started but never answered.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

APP = "rates-trainer"
DEFAULT_PORT = 8765
PORT_SPAN = 20                      # how many ports above the preferred one are tried when it is taken
STAMP = ".source-hash"
HOST = "127.0.0.1"
OK, SETUP, FAILED, TIMEOUT = 0, 2, 3, 4


def say(msg: str = "") -> None:
    print(msg, flush=True)


def data_dir() -> Path:
    return Path(os.environ.get("RATES_TRAINER_HOME") or Path.home() / ".rates_trainer")


def same_dir(a: str | Path, b: str | Path) -> bool:
    try:
        return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()
    except OSError:
        return str(a) == str(b)


# ------------------------------------------------------------------------------------------------------------- what is on a port

def probe(port: int, timeout: float = 1.0) -> dict:
    """{'state': 'free'} nothing listens | {'state': 'ours', 'data_dir', 'pid'} this application answers | {'state': 'other'} something else holds the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        if s.connect_ex((HOST, port)) != 0:
            return {"state": "free"}
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
        if isinstance(j, dict) and j.get("app") == APP:
            return {"state": "ours", "data_dir": str(j.get("data_dir", "")), "pid": j.get("pid")}
    except (OSError, ValueError):
        pass
    return {"state": "other"}


def who_holds(port: int) -> str:
    """Best-effort description of the process listening on a port (for the message only)."""
    lsof = shutil.which("lsof")
    if not lsof:
        return ""
    try:
        out = subprocess.run([lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return ""
    return out[1] if len(out) > 1 else ""


def choose(preferred: int, mine: Path, span: int = PORT_SPAN) -> tuple[str, int]:
    """('reuse', port) if this application already runs on the same data directory, else ('start', first free port). Explains every port it skips."""
    for port in range(preferred, preferred + span + 1):
        p = probe(port)
        if p["state"] == "free":
            if port != preferred:
                say(f"Using port {port} instead.")
            return "start", port
        if p["state"] == "ours" and same_dir(p["data_dir"], mine):
            return "reuse", port
        if p["state"] == "ours":
            say(f"Port {port} has another Rates Trainer server, using a different data directory ({p['data_dir']}). Leaving it alone.")
        else:
            held = who_holds(port)
            say(f"Port {port} is in use by something that is not Rates Trainer{': ' + held if held else ''}. Leaving it alone.")
    raise SystemExit(_fail(SETUP, f"No free port between {preferred} and {preferred + span}. Close what is using them, or choose another with --port."))


def _fail(code: int, msg: str) -> int:
    print(f"\nRates Trainer: {msg}", file=sys.stderr, flush=True)
    return code


# ------------------------------------------------------------------------------------------------------------- the frontend build

_SKIP_DIRS = {"__tests__", "fixtures", "node_modules"}


def source_hash(root: Path) -> str | None:
    """A hash of everything the build depends on (not the tests or fixtures); None when this checkout has no frontend sources."""
    fe = root / "frontend"
    if not (fe / "src").is_dir():
        return None
    files = [p for p in (fe / "src").rglob("*") if p.is_file() and not (set(p.relative_to(fe / "src").parts) & _SKIP_DIRS)
             and ".test." not in p.name and p.name != "test-setup.ts"]
    files += [fe / n for n in ("index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json") if (fe / n).is_file()]
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(str(p.relative_to(fe)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def static_dir(root: Path) -> Path:
    return root / "src" / "rates_trainer" / "web" / "static"


def needs_build(root: Path) -> bool:
    st = static_dir(root)
    if not (st / "index.html").is_file():
        return True
    want = source_hash(root)
    if want is None:
        return False                                              # no sources to build from: use what is there
    stamp = st / STAMP
    return not stamp.is_file() or stamp.read_text().strip() != want


def find_npm() -> str | None:
    extra = ["/opt/homebrew/bin", "/usr/local/bin"]
    path = os.pathsep.join([os.environ.get("PATH", ""), *extra])
    return shutil.which("npm", path=path)


def ensure_frontend(root: Path) -> int:
    if not needs_build(root):
        say("Frontend is up to date.")
        return OK
    st = static_dir(root)
    have = (st / "index.html").is_file()
    npm = find_npm()
    if npm is None:
        if have:
            say("The frontend sources changed, but npm was not found: using the existing build.")
            return OK
        return _fail(SETUP, "The frontend has not been built and npm was not found.\n  Install Node.js (https://nodejs.org), then run:  cd frontend && npm install && npm run build")
    fe = root / "frontend"
    env = {**os.environ, "PATH": os.pathsep.join([str(Path(npm).parent), os.environ.get("PATH", "")])}
    if not (fe / "node_modules").is_dir():
        say("Installing frontend packages (first run only)…")
        cmd = [npm, "ci" if (fe / "package-lock.json").is_file() else "install"]
        if subprocess.run(cmd, cwd=fe, env=env).returncode != 0:
            return _fail(SETUP, "npm could not install the frontend packages (see above).")
    say("Building the frontend (its sources changed)…")
    if subprocess.run([npm, "run", "build"], cwd=fe, env=env).returncode != 0:
        return _fail(SETUP, "The frontend build failed (see above).")
    if not (st / "index.html").is_file():
        return _fail(SETUP, f"The build finished but {st / 'index.html'} is missing.")
    want = source_hash(root)
    if want:
        (st / STAMP).write_text(want + "\n")
    return OK


# ------------------------------------------------------------------------------------------------------------- the server

def open_url(url: str) -> bool:
    """Open the default browser. RATES_TRAINER_OPEN names another command (used by the tests); on macOS this is `open`."""
    custom = os.environ.get("RATES_TRAINER_OPEN")
    try:
        if custom:
            return subprocess.run([*shlex.split(custom), url]).returncode == 0
        if sys.platform == "darwin":
            return subprocess.run(["open", url]).returncode == 0
        return bool(webbrowser.open(url))
    except OSError:
        return False


def open_browser(url: str) -> None:
    if not open_url(url):
        say(f"Could not open a browser automatically. Open this address yourself: {url}")


def wait_ready(proc: subprocess.Popen, port: int, mine: Path, timeout: float) -> int:
    """OK once the child answers /api/health as this application, on this data directory, with the child's own pid."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        code = proc.poll()
        if code is not None:
            return _fail(FAILED, f"The server stopped during startup (exit code {code}). Its messages are above.")
        p = probe(port, timeout=0.5)
        if p["state"] == "ours":
            if same_dir(p["data_dir"], mine) and p.get("pid") in (None, proc.pid):
                return OK
            return _fail(FAILED, f"Port {port} was taken by another Rates Trainer server while this one was starting. Run again.")
        time.sleep(0.2)
    return _fail(TIMEOUT, f"The server did not answer on port {port} within {timeout:g}s.")


def stop_child(proc: subprocess.Popen, grace: float = 8.0) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(grace)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)


def run_server(root: Path, port: int, mine: Path, timeout: float, browser: bool) -> int:
    url = f"http://{HOST}:{port}/"
    say(f"Starting the server on {url} …")
    proc = subprocess.Popen([sys.executable, str(root / "trainer"), "ui", "--port", str(port), "--no-browser"], cwd=root, stdin=subprocess.DEVNULL)

    def handler(signum, _frame):
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, handler)
    try:
        code = wait_ready(proc, port, mine, timeout)
        if code != OK:
            return code
        say(f"\nRates Trainer is running at {url}")
        say(f"Your data: {mine}")
        say("To stop it: press Ctrl-C in this window (or close the window).\n")
        if browser:
            open_browser(url)
        rc = proc.wait()
        return OK if rc in (0, -signal.SIGINT, -signal.SIGTERM) else _fail(FAILED, f"The server stopped unexpectedly (exit code {rc}).")
    except KeyboardInterrupt:
        say("\nStopping…")
        return OK
    finally:
        stop_child(proc)


def stop_servers(preferred: int, mine: Path) -> int:
    """SIGTERM to this application's server(s) on this data directory, identified by what they answer; anything else is left alone."""
    stopped = 0
    for port in range(preferred, preferred + PORT_SPAN + 1):
        p = probe(port, timeout=0.5)
        if p["state"] == "ours" and same_dir(p["data_dir"], mine) and isinstance(p.get("pid"), int):
            try:
                os.kill(p["pid"], signal.SIGTERM)
            except OSError as e:
                say(f"Could not stop the server on port {port} (pid {p['pid']}): {e}")
                continue
            say(f"Stopped the Rates Trainer server on port {port} (pid {p['pid']}).")
            stopped += 1
        elif p["state"] != "free":
            say(f"Port {port}: not this application on this data directory; left alone.")
    if not stopped:
        say("No Rates Trainer server is running on this data directory.")
    return OK


def check_environment(root: Path) -> int:
    missing = [m for m in ("uvicorn", "fastapi") if importlib.util.find_spec(m) is None]
    if missing:
        return _fail(SETUP, f"This Python ({sys.executable}) lacks {', '.join(missing)}.\n  In the project folder run:  python3 -m venv .venv && .venv/bin/pip install -e '.[ui]'")
    if not (root / "trainer").is_file():
        return _fail(SETUP, f"{root / 'trainer'} not found: is this the project folder?")
    return OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="launch.py", description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=int(os.environ.get("RATES_TRAINER_PORT") or DEFAULT_PORT))
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent, help="the project folder (default: this script's parent)")
    ap.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for the server to answer")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-build", action="store_true", help="never build the frontend (use what is there)")
    ap.add_argument("--stop", action="store_true", help="stop this application's server instead of starting one")
    a = ap.parse_args(argv)
    root, mine = a.root.resolve(), data_dir()

    if a.stop:
        return stop_servers(a.port, mine)
    say("Rates Trainer")
    code = check_environment(root)
    if code != OK:
        return code
    say(f"Project: {root}")
    say(f"Data:    {mine}  (existing sessions and practice history are used as they are)")
    action, port = choose(a.port, mine)
    if action == "reuse":
        say(f"Rates Trainer is already running on port {port} with this data: opening it.")
        if not a.no_browser:
            open_browser(f"http://{HOST}:{port}/")
        return OK
    if not a.no_build:
        code = ensure_frontend(root)
        if code != OK:
            return code
    elif not (static_dir(root) / "index.html").is_file():
        return _fail(SETUP, "The frontend has not been built (and --no-build was given).")
    return run_server(root, port, mine, a.timeout, not a.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
