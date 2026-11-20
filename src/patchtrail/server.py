# SPDX-License-Identifier: Apache-2.0
"""`ptl serve`: the JSON API and the built page, in one stdlib HTTP server.

Every route opens its own database connection. Every /api request must name a known
Host (an IP address, localhost, this machine's names or config `hosts`), so a DNS-rebinding
page cannot reach it. Requests that change state must be same-origin (when they carry an
Origin) and JSON, so a web page on another site cannot drive them. No route takes a git URL
or sets a tree; those stay CLI-only."""
import errno
import functools
import ipaddress
import json
import mimetypes
import re
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from patchtrail import __version__, actions, db, fetch, views
from patchtrail.actions import ActionError
from patchtrail.config import Config, Paths, my_addresses
from patchtrail.service import Runner, Scheduler
from patchtrail.sources import lore

NO_BUNDLE = (b"<!doctype html><html><body><p>patchtrail's web page was not built. Install from "
             b"a release, or run <code>make install</code> in a checkout. The API works: "
             b"<a href=\"/api/status\">/api/status</a></p></body></html>")
MAX_BODY = 1 << 20
_NUM = re.compile(r"[0-9]{1,18}")
_HOST = re.compile(r"(\[[^\]]*\]|[^:\[\]]*)(?::[0-9]*)?")


def host_name(host: str) -> str:
    """The name or address of a Host header, without its port, lowercased and without a
    trailing dot; "" when the header is malformed."""
    m = _HOST.fullmatch(host.strip())
    return m.group(1).lower().rstrip(".") if m else ""


def is_ip_literal(name: str) -> bool:
    """An IPv4 address, or a bracketed IPv6 one: a name DNS rebinding cannot use."""
    try:
        if name.startswith("[") and name.endswith("]"):
            ipaddress.IPv6Address(name[1:-1])
        else:
            ipaddress.IPv4Address(name)
    except ValueError:
        return False
    return True


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]          # names lowercase
    body: bytes = b""


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)


def _json(status: int, obj) -> Response:
    return Response(status, json.dumps(obj).encode())


def _error(status: int, message: str, **extra) -> Response:
    return _json(status, {"error": message, **extra})


class _BadRequest(Exception):
    pass


def _str_list(v, what: str) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise _BadRequest(f"{what} must be a list of strings")
    return v


def _opt_str(v, what: str) -> str | None:
    if v is not None and not isinstance(v, str):
        raise _BadRequest(f"{what} must be a string")
    return v


def _req_str(body: dict, key: str) -> str:
    v = body.get(key)
    if not isinstance(v, str):
        raise _BadRequest(f"{key} must be a string")
    return v


class App:
    def __init__(self, paths: Paths, cfg: Config, runner: Runner, scheduler: Scheduler, *,
                 static_dir: Path | None = None):
        self.paths, self.cfg, self.runner, self.scheduler = paths, cfg, runner, scheduler
        self.static_dir = (static_dir if static_dir is not None
                           else Path(str(resources.files("patchtrail") / "web" / "dist")))

    # --- dispatch ---------------------------------------------------------------

    def handle(self, req: Request) -> Response:
        try:
            if req.path == "/api" or req.path.startswith("/api/"):
                return self._api(req)
            if req.method not in ("GET", "HEAD"):
                return _error(405, "method not allowed")
            return self._static(req.path)
        except ActionError as e:
            return _error(e.status, str(e))
        except _BadRequest as e:
            return _error(400, str(e))

    @functools.cached_property
    def _own_names(self) -> frozenset[str]:
        """localhost, this machine's names and the configured hosts (looked up once)."""
        names = {"localhost", socket.gethostname(), socket.getfqdn(), *self.cfg.hosts}
        return frozenset(n for n in map(host_name, names) if n)

    def _unknown_host(self, req: Request) -> Response | None:
        name = host_name(req.headers.get("host", ""))
        if not name:
            return _error(403, "missing or malformed Host header")
        if is_ip_literal(name) or name in self._own_names:
            return None
        return _error(403, f"unknown Host {name}; add it to hosts in config.toml")

    def _api(self, req: Request) -> Response:
        refused = self._unknown_host(req)
        if refused:
            return refused
        if req.method not in ("GET", "HEAD"):
            refused = self._csrf(req)
            if refused:
                return refused
        parts = [unquote(p) for p in req.path.split("/")[2:]]
        conn = db.connect(self.paths.db)
        try:
            return self._route(conn, req, parts) or _error(404, "not found")
        finally:
            conn.close()

    @staticmethod
    def _csrf(req: Request) -> Response | None:
        origin = req.headers.get("origin")
        if origin is not None and origin != "http://" + req.headers.get("host", ""):
            return _error(403, "cross-origin request refused")
        ctype = req.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return _error(415, "Content-Type must be application/json")
        return None

    @staticmethod
    def _body(req: Request) -> dict:
        if not req.body.strip():
            return {}
        try:
            body = json.loads(req.body)
        except (ValueError, UnicodeDecodeError, RecursionError) as e:
            raise _BadRequest("body is not valid JSON") from e
        if not isinstance(body, dict):
            raise _BadRequest("body must be a JSON object")
        return body

    def _route(self, conn, req: Request, parts: list[str]) -> Response | None:
        m, n = req.method, len(parts)
        if m == "GET" and parts == ["status"]:
            return _json(200, self._status(conn))
        if m == "POST" and parts == ["fetch"]:
            self._body(req)
            try:
                self.runner.start("page")
            except fetch.Busy as e:
                return _error(409, "a fetch is already running",
                              running=views.run_dict(e.run) if e.run else None)
            return _json(202, self._status(conn))
        if m == "GET" and n == 3 and parts[0] == "runs" and parts[2] == "log":
            if not _NUM.fullmatch(parts[1]):
                return _error(404, "no such run")
            after = req.query.get("after", "0")
            if not _NUM.fullmatch(after):
                raise _BadRequest("after must be a non-negative integer")
            log = views.run_log(conn, int(parts[1]), int(after))
            return _json(200, log) if log is not None else _error(404, "no such run")
        if parts[:1] != ["patches"]:
            return None
        if n == 1:
            if m == "GET":
                return _json(200, {"patches": views.cards(
                    conn, my_addresses(self.cfg), now=int(time.time()),
                    idle_days=self.cfg.idle_days)})
            if m == "POST":
                return self._register(conn, self._body(req))
            return None
        name = parts[1]
        if n == 2 and m == "GET":
            row = actions.patch(conn, name)
            return _json(200, views.detail(conn, row, my_addresses(self.cfg),
                                           now=int(time.time()),
                                           idle_days=self.cfg.idle_days))
        if n == 3 and m == "GET" and parts[2] == "mails":
            row = actions.patch(conn, name)
            return _json(200, views.mails(conn, row, my_addresses(self.cfg)))
        if n == 3 and (m, parts[2]) in _CHANGES:
            row = actions.patch(conn, name)
            body = self._body(req)
            _CHANGES[(m, parts[2])](self, conn, row, body)
            return self._card(conn, name)
        return None

    # --- pieces -----------------------------------------------------------------

    def _status(self, conn) -> dict:
        return views.status(conn, interval_hours=self.cfg.interval_hours,
                            now=int(time.time()), starting=self.runner.starting(conn),
                            version=__version__)

    def _card(self, conn, name: str) -> Response:
        row = actions.patch(conn, name)
        return _json(200, views.card(conn, row, my_addresses(self.cfg), now=int(time.time()),
                                     idle_days=self.cfg.idle_days))

    def _register(self, conn, body: dict) -> Response:
        name, msgid = _req_str(body, "name"), _req_str(body, "msgid")
        follow = body.get("follow", False)
        if not isinstance(follow, bool):
            raise _BadRequest("follow must be true or false")
        row, created = actions.register(
            conn, name=name, msgid=msgid, follow=follow, note=_opt_str(body.get("note"), "note"),
            links=_str_list(body.get("links"), "links"), now=int(time.time()))
        try:          # lore only: seconds, not the kernel trail's fetches
            self.runner.start("api", [row["name"]], lore_only=True)
        except fetch.Busy:
            pass              # the next run follows the patch
        return _json(201 if created else 200,
                     actions.add_json(conn, row, lore.parse_msgid(msgid)))

    def _close(self, conn, row, body):
        reason = body.get("reason")
        if not isinstance(reason, str):
            raise _BadRequest("reason must be a string")
        actions.close(conn, self.paths, self.cfg, row, reason, _opt_str(body.get("note"), "note"))

    def _mark_applied(self, conn, row, body):
        actions.mark_applied(conn, self.paths, self.cfg, row, _opt_str(body.get("commit"), "commit"))

    def _skip(self, conn, row, body):
        actions.skip(conn, self.paths, self.cfg, row, _req_str(body, "series"))

    def _unskip(self, conn, row, body):
        actions.unskip(conn, self.paths, self.cfg, row, _req_str(body, "series"))

    def _links(self, conn, row, body):
        add = actions.check_urls(_str_list(body.get("add"), "add"))
        remove = _str_list(body.get("remove"), "remove")
        actions.add_links(conn, row, add, int(time.time()))
        actions.remove_links(conn, row, remove)

    def _note(self, conn, row, body):
        if "note" not in body:
            raise _BadRequest("note is required")
        actions.set_note(conn, row, _opt_str(body["note"], "note"))

    # --- static files -----------------------------------------------------------

    def _static(self, path: str) -> Response:
        root = self.static_dir.resolve()
        rel = unquote(path).lstrip("/")
        if "\0" in rel:
            return _error(404, "not found")
        target = (root / rel).resolve() if rel else root
        if target != root and root not in target.parents:
            return _error(404, "not found")
        try:
            is_file = bool(rel) and target.is_file()
        except OSError:                      # a name too long for the filesystem
            return _error(404, "not found")
        if is_file:
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            headers = {}
            if re.match(r"assets/", rel):
                headers["Cache-Control"] = "max-age=31536000, immutable"
            try:
                return Response(200, target.read_bytes(), ctype, headers)
            except OSError:
                return _error(404, "not found")
        index = root / "index.html"
        if index.is_file():
            return Response(200, index.read_bytes(), "text/html; charset=utf-8",
                            {"Cache-Control": "no-cache"})
        if path == "/":
            return Response(200, NO_BUNDLE, "text/html; charset=utf-8")
        return _error(404, "not found")


_CHANGES: dict[tuple[str, str], Callable] = {
    ("POST", "read"): lambda s, c, r, b: actions.mark_read(c, r),
    ("POST", "unread"): lambda s, c, r, b: actions.mark_unread(c, r),
    ("POST", "hide"): lambda s, c, r, b: actions.hide(c, s.paths, s.cfg, r),
    ("POST", "unhide"): lambda s, c, r, b: actions.unhide(c, r),
    ("POST", "close"): App._close,
    ("POST", "mark-applied"): App._mark_applied,
    ("POST", "skip"): App._skip,
    ("POST", "unskip"): App._unskip,
    ("POST", "links"): App._links,
    ("PUT", "note"): App._note,
}


# --- the server ------------------------------------------------------------------

def parse_listen(listen: str) -> tuple[str, int]:
    m = re.fullmatch(r"\[([^\]]+)\]:(\d+)|([^:\[\]]*):(\d+)", listen)
    if not m:
        raise ValueError(f"bad listen address: {listen} (want HOST:PORT)")
    return (m.group(1), int(m.group(2))) if m.group(1) else (m.group(3), int(m.group(4)))


class _Server6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def _handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 120           # an idle or half-open keep-alive connection frees its thread

        def _serve(self):
            url = urlsplit(self.path)
            resp = None
            raw_len = (self.headers.get("Content-Length") or "0").strip()
            length = int(raw_len) if _NUM.fullmatch(raw_len) else -1
            if self.command not in ("GET", "HEAD") and \
                    "chunked" in self.headers.get("Transfer-Encoding", "").lower():
                resp = _error(411, "chunked bodies are not supported; send Content-Length")
            elif length < 0:
                resp = _error(400, "bad Content-Length")
            elif length > MAX_BODY:
                resp = _error(413, "body too large")
            if resp is not None:
                self.close_connection = True      # the body, if any, was not read
            else:
                req = Request(self.command, url.path, dict(parse_qsl(url.query)),
                              {k.lower(): v for k, v in self.headers.items()},
                              self.rfile.read(length) if length else b"")
                try:
                    resp = app.handle(req)
                except Exception as e:          # a bug must not kill the connection thread
                    print(f"ptl: {self.command} {url.path}: {e!r}", file=sys.stderr)
                    resp = _error(500, "internal error")
            self.send_response(resp.status)
            self.send_header("Content-Type", resp.content_type)
            self.send_header("Content-Length", str(len(resp.body)))
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(resp.body)

        do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _serve

        def log_message(self, fmt, *args):
            pass

    return Handler


def serve(paths: Paths, cfg: Config, listen: str | None = None, *,
          ready: Callable[[str, int], None] | None = None,
          stop: threading.Event | None = None) -> int:
    """Run until SIGTERM, ^C or `stop` is set. ready(host, port) is called once listening."""
    listen = listen or cfg.listen
    host, port = parse_listen(listen)
    runner = Runner(paths, timeout_s=cfg.fetch_timeout_hours * 3600)
    scheduler = Scheduler(runner, paths, interval_s=cfg.interval_hours * 3600)
    app = App(paths, cfg, runner, scheduler)
    try:
        cls = _Server6 if ":" in host else ThreadingHTTPServer
        httpd = cls((host, port), _handler(app))
    except OSError as e:          # socket.gaierror is one too
        if e.errno == errno.EADDRINUSE:
            print(f"ptl: {listen} is in use; is the service running? (ptl service status)",
                  file=sys.stderr)
        else:
            print(f"ptl: cannot listen on {listen}: {e.strerror or e}", file=sys.stderr)
        return 1
    httpd.daemon_threads = True
    stop = stop or threading.Event()
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
    bound_host, bound_port = httpd.server_address[:2]
    shown = f"[{bound_host}]" if ":" in bound_host else bound_host
    print(f"patchtrail {__version__} serving on http://{shown}:{bound_port}", flush=True)
    sched = threading.Thread(target=scheduler.run_forever, args=(stop,), name="scheduler")
    web = threading.Thread(target=httpd.serve_forever, name="http")
    sched.start()
    web.start()
    if ready:
        ready(bound_host, bound_port)
    try:
        while not stop.wait(1):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.shutdown()           # first: no request may start a child from here on
        web.join()
        sched.join()
        runner.terminate()
        httpd.server_close()
    return 0
