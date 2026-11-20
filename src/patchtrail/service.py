# SPDX-License-Identifier: Apache-2.0
"""The fetch runner and the scheduler of `ptl serve`.

A fetch never runs in the server process: each one is a child
`python -m patchtrail fetch --trigger ...`, tracked by PID, which takes the fetch
lock itself. The child leads its own process group, so a timeout kills the whole group."""
import os
import signal
import subprocess
import sys
import threading
import time
import traceback

from patchtrail import db, fetch, views
from patchtrail.config import Paths


class Runner:
    def __init__(self, paths: Paths, *, timeout_s: float, grace_s: float = 30,
                 spawn=subprocess.Popen, now=time.time):
        self._paths, self._timeout_s, self._grace_s = paths, timeout_s, grace_s
        self._spawn, self._now = spawn, now
        self._lock = threading.Lock()          # guards start and poll
        self._child = None
        self._started = 0.0

    @property
    def child_pid(self) -> int | None:
        with self._lock:
            return self._child.pid if self._alive() else None

    def _alive(self) -> bool:
        return self._child is not None and self._child.poll() is None

    def _reap(self, error: str | None = None) -> None:
        conn = db.connect(self._paths.db)
        try:
            fetch.reap_stale(self._paths, conn, int(self._now()), error)
        finally:
            conn.close()

    def _after_exit(self) -> None:
        """The child is gone: forget it, and mark what it left running."""
        code = self._child.returncode
        self._child = None
        self._reap(f"fetch process exited with status {code}" if code else None)

    def starting(self, conn) -> bool:
        with self._lock:
            if not self._alive():
                return False
            pid = self._child.pid
        return conn.execute("SELECT 1 FROM runs WHERE status='running' AND pid=?",
                            (pid,)).fetchone() is None

    def start(self, trigger: str, names: list[str] | None = None,
              lore_only: bool = False) -> None:
        with self._lock:
            conn = db.connect(self._paths.db)
            try:
                if self._child is not None and not self._alive():
                    self._after_exit()
                if self._child is not None:
                    raise fetch.Busy(conn.execute(
                        "SELECT * FROM runs WHERE status='running' ORDER BY id DESC LIMIT 1"
                    ).fetchone())
                with fetch.locked(self._paths, conn):
                    pass                       # released at once; the child takes it itself
            finally:
                conn.close()
            argv = [sys.executable, "-m", "patchtrail", "fetch", "--trigger", trigger,
                    *(["--lore-only"] if lore_only else []), *(names or [])]
            self._child = self._spawn(argv, process_group=0, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL)
            self._started = self._now()

    def poll(self) -> None:
        with self._lock:
            if self._child is None:
                self._reap()
            elif not self._alive():
                self._after_exit()
            elif self._now() - self._started > self._timeout_s:
                h = self._timeout_s / 3600
                self._kill(self._grace_s, f"killed after {h:g} {'hour' if h == 1 else 'hours'}")

    def _kill(self, grace_s: float, error: str) -> None:
        """Kill the child's process group: SIGTERM, SIGKILL after grace_s. Every wait is
        bounded; a child that survives SIGKILL is kept for a later poll() to reap."""
        child = self._child
        self._signal(child.pid, signal.SIGTERM)
        try:
            child.wait(grace_s)
        except subprocess.TimeoutExpired:
            pass
        # Also reaches stragglers in the group. If the child was already reaped by the
        # wait above, an unrelated group reusing the pgid is not a realistic concern.
        self._signal(child.pid, signal.SIGKILL)
        try:
            child.wait(5)
        except subprocess.TimeoutExpired:
            return                             # uninterruptible; poll() retries
        self._child = None
        self._reap(error)

    def terminate(self) -> None:
        """Stop a running fetch because the service is shutting down."""
        with self._lock:
            if self._alive():
                self._kill(min(self._grace_s, 5), "stopped with the service")

    @staticmethod
    def _signal(pgid: int, sig: int) -> None:
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass


class Scheduler:
    def __init__(self, runner: Runner, paths: Paths, *, interval_s: float, now=time.time):
        self._runner, self._paths, self._interval_s, self._now = runner, paths, interval_s, now
        self._last_spawn: float | None = None

    def next_at(self, conn) -> int:
        return views.next_fetch_at(conn, self._interval_s, int(self._now()))

    def tick(self) -> None:
        self._runner.poll()
        conn = db.connect(self._paths.db)
        try:
            due_at = self.next_at(conn)
        finally:
            conn.close()
        if self._last_spawn is not None:       # a child may die before it writes a run row
            due_at = max(due_at, self._last_spawn + self._interval_s)
        if self._now() >= due_at and self._runner.child_pid is None:
            try:
                self._runner.start("schedule")
                self._last_spawn = self._now()
            except fetch.Busy:
                pass                           # a CLI or cron fetch counts as the run

    def run_forever(self, stop: threading.Event, every_s: float = 15) -> None:
        while not stop.is_set():
            try:
                self.tick()
            except Exception:
                traceback.print_exc()
            stop.wait(every_s)
