# Copyright (C) 2026 Nadav Har'El
# SPDX-License-Identifier: AGPL-3.0-or-later

import re

import pytest
from conftest import csrf, make_cfg, send

from greetings import auth, db
from greetings.web import create_app


def post(client, path, **data):
    return client.post(path, data={"csrf": csrf(client, "/admin"), **data})


def test_admin_lists_newest_first(app, client):
    send(app.test_client(), "א", "ראשונה")
    send(app.test_client(), "ב", "שנייה")
    html = client.get("/admin").get_data(as_text=True)
    assert html.index("שנייה") < html.index("ראשונה")
    assert "2</strong> ברכות" in html


def test_admin_edit_keeps_revision(app, client, cfg):
    send(app.test_client(), "א", "טעות")
    gid = db.all_greetings(db.connect(cfg.db_path))[0].id
    r = post(client, f"/admin/{gid}", name="א", body="תיקון")
    assert r.status_code == 302
    conn = db.connect(cfg.db_path)
    assert db.get(conn, gid).body == "תיקון"
    assert db.revisions(conn, gid)[0]["body"] == "טעות"
    assert "נערכה" in client.get("/admin").get_data(as_text=True)


def test_admin_may_exceed_length_limit(app, client, cfg):
    send(app.test_client(), "א", "ב" * 300)
    gid = db.all_greetings(db.connect(cfg.db_path))[0].id
    assert post(client, f"/admin/{gid}", name="א", body="ב" * 301).status_code == 302


def test_delete_and_restore(app, client, cfg):
    send(app.test_client(), "א", "ברכה")
    gid = db.all_greetings(db.connect(cfg.db_path))[0].id
    post(client, f"/admin/{gid}/delete")
    assert db.all_greetings(db.connect(cfg.db_path)) == []
    assert "ברכות שנמחקו (1)" in client.get("/admin").get_data(as_text=True)
    post(client, f"/admin/{gid}/restore")
    assert len(db.all_greetings(db.connect(cfg.db_path))) == 1


def test_admin_post_needs_csrf(app, client, cfg):
    send(app.test_client(), "א", "ברכה")
    gid = db.all_greetings(db.connect(cfg.db_path))[0].id
    assert client.post(f"/admin/{gid}/delete", data={"csrf": "x"}).status_code == 400
    assert len(db.all_greetings(db.connect(cfg.db_path))) == 1


def test_close_and_open_form(client, cfg):
    post(client, "/admin/form", open="0")
    assert not db.form_open(db.connect(cfg.db_path))
    post(client, "/admin/form", open="1")
    assert db.form_open(db.connect(cfg.db_path))


def test_print_and_csv(app, client):
    send(app.test_client(), "אורח", "מזל טוב, \"יקירה\"\nשורה שנייה")
    html = client.get("/admin/print").get_data(as_text=True)
    assert "אורח" in html and "1 ברכות" in html
    r = client.get("/admin/greetings.csv")
    text = r.get_data(as_text=True)
    assert text.startswith("﻿") and "אורח" in text
    assert '"מזל טוב, ""יקירה""\nשורה שנייה"' in text


def test_screen_api_versions(app, client):
    r = client.get("/screen/api/greetings")
    data = r.get_json()
    assert data["greetings"] == []
    etag = r.headers["ETag"]
    # Check that an unchanged list costs a 304.
    assert client.get("/screen/api/greetings", headers={"If-None-Match": etag}).status_code == 304
    send(app.test_client(), "א", "ברכה")
    r = client.get("/screen/api/greetings", headers={"If-None-Match": etag})
    assert r.status_code == 200
    assert [g["body"] for g in r.get_json()["greetings"]] == ["ברכה"]


def test_qr_svg(client):
    r = client.get("/qr.svg")
    assert r.headers["Content-Type"] == "image/svg+xml"
    assert r.get_data(as_text=True).startswith("<svg")
    assert 'fill="#fff"' in client.get("/qr.svg?on=dark").get_data(as_text=True) or \
        "#fff" in client.get("/qr.svg?on=dark").get_data(as_text=True)


# ------------------------------------------------------------ with login

@pytest.fixture
def guarded(tmp_path):
    a = create_app(make_cfg(tmp_path), require_login=True)
    a.testing = True
    return a


@pytest.mark.parametrize("path", ["/admin", "/screen", "/admin/print",
                                  "/admin/greetings.csv", "/admin/1", "/admin/qr"])
def test_private_pages_need_login(guarded, path):
    r = guarded.test_client().get(path)
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_private_posts_need_login(guarded):
    c = guarded.test_client()
    send(c, "א", "ברכה")
    tok = csrf(c)
    assert c.post("/admin/1/delete", data={"csrf": tok}).status_code == 302
    assert c.get("/screen/api/greetings").status_code == 401


def test_guest_form_needs_no_login(guarded):
    assert guarded.test_client().get("/").status_code == 200


def login_as(client, email):
    with client.session_transaction() as s:
        s[auth.SESSION_ADMIN] = email


def test_admin_allowed(guarded):
    c = guarded.test_client()
    login_as(c, "Mom@Example.com")
    assert c.get("/admin").status_code == 200
    assert c.get("/screen/api/greetings").status_code == 200


def test_non_admin_refused(guarded):
    c = guarded.test_client()
    login_as(c, "stranger@example.com")
    assert c.get("/admin").status_code == 302


def test_login_page_without_google(guarded):
    html = guarded.test_client().get("/login").get_data(as_text=True)
    assert "לא הוגדרה" in html


def test_google_callback_checks_allowlist(tmp_path, monkeypatch):
    from greetings import google_auth
    cfg = make_cfg(tmp_path, base_url="https://greetings.example",
                   google={"enabled": True, "client_id": "id", "client_secret": "s"})
    a = create_app(cfg, require_login=True)
    c = a.test_client()
    r = c.get("/auth/google?next=/screen")
    state = re.search(r"state=([^&]+)", r.headers["Location"]).group(1)
    for email, ok in (("stranger@example.com", False), ("mom@example.com", True)):
        monkeypatch.setattr(google_auth, "complete",
                            lambda *a, email=email, **k: (google_auth.Identity(email, "x"), "/screen"))
        r = c.get(f"/auth/google/callback?code=c&state={state}")
        assert ("/screen" == r.headers["Location"]) == ok, email
    assert c.get("/screen").status_code == 200


def test_safe_next():
    assert auth.safe_next("//evil.com") == "/admin"
    assert auth.safe_next("https://evil.com") == "/admin"
    assert auth.safe_next("/screen") == "/screen"
