# SPDX-License-Identifier: Apache-2.0
import http.client
import json
import threading
import time

import pytest

from patchtrail import db, fetch, server
from patchtrail.config import Config, paths


class FakeRunner:
    def __init__(self):
        self.calls, self.busy = [], None

    def start(self, trigger, names=None, lore_only=False):
        if self.busy is not None:
            raise fetch.Busy(self.busy[0])
        self.calls.append((trigger, names, lore_only))

    def starting(self, conn):
        return False

    def terminate(self):
        pass


@pytest.fixture
def runner():
    return FakeRunner()


@pytest.fixture
def static(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html>page</html>")
    (d / "assets" / "x.js").write_text("console.log(1)")
    return d


@pytest.fixture
def app(populated, runner, static):
    return server.App(paths(), Config(), runner, None, static_dir=static)


def call(app, method, path, body=None, *, headers=None, raw=None):
    h = {"host": "10.0.0.1:8470"}
    if method != "GET":
        h["content-type"] = "application/json"
    h.update(headers or {})
    data = raw if raw is not None else (json.dumps(body if body is not None else {}).encode()
                                        if method != "GET" else b"")
    path, _, q = path.partition("?")
    query = dict(p.split("=") for p in q.split("&")) if q else {}
    r = app.handle(server.Request(method, path, query, h, data))
    return r, (json.loads(r.body) if r.content_type == "application/json" else None)


def tree(conn):
    return conn.execute("SELECT name, tree_url, tree_branch FROM patches").fetchall()


def test_status_ok(app):
    r, j = call(app, "GET", "/api/status")
    assert r.status == 200 and j["interval_hours"] == 3 and j["starting"] is False


def test_cards_and_detail(app):
    _, j = call(app, "GET", "/api/patches")
    assert {c["name"] for c in j["patches"]} == {"iowq-cpuset", "erofs"}
    r, j = call(app, "GET", "/api/patches/iowq-cpuset")
    assert r.status == 200 and j["name"] == "iowq-cpuset" and "steps" in j
    r, j = call(app, "GET", "/api/patches/iowq-cpuset/mails")
    assert r.status == 200 and j["groups"]
    r, j = call(app, "GET", "/api/runs/999/log")
    assert r.status == 404


def test_run_log(app, conn):
    cur = conn.execute("INSERT INTO runs(trigger, started_at, status) VALUES ('cli', 1, 'ok')")
    conn.execute("INSERT INTO run_log(run_id, at, line) VALUES (?, 2, 'hello')", (cur.lastrowid,))
    conn.commit()
    r, j = call(app, "GET", f"/api/runs/{cur.lastrowid}/log?after=0")
    assert r.status == 200 and j["lines"][0]["line"] == "hello"
    _, j = call(app, "GET", f"/api/runs/{cur.lastrowid}/log?after={j['lines'][0]['n']}")
    assert j["lines"] == []


def test_unknown_patch_404(app):
    for m, p in [("GET", "/api/patches/nope"), ("GET", "/api/patches/nope/mails"),
                 ("POST", "/api/patches/nope/read"), ("PUT", "/api/patches/nope/note")]:
        r, j = call(app, m, p)
        assert r.status == 404 and "error" in j
    r, j = call(app, "GET", "/api/nothing")
    assert r.status == 404 and "error" in j


ACTIONS = [
    ("read", {}, lambda c: c["unread"] is False),
    ("unread", {}, lambda c: c["unread"] is True),
    ("hide", {}, lambda c: c["hidden"] is True),
    ("unhide", {}, lambda c: c["hidden"] is False),
    ("close", {"reason": "dropped", "note": "meh"}, lambda c: c["closed"] == "dropped"
     and c["closed_note"] == "meh"),
    ("mark-applied", {}, lambda c: c["name"] == "erofs"),
    ("skip", {"series": "6.1"}, lambda c: c["name"] == "erofs"),
    ("unskip", {"series": "6.1"}, lambda c: c["name"] == "erofs"),
    ("links", {"add": ["https://example.org/pr/1"]},
     lambda c: [lk["url"] for lk in c["links"]] == ["https://example.org/pr/1"]),
    ("links", {"remove": ["https://example.org/pr/1"]}, lambda c: c["links"] == []),
]


def test_actions_return_card(app):
    for action, body, ok in ACTIONS:
        r, j = call(app, "POST", f"/api/patches/erofs/{action}", body)
        assert r.status == 200, (action, j)
        assert ok(j), (action, j)


def test_action_bad_input_400(app):
    for action, body in [("close", {"reason": "bogus"}), ("close", {}),
                         ("mark-applied", {"commit": "zz"}), ("skip", {"series": "x"}),
                         ("links", {"add": ["ftp://x"]}), ("links", {"add": "no"})]:
        r, j = call(app, "POST", f"/api/patches/erofs/{action}", body)
        assert r.status == 400 and "error" in j, action


def test_bad_json_400(app):
    r, j = call(app, "POST", "/api/patches/erofs/read", raw=b"{nope")
    assert r.status == 400
    r, _ = call(app, "POST", "/api/patches/erofs/read", raw=b"[1]")
    assert r.status == 400


def test_note_put(app):
    r, j = call(app, "PUT", "/api/patches/erofs/note", {"note": "hello"})
    assert r.status == 200 and j["note"] == "hello"
    r, j = call(app, "PUT", "/api/patches/erofs/note", {"note": None})
    assert j["note"] is None
    assert call(app, "PUT", "/api/patches/erofs/note", {})[0].status == 400


def test_register_201_200_409_400(app):
    r, j = call(app, "POST", "/api/patches", {"name": "newp", "msgid": "new1@x",
                                              "note": "n", "links": ["https://e.org/1"]})
    assert r.status == 201 and j["name"] == "newp" and j["note"] == "n"
    r, j = call(app, "POST", "/api/patches", {"name": "other", "msgid": "new1@x"})
    assert r.status == 200 and j["name"] == "newp"
    assert [c[1] for c in app.runner.calls] == [["newp"], ["newp"]]    # fetched on repeats too
    r, j = call(app, "POST", "/api/patches", {"name": "erofs", "msgid": "new2@x"})
    assert r.status == 409
    for body in ({"name": "bad name", "msgid": "a@b"}, {"name": "x", "msgid": "nomsgid"},
                 {"msgid": "a@b"}, {"name": "x", "msgid": "a@b", "links": ["ftp://x"]}):
        assert call(app, "POST", "/api/patches", body)[0].status == 400, body


def test_register_refuses_a_msgid_b4_reads_as_a_url(app, runner, conn):  # final review C1
    revs = conn.execute("SELECT COUNT(*) FROM revisions").fetchone()[0]
    for msgid in ("https://lore.kernel.org/all/http:%2F%2F127.0.0.1:8443%2Fl%2Fa@b",
                  "<http://127.0.0.1:8443/l/a@b>"):
        r, j = call(app, "POST", "/api/patches", {"name": "evil", "msgid": msgid})
        assert r.status == 400 and "not a Message-ID" in j["error"], msgid
    assert conn.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == revs
    assert conn.execute("SELECT 1 FROM patches WHERE name='evil'").fetchone() is None
    assert runner.calls == []

def test_register_starts_lore_only_fetch(app, runner):
    call(app, "POST", "/api/patches", {"name": "newp", "msgid": "new1@x"})
    assert runner.calls == [("api", ["newp"], True)]
    runner.busy = (None,)
    r, _ = call(app, "POST", "/api/patches", {"name": "newq", "msgid": "new3@x"})
    assert r.status == 201


def test_fetch_now_202(app, runner):
    r, j = call(app, "POST", "/api/fetch")
    assert r.status == 202 and "version" in j and runner.calls == [("page", None, False)]


def test_fetch_now_conflict(app, runner, conn):
    cur = conn.execute("INSERT INTO runs(trigger, started_at, status) VALUES ('cli', 1, 'running')")
    conn.commit()
    runner.busy = (conn.execute("SELECT * FROM runs WHERE id=?", (cur.lastrowid,)).fetchone(),)
    r, j = call(app, "POST", "/api/fetch")
    assert r.status == 409 and j["running"]["id"] == cur.lastrowid


def test_cross_origin_refused(app, conn):
    before = [tuple(r) for r in conn.execute("SELECT name, read_snapshot_id FROM patches")]
    r, j = call(app, "POST", "/api/patches/erofs/hide",
                headers={"origin": "http://evil.example"})
    assert r.status == 403
    r, _ = call(app, "POST", "/api/patches", {"name": "x", "msgid": "a@b"},
                headers={"origin": "http://evil.example"})
    assert r.status == 403
    assert conn.execute("SELECT hidden FROM patches WHERE name='erofs'").fetchone()[0] == 0
    assert [tuple(r) for r in conn.execute("SELECT name, read_snapshot_id FROM patches")] == before
    r, _ = call(app, "POST", "/api/patches/erofs/hide", headers={"origin": "http://10.0.0.1:8470"})
    assert r.status == 200


# --- plan 2 final review I6: DNS rebinding -------------------------------------

def test_dns_rebinding_host_refused(app, conn):
    h = {"host": "rebind.example:8470", "origin": "http://rebind.example:8470"}
    r, j = call(app, "POST", "/api/patches/erofs/hide", headers=h)
    assert r.status == 403
    assert j["error"] == "unknown Host rebind.example; add it to hosts in config.toml"
    r, _ = call(app, "POST", "/api/patches", {"name": "x", "msgid": "a@b"}, headers=h)
    assert r.status == 403 and app.runner.calls == []
    for path in ("/api/status", "/api/patches", "/api/patches/erofs/mails"):
        assert call(app, "GET", path, headers=h)[0].status == 403, path
    assert conn.execute("SELECT hidden FROM patches WHERE name='erofs'").fetchone()[0] == 0
    assert conn.execute("SELECT 1 FROM patches WHERE name='x'").fetchone() is None
    assert call(app, "GET", "/", headers=h)[0].status == 200          # the page itself is static


def test_ip_literal_hosts_pass(app):
    for host in ("10.0.0.1:8470", "127.0.0.1", "[::1]:8470", "[fe80::1]", "192.0.2.7:1"):
        assert call(app, "GET", "/api/status", headers={"host": host})[0].status == 200, host
        r, _ = call(app, "POST", "/api/patches/erofs/read",
                    headers={"host": host, "origin": "http://" + host})
        assert r.status == 200, host
    for host in ("10.0.0.1.rebind.example:8470", "[not-an-ip]:8470", "::1", ""):
        assert call(app, "GET", "/api/status", headers={"host": host})[0].status == 403, host


def test_own_host_names_pass(populated, runner, static, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "gethostname", lambda: "BuildBox")
    monkeypatch.setattr(socket, "getfqdn", lambda *a: "buildbox.lan.example.org")
    app = server.App(paths(), Config(), runner, None, static_dir=static)
    for host in ("localhost:8470", "LOCALHOST", "buildbox:8470", "BUILDBOX",
                 "buildbox.lan.example.org:8470", "buildbox.lan.example.org."):
        assert call(app, "GET", "/api/status", headers={"host": host})[0].status == 200, host
    for host in ("buildbox.rebind.example", "localhost.rebind.example:8470"):
        assert call(app, "GET", "/api/status", headers={"host": host})[0].status == 403, host


def test_configured_hosts_pass(populated, runner, static):
    app = server.App(paths(), Config(hosts=["ptl.example.org", "Alias.Example.org:8470"]), runner,
                     None, static_dir=static)
    for host in ("ptl.example.org:8470", "PTL.example.org", "alias.example.org:9"):
        assert call(app, "GET", "/api/status", headers={"host": host})[0].status == 200, host
    assert call(app, "GET", "/api/status", headers={"host": "other.example.org"})[0].status == 403


def test_handler_times_out_idle_connections():                  # final review M2
    assert server._handler(None).timeout == 120

def test_form_post_refused(app):
    r, _ = call(app, "POST", "/api/patches/erofs/hide", headers={"content-type": "text/plain"})
    assert r.status == 415
    r, _ = call(app, "POST", "/api/patches/erofs/hide", headers={"content-type": "text/plain"},
                raw=b"{}")
    assert r.status == 415
    r, _ = call(app, "POST", "/api/patches/erofs/hide",
                headers={"content-type": "application/json; charset=utf-8"})
    assert r.status == 200


def test_agent_post_without_origin(app):
    r, _ = call(app, "POST", "/api/patches", {"name": "agent", "msgid": "ag@x"})
    assert r.status == 201


def test_no_route_sets_tree(app, conn):
    evil = {"tree_url": "https://evil.example/x.git", "tree_branch": "master",
            "reason": "dropped", "series": "6.1", "note": "n"}
    for action in ("read", "unread", "hide", "unhide", "close", "mark-applied", "skip",
                   "unskip", "links"):
        call(app, "POST", f"/api/patches/erofs/{action}", evil)
    call(app, "PUT", "/api/patches/erofs/note", evil)
    call(app, "POST", "/api/patches", {"name": "np", "msgid": "np@x", **evil})
    assert all(r["tree_url"] is None and r["tree_branch"] is None for r in tree(conn))
    for m, p in [("DELETE", "/api/patches/erofs"), ("POST", "/api/patches/erofs/rename"),
                 ("POST", "/api/patches/erofs/merge"), ("POST", "/api/patches/erofs/split"),
                 ("PUT", "/api/patches/erofs/tree")]:
        assert call(app, m, p)[0].status == 404, (m, p)
    assert conn.execute("SELECT COUNT(*) FROM patches WHERE name='erofs'").fetchone()[0] == 1


def test_spa_fallback_and_assets(app):
    r, _ = call(app, "GET", "/p/foo/thread")
    assert r.status == 200 and r.body == b"<html>page</html>"
    assert r.headers["Cache-Control"] == "no-cache" and r.content_type.startswith("text/html")
    r, _ = call(app, "GET", "/assets/x.js")
    assert r.status == 200 and r.body == b"console.log(1)"
    assert r.headers["Cache-Control"] == "max-age=31536000, immutable"
    assert "javascript" in r.content_type
    for p in ("/../pyproject.toml", "/%2e%2e/pyproject.toml", "/assets/../../x", "/%2e%2e%2f"):
        assert call(app, "GET", p)[0].status == 404, p
    (app.static_dir.parent / "secret.txt").write_text("secret")
    r, _ = call(app, "GET", "/%2e%2e/secret.txt")
    assert r.status == 404 and b"secret" not in r.body
    r, _ = call(app, "GET", "/../secret.txt")
    assert r.status == 404 and b"secret" not in r.body


def test_long_path_404(app):
    r, _ = call(app, "GET", "/" + "a" * 300)
    assert r.status == 404 or r.body == b"<html>page</html>"
    assert call(app, "GET", "/assets/" + "a" * 300)[0].status in (200, 404)


def test_bad_run_ids_and_after(app):
    for p in ("/api/runs/%C2%B2/log", "/api/runs/99999999999999999999/log"):
        assert call(app, "GET", p)[0].status == 404, p
    for p in ("/api/runs/1/log?after=99999999999999999999", "/api/runs/1/log?after=%C2%B2",
              "/api/runs/1/log?after=-1", "/api/runs/1/log?after=x"):
        assert call(app, "GET", p)[0].status == 400, p


def test_deeply_nested_json_400(app):
    r, _ = call(app, "POST", "/api/patches/erofs/read", raw=b"[" * 200000)
    assert r.status == 400


def test_origin_without_host_and_other_methods(app):
    r, _ = call(app, "POST", "/api/patches/erofs/hide",
                headers={"origin": "http://10.0.0.1:8470", "host": ""})
    assert r.status == 403          # empty Host: no match
    h = {"origin": "http://evil.example"}
    assert call(app, "PUT", "/api/patches/erofs/note", {"note": "x"}, headers=h)[0].status == 403
    assert call(app, "DELETE", "/api/patches/erofs", headers=h)[0].status == 403
    r = app.handle(server.Request("POST", "/api/patches/erofs/hide", {},
                                  {"origin": "http://10.0.0.1:8470",
                                   "content-type": "application/json"}, b"{}"))
    assert r.status == 403          # no Host header at all


def test_urlencoded_post_415(app):
    r, _ = call(app, "POST", "/api/patches/erofs/hide",
                headers={"content-type": "application/x-www-form-urlencoded"}, raw=b"a=b")
    assert r.status == 415


def test_no_bundle_page(populated, runner, tmp_path):
    app = server.App(paths(), Config(), runner, None, static_dir=tmp_path / "empty")
    r, _ = call(app, "GET", "/")
    assert r.status == 200 and b"was not built" in r.body and b"/api/status" in r.body


def test_parse_listen():
    assert server.parse_listen("0.0.0.0:8470") == ("0.0.0.0", 8470)
    assert server.parse_listen("[::1]:9") == ("::1", 9)
    with pytest.raises(ValueError):
        server.parse_listen("nonsense")


@pytest.fixture
def live(populated):
    # A recent run keeps the scheduler from starting a real fetch child.
    populated.execute("INSERT INTO runs(trigger, started_at, finished_at, status) "
                      "VALUES ('cli', ?, ?, 'ok')", (int(time.time()),) * 2)
    populated.commit()
    started, stop, out = threading.Event(), threading.Event(), {}

    def ready(host, port):
        out["port"] = port
        started.set()

    t = threading.Thread(target=lambda: out.update(rc=server.serve(
        paths(), Config(), "127.0.0.1:0", ready=ready, stop=stop)))
    t.start()
    assert started.wait(10)
    yield out["port"]
    stop.set()
    t.join(30)
    assert not t.is_alive() and out["rc"] == 0


def _raw(port, lines: list[str], body: bytes = b"") -> tuple[int, bytes]:
    import socket

    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
        data = b""
        while chunk := s.recv(65536):
            data += chunk
            if b"\r\n\r\n" in data and data.endswith(b"}"):
                break
    return int(data.split(b" ", 2)[1]), data


def test_bad_content_length(live):
    base = ["POST /api/patches/erofs/read HTTP/1.1", "Host: x", "Content-Type: application/json",
            "Connection: close"]
    for cl in ("-1", "abc", "1.5", "\u00b2"):
        status, _ = _raw(live, base + [f"Content-Length: {cl}"])
        assert status == 400, cl
    assert _raw(live, base + [f"Content-Length: {1 << 21}"])[0] == 413


def test_chunked_body_411(live):
    status, _ = _raw(live, ["POST /api/patches/erofs/read HTTP/1.1", "Host: x",
                            "Content-Type: application/json", "Transfer-Encoding: chunked",
                            "Connection: close"], b"2\r\n{}\r\n0\r\n\r\n")
    assert status == 411


def test_long_path_over_socket(live):
    status, _ = _raw(live, ["GET /" + "a" * 300 + " HTTP/1.1", "Host: x", "Connection: close"])
    assert status in (200, 404)        # served as the page; never a 500


def test_serve_ipv6(populated, capsys):
    import socket

    if not socket.has_ipv6:
        pytest.skip("no IPv6")
    populated.execute("INSERT INTO runs(trigger, started_at, status) VALUES ('cli', ?, 'ok')",
                      (int(time.time()),))
    populated.commit()
    started, stop, out = threading.Event(), threading.Event(), {}
    t = threading.Thread(target=lambda: out.update(rc=server.serve(
        paths(), Config(), "[::1]:0", ready=lambda h, p: (out.update(port=p), started.set()),
        stop=stop)))
    t.start()
    try:
        if not started.wait(5):
            t.join(5)
            pytest.skip("no IPv6 loopback")
        c = http.client.HTTPConnection("::1", out["port"], timeout=10)
        c.request("GET", "/api/patches/nope")
        assert c.getresponse().status == 404
    finally:
        stop.set()
        t.join(30)


def test_serve_unresolvable_host(populated, capsys):
    assert server.serve(paths(), Config(), "no-such-host.invalid:80") == 1
    assert "ptl: cannot listen on no-such-host.invalid:80:" in capsys.readouterr().err


def test_shutdown_stops_http_before_runner(populated, monkeypatch):
    order, stop = [], threading.Event()
    populated.execute("INSERT INTO runs(trigger, started_at, status) VALUES ('cli', ?, 'ok')",
                      (int(time.time()),))
    populated.commit()
    monkeypatch.setattr(server.Runner, "terminate", lambda self: order.append("terminate"))
    orig = server.ThreadingHTTPServer.shutdown
    monkeypatch.setattr(server.ThreadingHTTPServer, "shutdown",
                        lambda self: (order.append("shutdown"), orig(self)))
    stop.set()
    assert server.serve(paths(), Config(), "127.0.0.1:0", stop=stop) == 0
    assert order == ["shutdown", "terminate"]


def test_serve_socket_roundtrip(populated, capsys):
    # A recent run keeps the scheduler from starting a real fetch child.
    populated.execute("INSERT INTO runs(trigger, started_at, finished_at, status) "
                      "VALUES ('cli', ?, ?, 'ok')", (int(time.time()),) * 2)
    populated.commit()
    started, stop, out = threading.Event(), threading.Event(), {}

    def ready(host, port):
        out["port"] = port
        started.set()

    t = threading.Thread(target=lambda: out.update(rc=server.serve(
        paths(), Config(), "127.0.0.1:0", ready=ready, stop=stop)))
    t.start()
    try:
        assert started.wait(10)
        c = http.client.HTTPConnection("127.0.0.1", out["port"], timeout=10)
        c.request("GET", "/api/status")
        r = c.getresponse()
        assert r.status == 200 and json.loads(r.read())["interval_hours"] == 3
        c.request("POST", "/api/fetch", b"{}", {"Content-Type": "text/plain"})
        r = c.getresponse()
        r.read()
        assert r.status == 415
        c.close()
    finally:
        stop.set()
        t.join(30)
    assert not t.is_alive() and out["rc"] == 0
    assert "serving on http://127.0.0.1:" in capsys.readouterr().out


def test_serve_port_in_use(populated, capsys):
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    try:
        assert server.serve(paths(), Config(), f"127.0.0.1:{s.getsockname()[1]}") == 1
    finally:
        s.close()
    assert "is in use" in capsys.readouterr().err


def test_wheel_contains_bundle(tmp_path):
    import shutil
    import subprocess
    import zipfile
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    if not (root / "src/patchtrail/web/dist/index.html").is_file():
        pytest.skip("web page not built (run `make web`)")
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not on PATH")
    subprocess.run([uv, "build", "--wheel", "-o", str(tmp_path)], cwd=root, check=True,
                   capture_output=True)
    [wheel] = tmp_path.glob("patchtrail-*.whl")
    assert "patchtrail/web/dist/index.html" in zipfile.ZipFile(wheel).namelist()
