"""The macOS app "Rates Trainer.app": its icon, the installer that builds it, scripts/app_launcher.sh and `launch.py --detach`.

As in test_launcher.py, everything runs against temporary data and log directories and free ports, with a stand-in for `open` that only writes the URL to a file. No test
shows a dialog, opens Terminal or a browser, touches ~/.rates_trainer, ~/Library/Logs or the real Desktop, or kills a process it did not start.
"""

import os
import plistlib
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from .test_launcher import ROOT, env_for, finish, foreign, fake_project, free_port, home, launch, opened, run_launcher, run_sh, wait_for, _alive  # noqa: F401  (fixtures)

ASSETS = ROOT / "scripts" / "assets"
INSTALL = ROOT / "scripts" / "install_launcher.sh"
APP_LAUNCHER = ROOT / "scripts" / "app_launcher.sh"
HAS_ICONUTIL = shutil.which("iconutil") is not None


# ------------------------------------------------------------------------------------------------------------------------ the icon

def test_the_icon_sources_are_text_free_vector_art():
    for name in ("icon.svg", "icon_small.svg"):
        root = ET.parse(ASSETS / name).getroot()
        tags = {el.tag.split("}")[-1] for el in root.iter()}
        assert root.get("width") == "1024" and root.get("height") == "1024"
        assert "text" not in tags and "image" not in tags, f"{name}: no lettering and no embedded bitmaps"


@pytest.mark.skipif(not HAS_ICONUTIL, reason="iconutil ships with macOS")
def test_the_icns_holds_every_size_macos_asks_for_at_the_right_pixels(tmp_path):
    icns = ASSETS / "AppIcon.icns"
    assert icns.read_bytes()[:4] == b"icns"
    out = tmp_path / "x.iconset"
    assert subprocess.run(["iconutil", "-c", "iconset", str(icns), "-o", str(out)], capture_output=True).returncode == 0
    want = {"icon_16x16": 16, "icon_16x16@2x": 32, "icon_32x32": 32, "icon_32x32@2x": 64, "icon_128x128": 128, "icon_128x128@2x": 256,
            "icon_256x256": 256, "icon_256x256@2x": 512, "icon_512x512": 512, "icon_512x512@2x": 1024}
    assert {f.stem: f for f in out.glob("*.png")}.keys() == want.keys()
    for stem, px in want.items():
        head = (out / f"{stem}.png").read_bytes()[:26]
        assert head[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", head[16:24]) == (px, px), stem
        assert head[25] == 6, f"{stem} keeps its transparent corners (RGBA)"


def test_the_preview_is_a_1024_png():
    head = (ASSETS / "AppIcon-1024.png").read_bytes()[:26]
    assert head[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", head[16:24]) == (1024, 1024)


# ------------------------------------------------------------------------------------------------------------------------ the installer

def app_checkout(tmp_path: Path, app_launcher_body: str | None = None) -> Path:
    proj = tmp_path / "Rates Trainer project"                                    # a space in the path, as a real folder may have
    (proj / "scripts/assets").mkdir(parents=True)
    (proj / "trainer").write_text("")
    for n in ("launch_in_terminal.command", "stop_server.sh"):
        shutil.copy(ROOT / "scripts" / n, proj / "scripts" / n)
    shutil.copy(ASSETS / "AppIcon.icns", proj / "scripts/assets/AppIcon.icns")
    shutil.copy(ROOT / "Rates Trainer.command", proj / "Rates Trainer.command")
    target = proj / "scripts/app_launcher.sh"
    if app_launcher_body is None:
        shutil.copy(APP_LAUNCHER, target)
    else:
        target.write_text(f"#!/bin/bash\n{app_launcher_body}\n")
    target.chmod(0o755)
    return proj


def install(proj, desktop, *flags):
    return run_sh(["bash", str(INSTALL), "--dest", str(desktop), "--root", str(proj), *flags])


def test_the_installer_builds_an_app_with_the_icon_registered_in_its_plist(tmp_path):
    proj, desktop = app_checkout(tmp_path), tmp_path / "Desktop"
    desktop.mkdir()
    r = install(proj, desktop)
    app = desktop / "Rates Trainer.app"
    assert r.returncode == 0 and f"Installed: {app}" in r.stdout, r.stderr
    plist = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert plist["CFBundleIconFile"] == "AppIcon" and plist["CFBundleName"] == plist["CFBundleDisplayName"] == "Rates Trainer"
    assert plist["CFBundleExecutable"] == "launcher" and plist["CFBundlePackageType"] == "APPL" and plist["CFBundleIdentifier"] == "local.ratestrainer.launcher"
    assert (app / "Contents/Resources/AppIcon.icns").read_bytes() == (ASSETS / "AppIcon.icns").read_bytes()
    assert os.access(app / "Contents/MacOS/launcher", os.X_OK) and (app / "Contents/Resources/rates-trainer-launcher").read_text().startswith(f"project={proj}")
    if shutil.which("codesign"):
        assert subprocess.run(["codesign", "--verify", "--deep", str(app)], capture_output=True).returncode == 0


def test_the_apps_executable_runs_the_projects_launcher_from_the_recorded_folder(tmp_path):
    proj, desktop = app_checkout(tmp_path, 'echo "ROOT=$RATES_TRAINER_ROOT ARGS=$#"'), tmp_path / "Desktop"
    desktop.mkdir()
    assert install(proj, desktop).returncode == 0
    r = run_sh([str(desktop / "Rates Trainer.app/Contents/MacOS/launcher")])
    assert r.returncode == 0 and r.stdout.strip() == f"ROOT={proj} ARGS=0", r.stderr


def test_the_installer_replaces_its_own_app_refuses_a_foreign_one_and_force_overrides(tmp_path):
    proj, desktop = app_checkout(tmp_path), tmp_path / "Desktop"
    desktop.mkdir()
    assert install(proj, desktop).returncode == 0
    again = install(proj, desktop)
    assert again.returncode == 0 and "Replacing the existing launcher" in again.stdout
    shutil.rmtree(desktop / "Rates Trainer.app")
    (desktop / "Rates Trainer.app/Contents").mkdir(parents=True)
    (desktop / "Rates Trainer.app/Contents/mine.txt").write_text("not yours")
    r = install(proj, desktop)
    assert r.returncode == 1 and "not overwriting" in r.stderr and (desktop / "Rates Trainer.app/Contents/mine.txt").exists()
    assert install(proj, desktop, "--force").returncode == 0 and not (desktop / "Rates Trainer.app/Contents/mine.txt").exists()
    assert install(proj, tmp_path / "missing").returncode == 1


def test_the_app_replaces_the_older_command_launcher_only_when_the_installer_made_it(tmp_path):
    proj, desktop = app_checkout(tmp_path), tmp_path / "Desktop"
    desktop.mkdir()
    assert install(proj, desktop, "--command").returncode == 0 and (desktop / "Rates Trainer.command").exists()
    r = install(proj, desktop)
    assert r.returncode == 0 and "Removed the older launcher" in r.stdout and not (desktop / "Rates Trainer.command").exists()
    assert (desktop / "Rates Trainer.app").is_dir()
    mine = desktop / "Rates Trainer.command"
    mine.write_text("#!/bin/sh\necho my own script\n")
    assert install(proj, desktop).returncode == 0 and "my own script" in mine.read_text()           # not ours: left alone


def test_a_missing_icon_is_reported_but_the_app_is_still_made(tmp_path):
    proj, desktop = app_checkout(tmp_path), tmp_path / "Desktop"
    desktop.mkdir()
    (proj / "scripts/assets/AppIcon.icns").unlink()
    r = install(proj, desktop)
    assert r.returncode == 0 and "AppIcon.icns is missing" in r.stderr and (desktop / "Rates Trainer.app/Contents/MacOS/launcher").exists()


# ------------------------------------------------------------------------------------------------------------------------ scripts/app_launcher.sh

def fake_checkout_with_python(tmp_path: Path, python_body: str | None) -> Path:
    proj = tmp_path / "proj"
    (proj / "scripts").mkdir(parents=True)
    (proj / "trainer").write_text("")
    (proj / "scripts/launch.py").write_text("")
    shutil.copy(APP_LAUNCHER, proj / "scripts/app_launcher.sh")
    if python_body is not None:
        py = proj / ".venv/bin/python"
        py.parent.mkdir(parents=True)
        py.write_text(f"#!/bin/sh\n{python_body}\n")
        py.chmod(0o755)
    return proj


def run_app(proj: Path, tmp_path: Path, *args):
    env = {**os.environ, "RATES_TRAINER_ROOT": str(proj), "RATES_TRAINER_LOG_DIR": str(tmp_path / "logs"), "RATES_TRAINER_NO_DIALOG": "1"}
    return subprocess.run(["bash", str(proj / "scripts/app_launcher.sh"), *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30, env=env)


def test_the_app_launcher_runs_the_detached_launcher_with_the_projects_python_and_logs_it(tmp_path):
    proj = fake_checkout_with_python(tmp_path, 'echo "PY $PWD $@"')
    r = run_app(proj, tmp_path, "--port", "9")
    assert r.returncode == 0 and r.stdout.strip() == f"PY {proj.resolve()} {proj.resolve()}/scripts/launch.py --detach --port 9"
    assert "launching:" in (tmp_path / "logs/launcher.log").read_text() and " ok" in (tmp_path / "logs/launcher.log").read_text()


def test_the_app_launcher_explains_a_failed_start_with_the_launchers_own_message_and_its_exit_code(tmp_path):
    proj = fake_checkout_with_python(tmp_path, 'echo "Rates Trainer"; echo "Project: x"; echo "The server stopped during startup (exit code 3)." >&2; exit 3')
    r = run_app(proj, tmp_path)
    assert r.returncode == 3
    assert "could not start: It did not start (exit code 3)." in r.stderr and "stopped during startup" in r.stderr and f"Logs: {tmp_path / 'logs'}" in r.stderr
    assert "Project: x" not in r.stderr                                      # the progress lines are not repeated in the error
    assert "FAILED" in (tmp_path / "logs/launcher.log").read_text()


def test_the_app_launcher_explains_a_missing_environment_and_a_moved_project(tmp_path):
    (tmp_path / "a").mkdir()
    r = run_app(fake_checkout_with_python(tmp_path / "a", None), tmp_path)
    assert r.returncode == 2 and "There is no Python environment" in r.stderr and "python3 -m venv .venv" in r.stderr
    gone = tmp_path / "gone"
    gone.mkdir()
    shutil.copy(APP_LAUNCHER, gone / "app_launcher.sh")
    r = subprocess.run(["bash", str(gone / "app_launcher.sh")], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30,
                       env={**os.environ, "RATES_TRAINER_ROOT": str(tmp_path / "moved"), "RATES_TRAINER_LOG_DIR": str(tmp_path / "logs2"), "RATES_TRAINER_NO_DIALOG": "1"})
    assert r.returncode == 2 and "project folder was not found" in r.stderr and "install_launcher.sh" in r.stderr


# ------------------------------------------------------------------------------------------------------------------------ launch.py --detach

@pytest.fixture()
def logs(tmp_path):
    return tmp_path / "logs"


@pytest.fixture()
def detached(home, logs, tmp_path):
    """Run `launch.py --detach ...`; whatever server it leaves behind is stopped afterwards (through --stop, as a user would)."""
    started = []

    def go(*args, **kw):
        p, log = run_launcher(["--detach", "--no-build", *args], home, tmp_path, RATES_TRAINER_LOG_DIR=str(logs), **kw)
        started.append(args)
        return p, log
    yield go
    for args in started:
        port = args[args.index("--port") + 1] if "--port" in args else None
        if port:
            subprocess.run([sys.executable, str(ROOT / "scripts/launch.py"), "--stop", "--port", port], env=env_for(home, RATES_TRAINER_LOG_DIR=str(logs)), capture_output=True, timeout=30)


def test_detach_starts_the_server_in_the_background_opens_the_browser_and_leaves_it_running(detached, home, logs):
    port = free_port()
    p, log = detached("--port", str(port))
    code, out = finish(p, 90)
    assert code == 0 and f"running at http://127.0.0.1:{port}/" in out and "keeps running in the background" in out
    assert opened(log) == [f"http://127.0.0.1:{port}/"]
    h = launch.probe(port)
    assert h["state"] == "ours" and h["data_dir"] == str(home) and _alive(h["pid"])          # the launcher has exited, the server has not
    assert "start on port" in (logs / "server.log").read_text()
    stop = subprocess.run([sys.executable, str(ROOT / "scripts/launch.py"), "--stop", "--port", str(port)], env=env_for(home, RATES_TRAINER_LOG_DIR=str(logs)), capture_output=True, text=True, timeout=30)
    assert "Stopped the Rates Trainer server" in stop.stdout
    assert wait_for(lambda: launch.probe(port, 0.2)["state"] == "free", 15)


def test_launching_again_opens_the_running_server_instead_of_starting_another(detached, tmp_path, logs):
    port = free_port()
    code, _ = finish(detached("--port", str(port))[0], 90)
    pid = launch.probe(port)["pid"]
    p, log = detached("--port", str(port))
    code2, out = finish(p, 30)
    assert code == 0 and code2 == 0 and "already running" in out
    assert opened(log) == [f"http://127.0.0.1:{port}/"] * 2                              # one open per launch (they share the stand-in browser's log), both the same server
    assert launch.probe(port)["pid"] == pid and launch.probe(port + 1)["state"] == "free"
    assert (logs / "server.log").read_text().count("start on port") == 1


def test_two_launches_at_the_same_moment_start_one_server(detached, logs):
    port = free_port(2)
    a, log_a = detached("--port", str(port))
    b, log_b = detached("--port", str(port))
    (ca, oa), (cb, ob) = finish(a, 90), finish(b, 90)
    assert ca == cb == 0, oa + ob
    assert (logs / "server.log").read_text().count("start on port") == 1                 # one server was started, the other launch found it
    assert opened(log_a) == opened(log_b) == [f"http://127.0.0.1:{port}/"] * 2           # each launch opened the one server (the stand-in browser's log is shared)
    assert launch.probe(port)["state"] == "ours" and launch.probe(port + 1)["state"] == "free"


def test_detach_skips_a_foreign_server_without_touching_it(detached, foreign):
    port, occupant = foreign
    p, log = detached("--port", str(port))
    code, out = finish(p, 90)
    assert code == 0 and "Leaving it alone" in out and occupant.poll() is None
    url = opened(log)[0]
    assert url != f"http://127.0.0.1:{port}/" and launch.probe(port)["state"] == "other"


def test_detach_reports_a_server_that_dies_during_startup_with_the_end_of_its_log(home, logs, tmp_path):
    root = fake_project(tmp_path, 'import sys\nprint("boom: cannot bind", file=sys.stderr)\nsys.exit(3)\n')
    p, log = run_launcher(["--detach", "--root", str(root), "--port", str(free_port()), "--no-build"], home, tmp_path, RATES_TRAINER_LOG_DIR=str(logs))
    code, out = finish(p)
    assert code == launch.FAILED and "stopped during startup (exit code 3)" in out and "boom: cannot bind" in out and "The end of" in out
    assert opened(log) == [] and "boom: cannot bind" in (logs / "server.log").read_text()


def test_detach_leaves_nothing_behind_when_the_server_never_answers(home, logs, tmp_path):
    pidfile = tmp_path / "child.pid"
    root = fake_project(tmp_path, f'import os, time\nopen({str(pidfile)!r}, "w").write(str(os.getpid()))\ntime.sleep(60)\n')
    p, log = run_launcher(["--detach", "--root", str(root), "--port", str(free_port()), "--no-build", "--timeout", "1.5"], home, tmp_path, RATES_TRAINER_LOG_DIR=str(logs))
    code, out = finish(p)
    assert code == launch.TIMEOUT and "did not answer" in out and opened(log) == []
    assert wait_for(lambda: not _alive(int(pidfile.read_text())), 10), "the child server was left running"


def test_the_log_folder_is_not_the_data_folder_or_the_project(monkeypatch, tmp_path):
    monkeypatch.delenv("RATES_TRAINER_LOG_DIR", raising=False)
    d = launch.log_dir()
    assert launch.data_dir() not in d.parents and d != launch.data_dir() and ROOT not in d.parents
    monkeypatch.setenv("RATES_TRAINER_LOG_DIR", str(tmp_path / "x"))
    assert launch.log_dir() == tmp_path / "x"
