# Copyright (C) 2026 Nadav Har'El
# SPDX-License-Identifier: AGPL-3.0-or-later

from conftest import csrf, send

from greetings import db


def rows(cfg):
    return db.all_greetings(db.connect(cfg.db_path))


def test_form_is_hebrew_rtl(client):
    html = client.get("/").get_data(as_text=True)
    assert '<html lang="he" dir="rtl">' in html
    assert "שליחה" in html


def test_send_greeting_sets_cookie_and_thanks(client, cfg):
    r = send(client, "סבתא רחל", "מזל טוב!")
    assert r.status_code == 302 and r.headers["Location"].endswith("/thanks")
    assert "greeting=" in r.headers["Set-Cookie"]
    assert "HttpOnly" in r.headers["Set-Cookie"]
    [g] = rows(cfg)
    assert (g.name, g.body) == ("סבתא רחל", "מזל טוב!")
    html = client.get("/thanks").get_data(as_text=True)
    assert "מזל טוב!" in html


def test_cookie_holds_no_plain_token_in_db(client, cfg):
    send(client, "a", "b")
    token = client.get_cookie("greeting").value
    conn = db.connect(cfg.db_path)
    owner = conn.execute("SELECT owner FROM greetings").fetchone()[0]
    assert owner != token and len(owner) == 64


def test_returning_guest_edits_instead_of_adding(client, cfg):
    send(client, "דוד", "ברכה ראשונה")
    html = client.get("/").get_data(as_text=True)
    # Check that the form comes back filled in, as an edit.
    assert "ברכה ראשונה" in html and "שמירת השינויים" in html
    send(client, "דוד", "ברכה מתוקנת")
    [g] = rows(cfg)
    assert g.body == "ברכה מתוקנת"
    revs = db.revisions(db.connect(cfg.db_path), g.id)
    assert [r["body"] for r in revs] == ["ברכה ראשונה"]
    assert revs[0]["edited_by"] == "guest"


def test_two_guests_two_greetings(app, cfg):
    send(app.test_client(), "א", "ברכה 1")
    send(app.test_client(), "ב", "ברכה 2")
    assert [g.body for g in rows(cfg)] == ["ברכה 1", "ברכה 2"]


def test_deleted_greeting_gives_fresh_form(client, cfg):
    send(client, "א", "ברכה")
    conn = db.connect(cfg.db_path)
    db.set_deleted(conn, rows(cfg)[0].id, True)
    html = client.get("/").get_data(as_text=True)
    assert "שליחה" in html and "שמירת השינויים" not in html
    send(client, "א", "ברכה חדשה")
    assert [g.body for g in rows(cfg)] == ["ברכה חדשה"]


def test_empty_fields_refused(client, cfg):
    r = send(client, "  ", "   \n ")
    assert r.status_code == 400
    html = r.get_data(as_text=True)
    assert "נא לכתוב את שמך" in html and "נא לכתוב ברכה" in html
    assert rows(cfg) == []


def test_length_limits(client, cfg):
    r = send(client, "א" * 41, "ב")
    assert r.status_code == 400
    r = send(client, "א", "ב" * 301)
    assert r.status_code == 400 and "עד 300 תווים" in r.get_data(as_text=True)
    # Check that the text the guest typed is kept for them to shorten.
    assert "ב" * 301 in r.get_data(as_text=True)
    # Check that emoji count as one character each, as the counter does.
    r = send(client, "א", "🎉" * 300)
    assert r.status_code == 302


def test_text_is_cleaned(client, cfg):
    send(client, "  רחל \n כהן ", "שורה\r\n\r\n\r\n\r\nשורה‮ הפוך\x07")
    [g] = rows(cfg)
    assert g.name == "רחל כהן"
    assert g.body == "שורה\n\nשורה הפוך"


def test_text_is_escaped(client):
    send(client, "<b>x</b>", "<script>alert(1)</script>")
    html = client.get("/thanks").get_data(as_text=True)
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html


def test_csrf_required(client, cfg):
    client.get("/")
    r = client.post("/", data={"csrf": "wrong", "name": "a", "body": "b"})
    assert r.status_code == 400
    assert rows(cfg) == []


def test_closed_form(client, cfg):
    send(client, "א", "ברכה")
    db.set_form_open(db.connect(cfg.db_path), False)
    assert "הסתיימה" in client.get("/").get_data(as_text=True)
    r = client.post("/", data={"name": "a", "body": "b"})
    assert "הסתיימה" in r.get_data(as_text=True)
    assert [g.body for g in rows(cfg)] == ["ברכה"]


def test_rate_limit_new_greetings(tmp_path):
    from conftest import make_cfg
    from greetings.web import create_app
    app = create_app(make_cfg(tmp_path, new_per_minute=2), require_login=False)
    for i in range(2):
        assert send(app.test_client(), "a", f"b{i}").status_code == 302
    assert send(app.test_client(), "a", "b").status_code == 429
