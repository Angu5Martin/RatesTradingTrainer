"""The macOS launcher: scripts/launch.py (readiness, reuse, occupied ports, build-when-needed, errors, stop), the double-click wrapper and the Desktop installer.

Everything runs against temporary data directories and free ports, with a stand-in for `open` that only writes the URL to a file: no test touches the real trainer data
(~/.rates_trainer), opens a real browser, or kills a process it did not start.
"""

import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "scripts" / "launch.py"
spec = importlib.util.spec_from_file_location("launch", LAUNCH)
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)


# ------------------------------------------------------------------------------------------------------------------------ helpers

def free_port(consecutive: int = 1) -> int:
    for _ in range(200):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
        if all(launch.probe(p + i, 0.2)["state"] == "free" for i in range(consecutive)):
            return p
    raise RuntimeError("no free ports")


def wait_for(pred, timeout=60.0, every=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = pred()
        if v:
            return v
        time.sleep(every)
    return None


def env_for(home: Path, **extra) -> dict:
    e = {k: v for k, v in os.environ.items() if k not in ("RATES_TRAINER_PORT", "RATES_TRAINER_OPEN")}
    e["RATES_TRAINER_HOME"] = str(home)
    e.update(extra)
    return e


def start_app(port: int, home: Path) -> subprocess.Popen:
    p = subprocess.Popen([sys.executable, str(ROOT / "trainer"), "ui", "--port", str(port), "--no-browser"], env=env_for(home),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    assert wait_for(lambda: launch.probe(port, 0.3)["state"] == "ours"), "the application did not start"
    return p


def stop(p: subprocess.Popen):
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()


def opener(tmp: Path) -> tuple[str, Path]:
    """A stand-in for `open`: appends the URL it is given to a file."""
    log = tmp / "opened.log"
    script = tmp / "fake-open.sh"
    script.write_text(f'#!/bin/sh\necho "$1" >> "{log}"\n')
    script.chmod(0o755)
    return str(script), log


def run_launcher(args, home, tmp, **extra):
    cmd, log = opener(tmp)
    p = subprocess.Popen([sys.executable, str(LAUNCH), *args], env=env_for(home, RATES_TRAINER_OPEN=cmd, **extra), stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return p, log


def finish(p: subprocess.Popen, timeout=30) -> tuple[int, str]:
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        out, _ = p.communicate()
        pytest.fail("the launcher did not finish:\n" + out)
    return p.returncode, out


def opened(log: Path) -> list[str]:
    return log.read_text().split() if log.exists() else []


@pytest.fixture()
def home(tmp_path):
    h = tmp_path / "data"
    h.mkdir()
    return h


@pytest.fixture()
def app(home):
    port = free_port()
    p = start_app(port, home)
    yield port, p
    stop(p)


@pytest.fixture()
def foreign():
    """Something that is not Rates Trainer holding a port."""
    port = free_port()
    p = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert wait_for(lambda: launch.probe(port, 0.3)["state"] != "free")
    yield port, p
    stop(p)


# ------------------------------------------------------------------------------------------------------------------------ identity and the data directory

def test_the_health_answer_identifies_the_application_its_data_directory_and_process(app, home):
    port, p = app
    j = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5).read())
    assert j == {"ok": True, "app": "rates-trainer", "data_dir": str(home), "pid": p.pid}
    assert launch.probe(port) == {"state": "ours", "data_dir": str(home), "pid": p.pid}


def test_probe_tells_a_free_port_from_a_foreign_server(foreign):
    port, _ = foreign
    assert launch.probe(port)["state"] == "other"
    assert launch.probe(free_port())["state"] == "free"


def test_the_launchers_data_directory_is_the_applications(monkeypatch, tmp_path):
    from rates_trainer.web import store
    monkeypatch.setenv("RATES_TRAINER_HOME", str(tmp_path / "x"))
    assert launch.data_dir() == store.home()
    monkeypatch.delenv("RATES_TRAINER_HOME")
    assert launch.data_dir() == store.home() == Path.home() / ".rates_trainer"


def test_the_test_suite_never_points_at_the_real_data_directory():
    assert Path(os.environ["RATES_TRAINER_HOME"]) != Path.home() / ".rates_trainer"


# ------------------------------------------------------------------------------------------------------------------------ choosing a port

def test_a_free_preferred_port_is_started_on(home):
    p = free_port()
    assert launch.choose(p, home) == ("start", p)


def test_this_application_on_the_same_data_is_reused(app, home):
    port, _ = app
    assert launch.choose(port, home) == ("reuse", port)
    assert launch.choose(port, Path(str(home) + "/../data")) == ("reuse", port)     # the same directory by another spelling


def test_a_foreign_server_is_skipped_never_touched_and_explained(foreign, home, capsys):
    port, proc = foreign
    action, chosen = launch.choose(port, home)
    assert action == "start" and chosen != port and launch.probe(chosen)["state"] == "free"
    assert "not Rates Trainer" in capsys.readouterr().out
    assert proc.poll() is None and launch.probe(port)["state"] == "other"


def test_a_trainer_on_other_data_is_not_reused(app, tmp_path, capsys):
    port, p = app
    action, chosen = launch.choose(port, tmp_path / "somewhere else")
    assert action == "start" and chosen != port
    assert "different data directory" in capsys.readouterr().out
    assert p.poll() is None


def test_after_a_fallback_the_next_launch_finds_and_reuses_its_own_server(home):
    base = free_port(2)
    occupant = subprocess.Popen([sys.executable, "-m", "http.server", str(base), "--bind", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert wait_for(lambda: launch.probe(base, 0.3)["state"] != "free")
        own = start_app(base + 1, home)                      # where an earlier launch fell back to
        try:
            assert launch.choose(base, home) == ("reuse", base + 1)
        finally:
            stop(own)
    finally:
        stop(occupant)


# ------------------------------------------------------------------------------------------------------------------------ the whole launch

def test_launch_waits_for_readiness_then_opens_the_browser_and_stops_cleanly(home, tmp_path):
    port = free_port()
    p, log = run_launcher(["--port", str(port), "--no-build"], home, tmp_path)
    try:
        urls = wait_for(lambda: opened(log), 90)
        assert urls == [f"http://127.0.0.1:{port}/"]
        h = launch.probe(port)                                              # the browser was opened only once the server answered
        assert h["state"] == "ours" and h["data_dir"] == str(home)
    finally:
        p.send_signal(signal.SIGINT)
    code, out = finish(p)
    assert code == 0 and f"running at http://127.0.0.1:{port}/" in out and str(home) in out and "Ctrl-C" in out
    assert wait_for(lambda: launch.probe(port, 0.2)["state"] == "free", 15), "the server was left running"
    assert opened(log) == [f"http://127.0.0.1:{port}/"]


def test_launching_again_reuses_the_running_server_without_starting_another(app, home, tmp_path):
    port, proc = app
    p, log = run_launcher(["--port", str(port), "--no-build"], home, tmp_path)
    code, out = finish(p, 30)
    assert code == 0 and "already running" in out
    assert opened(log) == [f"http://127.0.0.1:{port}/"]
    assert launch.probe(port)["pid"] == proc.pid and launch.probe(port + 1)["state"] == "free"


def test_an_occupied_port_gets_a_different_one_and_the_occupant_is_left_alone(foreign, home, tmp_path):
    port, occupant = foreign
    p, log = run_launcher(["--port", str(port), "--no-build"], home, tmp_path)
    try:
        urls = wait_for(lambda: opened(log), 90)
        assert urls and urls[0] != f"http://127.0.0.1:{port}/"
        assert launch.probe(port)["state"] == "other" and occupant.poll() is None
    finally:
        p.send_signal(signal.SIGINT)
    code, out = finish(p)
    assert code == 0 and "Leaving it alone" in out


def test_another_trainer_on_other_data_is_not_borrowed(app, tmp_path):
    port, other = app
    mine = tmp_path / "mine"
    mine.mkdir()
    p, log = run_launcher(["--port", str(port), "--no-build"], mine, tmp_path)
    try:
        urls = wait_for(lambda: opened(log), 90)
        assert urls and not urls[0].endswith(f":{port}/")
        new_port = int(urls[0].rsplit(":", 1)[1].strip("/"))
        assert launch.probe(new_port)["data_dir"] == str(mine) and launch.probe(port)["pid"] == other.pid
    finally:
        p.send_signal(signal.SIGINT)
    assert finish(p)[0] == 0


# ------------------------------------------------------------------------------------------------------------------------ errors

def fake_project(tmp_path: Path, trainer_body: str, static: bool = True) -> Path:
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    (root / "trainer").write_text(trainer_body)
    if static:
        (root / "src/rates_trainer/web/static").mkdir(parents=True)
        (root / "src/rates_trainer/web/static/index.html").write_text("<html></html>")
    return root


def test_a_server_that_dies_during_startup_is_reported_with_its_exit_code(home, tmp_path):
    root = fake_project(tmp_path, 'import sys\nprint("boom: cannot bind", file=sys.stderr)\nsys.exit(3)\n')
    p, log = run_launcher(["--root", str(root), "--port", str(free_port()), "--no-build"], home, tmp_path)
    code, out = finish(p)
    assert code == launch.FAILED and "boom: cannot bind" in out and "stopped during startup (exit code 3)" in out
    assert opened(log) == []


def test_a_server_that_never_answers_times_out_and_is_not_left_behind(home, tmp_path):
    pidfile = tmp_path / "child.pid"
    root = fake_project(tmp_path, f'import os, time\nopen({str(pidfile)!r}, "w").write(str(os.getpid()))\ntime.sleep(60)\n')
    p, log = run_launcher(["--root", str(root), "--port", str(free_port()), "--no-build", "--timeout", "1.5"], home, tmp_path)
    code, out = finish(p)
    assert code == launch.TIMEOUT and "did not answer" in out and opened(log) == []
    pid = int(pidfile.read_text())
    assert wait_for(lambda: not _alive(pid), 10), "the child server was left running"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_an_unbuilt_frontend_with_no_build_flag_is_a_clear_setup_error(home, tmp_path):
    root = fake_project(tmp_path, "", static=False)
    p, _ = run_launcher(["--root", str(root), "--port", str(free_port()), "--no-build"], home, tmp_path)
    code, out = finish(p)
    assert code == launch.SETUP and "frontend has not been built" in out


def test_a_missing_project_file_is_a_setup_error(home, tmp_path):
    p, _ = run_launcher(["--root", str(tmp_path), "--port", str(free_port())], home, tmp_path)
    code, out = finish(p)
    assert code == launch.SETUP and "not found" in out


# ------------------------------------------------------------------------------------------------------------------------ building the frontend only when needed

def frontend_tree(tmp_path: Path) -> Path:
    root = tmp_path / "fe"
    fe = root / "frontend"
    (fe / "src/__tests__").mkdir(parents=True)
    (fe / "src/fixtures").mkdir()
    (fe / "src/app.tsx").write_text("export const a = 1;\n")
    (fe / "src/__tests__/a.test.ts").write_text("test\n")
    (fe / "src/fixtures/f.json").write_text("{}")
    for n in ("index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"):
        (fe / n).write_text(n)
    return root


def fake_npm(tmp_path: Path, root: Path, fail_on: str | None = None) -> tuple[str, Path]:
    log = tmp_path / "npm.log"
    st = launch.static_dir(root)
    script = tmp_path / "npm"
    script.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n'
                      + (f'[ "$1 $2" = "{fail_on}" ] && exit 1\n' if fail_on else "")
                      + f'if [ "$1" = "run" ]; then mkdir -p "{st}" && echo built > "{st}/index.html"; fi\n'
                      + f'if [ "$1" = "ci" ] || [ "$1" = "install" ]; then mkdir -p "{root}/frontend/node_modules"; fi\n')
    script.chmod(0o755)
    return str(script), log


def test_the_frontend_is_built_when_missing_or_changed_and_not_otherwise(tmp_path, monkeypatch):
    root = frontend_tree(tmp_path)
    npm, log = fake_npm(tmp_path, root)
    monkeypatch.setattr(launch, "find_npm", lambda: npm)
    assert launch.needs_build(root)                                               # nothing built
    assert launch.ensure_frontend(root) == launch.OK
    assert log.read_text().splitlines() == ["ci", "run build"]                    # packages first (none installed), then the build
    assert not launch.needs_build(root) and (launch.static_dir(root) / launch.STAMP).is_file()
    assert launch.ensure_frontend(root) == launch.OK
    assert len(log.read_text().splitlines()) == 2                                 # up to date: no work on this launch
    (tmp_path / "fe/frontend/src/__tests__/a.test.ts").write_text("changed tests\n")
    (tmp_path / "fe/frontend/src/fixtures/f.json").write_text("{\"a\": 1}")
    assert not launch.needs_build(root)                                           # tests and fixtures do not feed the build
    (tmp_path / "fe/frontend/src/app.tsx").write_text("export const a = 2;\n")
    assert launch.needs_build(root)
    assert launch.ensure_frontend(root) == launch.OK
    assert log.read_text().splitlines()[2:] == ["run build"]                      # packages already there: only the build
    assert not launch.needs_build(root)


def test_a_failed_build_is_reported_and_leaves_no_stamp(tmp_path, monkeypatch, capsys):
    root = frontend_tree(tmp_path)
    npm, _ = fake_npm(tmp_path, root, fail_on="run build")
    monkeypatch.setattr(launch, "find_npm", lambda: npm)
    assert launch.ensure_frontend(root) == launch.SETUP
    assert "build failed" in capsys.readouterr().err and launch.needs_build(root)


def test_without_npm_an_existing_build_is_used_and_a_missing_one_is_an_error(tmp_path, monkeypatch, capsys):
    root = frontend_tree(tmp_path)
    monkeypatch.setattr(launch, "find_npm", lambda: None)
    assert launch.ensure_frontend(root) == launch.SETUP and "npm was not found" in capsys.readouterr().err
    st = launch.static_dir(root)
    st.mkdir(parents=True)
    (st / "index.html").write_text("old build")
    assert launch.ensure_frontend(root) == launch.OK and "existing build" in capsys.readouterr().out


def test_a_checkout_without_frontend_sources_uses_the_build_it_has(tmp_path):
    root = fake_project(tmp_path, "")
    assert launch.source_hash(root) is None and not launch.needs_build(root)


# ------------------------------------------------------------------------------------------------------------------------ stopping

def test_stop_ends_this_applications_server_and_only_that(app, home, foreign, tmp_path):
    port, proc = app
    fport, fproc = foreign
    other_port = free_port()
    other_home = tmp_path / "other"
    other_home.mkdir()
    other = start_app(other_port, other_home)
    try:
        for pref in (port, fport, other_port):
            p, _ = run_launcher(["--stop", "--port", str(pref)], home, tmp_path)
            assert finish(p)[0] == 0
        assert proc.wait(15) is not None                                          # ours, same data: stopped
        assert fproc.poll() is None and other.poll() is None                      # a foreign server and a trainer on other data: untouched
    finally:
        stop(other)


def test_stop_with_nothing_running_says_so(home, tmp_path):
    p, _ = run_launcher(["--stop", "--port", str(free_port())], home, tmp_path)
    code, out = finish(p)
    assert code == 0 and "No Rates Trainer server is running" in out


# ------------------------------------------------------------------------------------------------------------------------ the double-click wrapper and the installer

COMMAND = ROOT / "Rates Trainer.command"
INSTALL = ROOT / "scripts" / "install_launcher.sh"


def fake_checkout(tmp_path: Path, python_body: str | None) -> Path:
    proj = tmp_path / "Rates Trainer project"                                    # a space in the path, as a real folder may have
    (proj / "scripts").mkdir(parents=True)
    (proj / "trainer").write_text("")
    (proj / "scripts/launch.py").write_text("")
    shutil.copy(COMMAND, proj / "Rates Trainer.command")
    if python_body is not None:
        py = proj / ".venv/bin/python"
        py.parent.mkdir(parents=True)
        py.write_text(f"#!/bin/sh\n{python_body}\n")
        py.chmod(0o755)
    return proj


def run_sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30, **kw)


def test_the_command_file_finds_its_project_through_a_symlink_and_uses_the_venv(tmp_path):
    proj = fake_checkout(tmp_path, 'echo "PY $PWD $@"')
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / "Rates Trainer.command").symlink_to(proj / "Rates Trainer.command")
    r = run_sh([str(desktop / "Rates Trainer.command"), "--port", "9"])
    assert r.returncode == 0
    assert r.stdout.strip() == f"PY {proj.resolve()} {proj.resolve()}/scripts/launch.py --port 9"


def test_the_command_file_explains_a_missing_environment_and_a_failed_start(tmp_path):
    r = run_sh([str(fake_checkout(tmp_path / "a", None) / "Rates Trainer.command")]) if (tmp_path / "a").mkdir() is None else None
    assert r.returncode == 2 and "python3 -m venv .venv" in r.stdout
    proj = fake_checkout(tmp_path / "b", "echo startup failed >&2; exit 3") if (tmp_path / "b").mkdir() is None else None
    r = run_sh([str(proj / "Rates Trainer.command")])
    assert r.returncode == 3 and "did not start (exit code 3)" in r.stdout and "startup failed" in r.stderr


def test_the_installer_puts_an_executable_launcher_on_the_desktop_and_it_starts_the_project(tmp_path):
    proj = fake_checkout(tmp_path, 'echo "PY $@"')
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    r = run_sh(["bash", str(INSTALL), "--command", "--dest", str(desktop), "--root", str(proj)])
    target = desktop / "Rates Trainer.command"
    assert r.returncode == 0 and f"Installed: {target}" in r.stdout
    assert os.access(target, os.X_OK) and "rates-trainer-launcher" in target.read_text()
    again = run_sh(["bash", str(INSTALL), "--command", "--dest", str(desktop), "--root", str(proj)])      # running it twice is fine
    assert again.returncode == 0
    go = run_sh([str(target), "--flag"])
    assert go.returncode == 0 and go.stdout.strip() == f"PY {proj.resolve()}/scripts/launch.py --flag"


def test_the_installer_never_overwrites_a_file_that_is_not_its_own_unless_forced(tmp_path):
    proj = fake_checkout(tmp_path, "true")
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    mine = desktop / "Rates Trainer.command"
    mine.write_text("#!/bin/sh\necho my own script\n")
    r = run_sh(["bash", str(INSTALL), "--command", "--dest", str(desktop), "--root", str(proj)])
    assert r.returncode == 1 and "not overwriting" in r.stderr and "my own script" in mine.read_text()
    assert run_sh(["bash", str(INSTALL), "--command", "--dest", str(desktop), "--root", str(proj), "--force"]).returncode == 0
    assert "rates-trainer-launcher" in mine.read_text()
    assert run_sh(["bash", str(INSTALL), "--command", "--dest", str(tmp_path / "missing"), "--root", str(proj)]).returncode == 1


def test_a_desktop_launcher_whose_project_has_moved_says_so(tmp_path):
    proj = fake_checkout(tmp_path, "true")
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    assert run_sh(["bash", str(INSTALL), "--command", "--dest", str(desktop), "--root", str(proj)]).returncode == 0
    proj.rename(tmp_path / "moved")
    r = run_sh([str(desktop / "Rates Trainer.command")])
    assert r.returncode == 2 and "no longer at" in r.stdout and "install_launcher.sh" in r.stdout
