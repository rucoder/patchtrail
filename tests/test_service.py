# SPDX-License-Identifier: Apache-2.0
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from patchtrail import db, fetch, service
from patchtrail.config import paths


def _conn():
    return db.connect(paths().db)


def _add_run(conn, *, started_at, status="running", pid=None, trigger="cli"):
    cur = conn.execute("INSERT INTO runs(pid, trigger, started_at, status) VALUES (?,?,?,?)",
                       (pid, trigger, started_at, status))
    conn.commit()
    return cur.lastrowid


def _row(conn, run_id):
    return conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()


class FakeChild:
    pid = 4242
    returncode = 0

    def __init__(self, alive=True):
        self.alive = alive

    def poll(self):
        return None if self.alive else 0


class Spawner:
    def __init__(self, alive=True):
        self.calls, self.alive = [], alive

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return FakeChild(self.alive)


def test_start_spawns_child_with_trigger():
    spawn = Spawner()
    r = service.Runner(paths(), timeout_s=10, spawn=spawn)
    r.start("page", ["a", "b"], lore_only=True)
    argv, kw = spawn.calls[0]
    assert argv == [sys.executable, "-m", "patchtrail", "fetch", "--trigger", "page",
                    "--lore-only", "a", "b"]
    assert kw["process_group"] == 0
    assert kw["stdin"] == subprocess.DEVNULL and kw["stdout"] == subprocess.DEVNULL
    assert r.child_pid == 4242


def test_start_refused_while_child_alive():
    spawn = Spawner()
    r = service.Runner(paths(), timeout_s=10, spawn=spawn)
    r.start("page")
    with pytest.raises(fetch.Busy):
        r.start("page")
    assert len(spawn.calls) == 1


def test_start_refused_when_cli_holds_lock():
    spawn = Spawner()
    r = service.Runner(paths(), timeout_s=10, spawn=spawn)
    conn = _conn()
    _add_run(conn, started_at=1, pid=os.getpid())
    with fetch.locked(paths(), conn):
        with pytest.raises(fetch.Busy) as e:
            r.start("page")
    assert e.value.run["pid"] == os.getpid()
    assert spawn.calls == []


def test_starting_until_running_row_has_child_pid():
    r = service.Runner(paths(), timeout_s=10, spawn=Spawner())
    conn = _conn()
    assert not r.starting(conn)
    r.start("page")
    assert r.starting(conn)
    _add_run(conn, started_at=1, pid=4242)
    assert not r.starting(conn)


def test_nonzero_exit_marks_interrupted_with_status():
    r2 = service.Runner(paths(), timeout_s=10, spawn=lambda argv, **kw: subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(3)"], **kw))
    conn2 = _conn()
    rid2 = _add_run(conn2, started_at=2, pid=1)
    r2.start("page")
    r2._child.wait()
    r2.poll()
    row = _row(conn2, rid2)
    assert row["status"] == "interrupted"
    assert row["error"] == "fetch process exited with status 3"
    assert r2.child_pid is None


def test_timeout_kills_group_and_marks_interrupted(tmp_path):
    flag = tmp_path / "gc.pid"
    code = (
        "import os, subprocess, sys, time\n"
        "from patchtrail import db\n"
        "from patchtrail.config import paths\n"
        "c = db.connect(paths().db)\n"
        "c.execute(\"INSERT INTO runs(pid, trigger, started_at, status) VALUES (?, 'page', 1, 'running')\","
        " (os.getpid(),))\n"
        "c.commit()\n"
        f"g = subprocess.Popen(['sleep', '600'])\n"
        f"open({str(flag)!r}, 'w').write(str(g.pid))\n"
        "time.sleep(600)\n")
    clock = [1000]
    r = service.Runner(paths(), timeout_s=1, grace_s=1, now=lambda: clock[0],
                       spawn=lambda argv, **kw: subprocess.Popen([sys.executable, "-c", code], **kw))
    gc = None
    try:
        r.start("page")
        pid = r.child_pid
        deadline = time.time() + 15
        while not flag.exists() or not flag.read_text():
            assert time.time() < deadline
            time.sleep(0.05)
        gc = int(flag.read_text())
        r.poll()                       # within the timeout: nothing happens
        assert r.child_pid == pid
        clock[0] += 2
        r.poll()
        assert r.child_pid is None
        for p in (pid, gc):
            with pytest.raises(ProcessLookupError):
                os.kill(p, 0)
        row = _conn().execute("SELECT * FROM runs").fetchone()
        assert row["status"] == "interrupted" and "killed after" in row["error"]
    finally:
        if r._child is not None:
            try:
                os.killpg(r._child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            r._child.wait()
        if gc:
            try:
                os.kill(gc, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_stale_running_row_reaped():
    conn = _conn()
    rid = _add_run(conn, started_at=1, pid=999999)
    service.Runner(paths(), timeout_s=10, now=lambda: 50).poll()
    row = _row(conn, rid)
    assert row["status"] == "interrupted" and row["finished_at"] == 50


def _sched(now, spawn=None, interval=100):
    r = service.Runner(paths(), timeout_s=10, spawn=spawn or Spawner(), now=lambda: now[0])
    return r, service.Scheduler(r, paths(), interval_s=interval, now=lambda: now[0])


def test_scheduler_due_at_startup_with_no_runs():
    now = [500]
    spawn = Spawner()
    r, s = _sched(now, spawn)
    assert s.next_at(_conn()) == 500
    s.tick()
    assert spawn.calls and spawn.calls[0][0][5] == "schedule"


def test_scheduler_waits_interval_after_cli_run():
    now = [1000]
    spawn = Spawner()
    r, s = _sched(now, spawn)
    _add_run(_conn(), started_at=950, status="ok", trigger="cli")
    assert s.next_at(_conn()) == 1050
    s.tick()
    assert spawn.calls == []
    now[0] = 1050
    s.tick()
    assert len(spawn.calls) == 1


def test_schedule_after_failed_run():
    now = [1000]
    spawn = Spawner()
    r, s = _sched(now, spawn)
    _add_run(_conn(), started_at=1000, status="failed", trigger="schedule")
    now[0] = 1099
    s.tick()
    assert spawn.calls == []
    now[0] = 1100
    s.tick()
    assert len(spawn.calls) == 1


def test_tick_ignores_busy():
    now = [1000]
    spawn = Spawner()
    r, s = _sched(now, spawn)
    conn = _conn()
    _add_run(conn, started_at=1, pid=os.getpid())
    with fetch.locked(paths(), conn):
        s.tick()                       # due, but a CLI fetch holds the lock
    assert spawn.calls == []


def test_run_forever_stops():
    now = [1000]
    spawn = Spawner()
    r, s = _sched(now, spawn)
    stop = threading.Event()
    t = threading.Thread(target=s.run_forever, args=(stop, 0.01))
    t.start()
    time.sleep(0.2)
    stop.set()
    t.join(5)
    assert not t.is_alive()
    assert len(spawn.calls) == 1


def test_failed_spawn_waits_interval():
    now = [1000]
    spawn = Spawner(alive=False)       # the child dies before it writes a run row
    r, s = _sched(now, spawn)
    s.tick()
    assert len(spawn.calls) == 1
    now[0] = 1015
    s.tick()
    assert len(spawn.calls) == 1
    now[0] = 1100
    s.tick()
    assert len(spawn.calls) == 2


def _group_child(code):
    return lambda argv, **kw: subprocess.Popen([sys.executable, "-c", code], **kw)


def _cleanup(r):
    if r._child is not None:
        try:
            os.killpg(r._child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        r._child.wait()


_ROW = ("import os, signal, sys, time\n"
        "from patchtrail import db\nfrom patchtrail.config import paths\n"
        "c = db.connect(paths().db)\n"
        "c.execute(\"INSERT INTO runs(pid, trigger, started_at, status) VALUES (?, 'page', 1, 'running')\","
        " (os.getpid(),))\nc.commit()\n")


def _wait_row(r):
    conn = _conn()
    deadline = time.time() + 15
    while not r.child_pid or r.starting(conn):
        assert time.time() < deadline
        time.sleep(0.05)


def test_timeout_sigkill_when_child_ignores_sigterm():
    code = _ROW + "signal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint('x')\ntime.sleep(600)\n"
    clock = [1000]
    r = service.Runner(paths(), timeout_s=1, grace_s=0.5, now=lambda: clock[0],
                       spawn=_group_child(code))
    try:
        r.start("page")
        pid = r.child_pid
        _wait_row(r)
        time.sleep(0.3)                # let the handler be installed
        clock[0] += 2
        r.poll()
        assert r.child_pid is None
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        row = _conn().execute("SELECT * FROM runs").fetchone()
        assert row["status"] == "interrupted" and "killed after" in row["error"]
    finally:
        _cleanup(r)


def test_terminate_stops_child_and_marks_interrupted():
    code = _ROW + "time.sleep(600)\n"
    r = service.Runner(paths(), timeout_s=3600, grace_s=0.5, spawn=_group_child(code))
    try:
        r.start("page")
        pid = r.child_pid
        _wait_row(r)
        r.terminate()
        assert r.child_pid is None
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        row = _conn().execute("SELECT * FROM runs").fetchone()
        assert row["status"] == "interrupted" and row["error"] == "stopped with the service"
        r.terminate()                  # no child: a no-op
    finally:
        _cleanup(r)


# ---- systemd user unit (Task 8) ----

class FakeRun:
    def __init__(self, linger="no", fail=()):
        self.calls, self.linger, self.fail = [], linger, tuple(fail)

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[:2] == ["loginctl", "show-user"]:
            return subprocess.CompletedProcess(argv, 0, f"Linger={self.linger}\n", "")
        if any(argv[:2] == [f[0], f[1]] or argv[0] == f for f in self.fail):
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        return subprocess.CompletedProcess(argv, 0, "", "")


def _cfg(listen="0.0.0.0:8470"):
    from patchtrail.config import Config
    return Config(listen=listen)


def test_unit_text_exec_and_home(monkeypatch):
    monkeypatch.delenv("PATCHTRAIL_HOME", raising=False)
    t = service.unit_text()
    assert f"ExecStart={sys.executable} -m patchtrail serve\n" in t
    assert "Restart=on-failure\nRestartSec=10\n" in t
    assert "WantedBy=default.target" in t and "PATCHTRAIL_HOME" not in t
    monkeypatch.setenv("PATCHTRAIL_HOME", "/srv/ptl")
    assert "Environment=PATCHTRAIL_HOME=/srv/ptl\n" in service.unit_text()
    assert service.unit_path().name == "patchtrail.service"
    assert service.unit_path().parent.parts[-2:] == ("systemd", "user")


def test_install_commands_in_order():
    run = FakeRun(linger="no")
    out = service.install(_cfg(), run)
    assert service.unit_path().read_text() == service.unit_text()
    user = os.environ.get("USER") or __import__("getpass").getuser()
    assert run.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "patchtrail.service"],
        ["loginctl", "show-user", user, "-p", "Linger"],
        ["loginctl", "enable-linger", user],
    ]
    import socket
    assert out[-1].endswith(f"http://{socket.gethostname()}:8470")


def test_install_linger_already_on():
    run = FakeRun(linger="yes")
    out = service.install(_cfg("127.0.0.1:9000"), run)
    assert not any(c[:2] == ["loginctl", "enable-linger"] for c in run.calls)
    assert out[-1].endswith("http://127.0.0.1:9000")
    assert not any("sudo" in line for line in out)


def test_install_linger_needs_sudo_prints_hint():
    run = FakeRun(linger="no", fail=[("loginctl", "enable-linger")])
    out = service.install(_cfg(), run)
    user = os.environ.get("USER") or __import__("getpass").getuser()
    assert (f"run: sudo loginctl enable-linger {user}  "
            "(so the service keeps running after you log out)") in out


def test_install_surfaces_systemctl_failure():
    run = FakeRun(fail=[("systemctl", "--user")])
    with pytest.raises(service.ServiceError, match="boom"):
        service.install(_cfg(), run)


def test_uninstall():
    service.install(_cfg(), FakeRun(linger="yes"))
    run = FakeRun()
    service.uninstall(run)
    assert not service.unit_path().exists()
    assert run.calls == [["systemctl", "--user", "disable", "--now", "patchtrail.service"],
                         ["systemctl", "--user", "daemon-reload"]]


class _DisableFails(FakeRun):
    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        rc = 1 if "disable" in argv else 0
        return subprocess.CompletedProcess(argv, rc, "", "no such unit")


def test_uninstall_never_installed_is_quiet():
    run = _DisableFails()
    out = service.uninstall(run)
    assert out == ["patchtrail.service was not installed"]
    assert run.calls[-1] == ["systemctl", "--user", "daemon-reload"]


def test_uninstall_half_installed_cleans_up():
    service.unit_path().parent.mkdir(parents=True, exist_ok=True)
    service.unit_path().write_text("x")

    run = _DisableFails()
    out = service.uninstall(run)
    assert not service.unit_path().exists()
    assert run.calls[-1] == ["systemctl", "--user", "daemon-reload"]
    assert "no such unit" in out[0]


def test_status_and_logs_argv():
    run = FakeRun()
    service.status(run)
    service.logs(False, run)
    service.logs(True, run)
    assert run.calls == [
        ["systemctl", "--user", "status", "patchtrail.service", "--no-pager"],
        ["journalctl", "--user", "-u", "patchtrail.service", "-e"],
        ["journalctl", "--user", "-u", "patchtrail.service", "-e", "-f"],
    ]
