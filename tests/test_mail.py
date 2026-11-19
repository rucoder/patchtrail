from mails import make_mail, mbox

from patchtrail import store
from patchtrail.mail import parse_mail, split_mbox, standing, text_body

JENS = """On Wed, 11 Nov 2026 16:27:05 +0000, Me wrote:
> Since commit ...
> [...]

Applied, thanks!

[1/1] io_uring/io-wq: apply the current cpuset to new workers
      commit: 0659e44ce739ecd856164c75a5325b7959a2921d

Best regards,
--
Jens Axboe
"""


def test_applied_commits_and_standing():
    root = parse_mail(make_mail("r@x", subject="[PATCH] io_uring/io-wq: apply the current cpuset to new workers"))
    ty = parse_mail(make_mail("t@x", frm="Jens Axboe <axboe@kernel.dk>", in_reply_to="r@x",
                              subject="Re: [PATCH] io_uring/io-wq: apply the current cpuset to new workers",
                              date="Wed, 18 Nov 2026 09:07:48 -0700", body=JENS))
    assert ty.applied and ty.applied_commits == (("io_uring/io-wq: apply the current cpuset to new workers",
                                                  "0659e44ce739ecd856164c75a5325b7959a2921d"),)
    s = standing([root, ty], frozenset({"me@example.org"}))
    assert s.kind == "applied" and s.text() == "APPLIED by Jens Axboe, 2026-11-18"


def test_two_patch_series_thank_you():
    body = "Applied to kvm-x86 mmu, thanks!\n\n[1/2] KVM: a\n      https://github.com/kvm-x86/linux/commit/aaaaaaaaaaaa\n[2/2] KVM: b\n      commit: bbbbbbbbbbbb\n"
    m = parse_mail(make_mail("t@x", frm="Sean <s@g.com>", subject="Re: [PATCH v2 0/2] KVM: c", body=body, in_reply_to="r@x"))
    assert m.applied_commits == (("KVM: a", "aaaaaaaaaaaa"), ("KVM: b", "bbbbbbbbbbbb"))


def test_waiting_and_your_turn_wording():
    me = frozenset({"me@example.org"})
    root = parse_mail(make_mail("r@x"))
    rb = parse_mail(make_mail("a@x", frm="Tomita Moeko <t@m.org>", subject="Re: [PATCH] fix io",
                              date="Fri, 24 Jul 2026 10:00:00 +0000", in_reply_to="r@x",
                              body="Reviewed-by: Tomita Moeko <t@m.org>\n"))
    assert standing([root], me).text() == "waiting for a reply since 2026-11-11"
    root_jul = parse_mail(make_mail("r@x", date="Fri, 17 Jul 2026 08:49:42 +0000"))
    assert standing([root_jul, rb], me).text() == "Reviewed-by Tomita Moeko; waiting for the maintainer since 2026-07-24"
    q = parse_mail(make_mail("b@x", frm="Jiri Pirko <j@p.org>", subject="Re: [PATCH] fix io",
                             date="Thu, 21 Mar 2024 10:00:00 +0000", in_reply_to="r@x", body="Why?\n"))
    root_2024 = parse_mail(make_mail("r@x", date="Tue, 19 Mar 2024 12:04:10 +0000"))
    assert standing([root_2024, q], me).text() == "Jiri Pirko replied 2024-03-21: your turn"
    assert standing([root_2024, q], me, following=True).text() == "Jiri Pirko replied 2024-03-21"


def test_odd_mail_does_not_raise():
    raws = [make_mail("h@x", html_only=True),
            make_mail("d@x", date="garbage"),
            make_mail("e@x", subject="=?utf-8?q?R=C3=A9sum=C3=A9?=",
                      extra_headers={"Content-Type": "text/plain; charset=iso-8859-1"}, body="caf\xe9\n")]
    infos = [parse_mail(r) for r in raws]
    assert infos[1].date == 0 and infos[2].subject == "Résumé"
    assert text_body(raws[0]) == ("", 1)
    assert text_body(raws[2]) == ("caf\xe9\n", 0)


def test_no_mails_and_fields():
    assert standing([], frozenset()).kind == "none"
    assert standing([], frozenset()).text() == "not fetched yet"
    m = parse_mail(make_mail("c@x", cc="B <b@x.org>", body="change-id: abc123\n"))
    assert m.to_cc == ("list@vger.kernel.org", "b@x.org") and m.change_id == "abc123"
    assert m.from_addr == "me@example.org" and m.from_name == "Me" and not m.is_reply


def test_split_mbox_roundtrip():
    raws = split_mbox(mbox(make_mail("a@x"), make_mail("b@x", body="From here\n")))
    assert [parse_mail(r).msgid for r in raws] == ["a@x", "b@x"]
    assert "From here" in text_body(raws[1])[0]


def test_upsert_mails_returns_only_new(conn):
    pid = store.add_patch(conn, "p", now=1)
    rid = store.add_revision(conn, pid, "a@x")
    assert store.upsert_mails(conn, rid, [make_mail("a@x")], now=5) == ["a@x"]
    assert store.upsert_mails(conn, rid, [make_mail("a@x"), make_mail("b@x")], now=6) == ["b@x"]
    assert len(store.patch_mails(conn, pid)) == 2


def test_mail_infos_sorted_by_date(conn):
    pid = store.add_patch(conn, "p", now=1)
    rid = store.add_revision(conn, pid, "a@x")
    store.upsert_mails(conn, rid, [make_mail("late@x", date="Thu, 12 Nov 2026 12:00:00 +0000"),
                                   make_mail("early@x")], now=5)
    assert [m.msgid for m in store.mail_infos(conn, pid)] == ["early@x", "late@x"]


def test_standing_sorts_by_date():
    me = frozenset({"me@example.org"})
    root = parse_mail(make_mail("r@x"))
    q = parse_mail(make_mail("b@x", frm="Jiri Pirko <j@p.org>", subject="Re: [PATCH] fix io",
                             date="Thu, 12 Nov 2026 10:00:00 +0000", in_reply_to="r@x", body="Why?\n"))
    assert standing([q, root], me).text() == standing([root, q], me).text() \
        == "Jiri Pirko replied 2026-11-12: your turn"


def test_encoded_display_name_with_comma():
    m = parse_mail(make_mail("c@x", frm="=?utf-8?q?M=C3=BCller=2C_Hans?= <h@x.org>",
                             to="=?utf-8?q?Doe=2C_J?= <j@x.org>, k@x.org"))
    assert (m.from_name, m.from_addr) == ("M\xfcller, Hans", "h@x.org")
    assert m.to_cc == ("j@x.org", "k@x.org")
