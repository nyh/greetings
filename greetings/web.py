"""The web application: the guest form, the screen and the family's page.

| URL                    | who        |
|------------------------|------------|
| ``/``                  | guests     |
| ``/screen``            | the family |
| ``/admin``             | the family |

``create_app(cfg, require_login=False)`` turns the sign-in off entirely, for
working on the interface on your own machine.
"""

# Copyright (C) 2026 Nadav Har'El
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import csv
import functools
import hashlib
import io
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    Flask, Response, abort, g, jsonify, make_response, redirect,
    render_template, request, session, url_for,
)

from . import auth, db, google_auth, qr
from .config import Config

log = logging.getLogger("greetings")

STATIC_DIR = Path(__file__).parent / "static"

GUEST_COOKIE_DAYS = 365

# Unicode controls that would let one greeting reorder the text around it on
# screen (bidi overrides and isolates), plus the C0/C1 controls. Newlines are
# kept in a greeting, and joiners are kept because emoji are built from them.
_BIDI = "‪‫‬‭‮⁦⁧⁨⁩‎‏"
_STRIP = re.compile(f"[\\x00-\\x09\\x0b-\\x1f\\x7f-\\x9f{_BIDI}]")


def clean_name(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _STRIP.sub("", text.replace("\n", " "))
    return " ".join(text.split())


def clean_body(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = _STRIP.sub("", text)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def length(text: str) -> int:
    """Characters as a person counts them. The form's counter counts the same
    way (code points), so the two never disagree about the limit."""
    return len(text)


def _assets_version() -> str:
    """A digest of the static files, appended to their URLs, so a changed
    stylesheet is fetched again instead of being taken from a cache."""
    h = hashlib.sha256()
    for p in sorted(STATIC_DIR.iterdir()):
        if p.is_file():
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def create_app(cfg: Config, *, require_login: bool = True) -> Flask:
    app = Flask(__name__)
    if cfg.behind_proxy:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init(cfg.db_path)
    app.secret_key = auth.secret_key(cfg.secret_key_path)
    secure = cfg.base_url.startswith("https://")
    app.config.update(
        SESSION_COOKIE_NAME="greetings_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=secure,
        PERMANENT_SESSION_LIFETIME=timedelta(days=cfg.session_days),
        REQUIRE_LOGIN=require_login,
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    tz = ZoneInfo(cfg.timezone)
    limiter = auth.RateLimit(cfg.new_per_minute)
    assets_v = _assets_version()

    # ---------------------------------------------------------- plumbing

    def conn():
        if "db" not in g:
            g.db = db.connect(cfg.db_path)
        return g.db

    @app.teardown_appcontext
    def _close(exc):
        c = g.pop("db", None)
        if c is not None:
            c.close()

    def public_url() -> str:
        """The guests' address, as printed in the QR code."""
        return cfg.base_url or request.host_url.rstrip("/")

    @app.context_processor
    def _globals():
        return {
            "cfg": cfg,
            "csrf_token": auth.csrf_token,
            "static": lambda name: url_for("static", filename=name, v=assets_v),
            "public_url": public_url,
            "require_login": require_login,
            "admin_email": auth.admin_email(),
        }

    @app.template_filter("localtime")
    def _localtime(iso: str | None, fmt: str = "%H:%M") -> str:
        if not iso:
            return ""
        return datetime.fromisoformat(iso).astimezone(tz).strftime(fmt)

    @app.after_request
    def _headers(resp: Response) -> Response:
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.path.startswith("/static/") and request.args.get("v"):
            # Safe because the URL changes whenever the file does.
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif request.path.startswith("/static/"):
            # Files reached without ?v=, such as rotation.js imported by
            # screen.js: check for a newer copy every time.
            resp.headers["Cache-Control"] = "no-cache"
        else:
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def admin_only(fn=None, *, api: bool = False):
        def wrap(f):
            @functools.wraps(f)
            def inner(*a, **kw):
                if require_login and not auth.is_admin(cfg.admins):
                    if api:
                        return jsonify(error="login required"), 401
                    return redirect(url_for("login", next=request.full_path.rstrip("?")))
                return f(*a, **kw)
            return inner
        return wrap(fn) if fn else wrap

    def editor() -> str:
        return auth.admin_email() or "local"

    @app.route("/healthz")
    def healthz():
        conn().execute("SELECT 1")
        return "ok\n", 200, {"Content-Type": "text/plain"}

    # ---------------------------------------------------------- guests

    def validate(name: str, body: str, *, limits: bool = True) -> list[str]:
        errors = []
        if not name:
            errors.append("נא לכתוב את שמך.")
        elif limits and length(name) > cfg.max_name:
            errors.append(f"השם ארוך מדי: עד {cfg.max_name} תווים, בבקשה.")
        if not body:
            errors.append("נא לכתוב ברכה.")
        elif limits and length(body) > cfg.max_length:
            errors.append(f"הברכה ארוכה מדי: עד {cfg.max_length} תווים, בבקשה.")
        return errors

    def form_page(greeting, name="", body="", errors=(), status=200):
        return render_template(
            "form.html", greeting=greeting, name=name, body=body, errors=errors,
        ), status

    @app.get("/")
    def guest_form():
        if not db.form_open(conn()):
            return render_template("closed.html")
        mine = db.by_owner(conn(), auth.guest_owner()) if auth.guest_owner() else None
        if mine:
            return form_page(mine, mine.name, mine.body)
        return form_page(None)

    @app.post("/")
    def guest_submit():
        c = conn()
        if not db.form_open(c):
            return render_template("closed.html")
        owner = auth.guest_owner()
        mine = db.by_owner(c, owner) if owner else None
        name = clean_name(request.form.get("name", ""))
        body = clean_body(request.form.get("body", ""))
        if not auth.check_csrf():
            return form_page(mine, name, body,
                             ["הטופס פג תוקף. נא לשלוח שוב."], 400)
        errors = validate(name, body)
        if errors:
            return form_page(mine, name, body, errors, 400)
        if mine:
            db.update(c, mine.id, name, body, by="guest")
            return redirect(url_for("thanks"))
        if not limiter.allow(request.remote_addr or ""):
            return form_page(None, name, body,
                             ["נשלחו יותר מדי ברכות מהרשת הזאת בזמן קצר. "
                              "נא לנסות שוב בעוד דקה."], 429)
        token = auth.new_guest_token()
        gid = db.add(c, name, body, auth.owner_of(token))
        log.info("new greeting %d from %s", gid, request.remote_addr)
        resp = redirect(url_for("thanks"))
        resp.set_cookie(
            auth.GUEST_COOKIE, token, max_age=GUEST_COOKIE_DAYS * 86400,
            httponly=True, samesite="Lax", secure=secure,
        )
        return resp

    @app.get("/thanks")
    def thanks():
        owner = auth.guest_owner()
        mine = db.by_owner(conn(), owner) if owner else None
        if not mine:
            return redirect(url_for("guest_form"))
        return render_template("thanks.html", greeting=mine)

    @app.get("/qr.svg")
    def qr_svg():
        # White modules for a dark background (?on=dark); never a color taken
        # from the request, which would go straight into the SVG.
        color = "#fff" if request.args.get("on") == "dark" else "#000"
        svg = qr.svg(public_url(), dark=color)
        resp = make_response(svg)
        resp.headers["Content-Type"] = "image/svg+xml"
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    # ---------------------------------------------------------- the screen

    @app.get("/screen")
    @admin_only
    def screen():
        settings = {
            "cards": cfg.screen.cards,
            "changeSecs": cfg.screen.change_secs,
            "minSecs": cfg.screen.min_secs,
            "newSecs": cfg.screen.new_secs,
            "pollSecs": cfg.screen.poll_secs,
            "api": url_for("screen_api"),
        }
        return render_template("screen.html", settings=settings)

    @app.get("/screen/api/greetings")
    @admin_only(api=True)
    def screen_api():
        c = conn()
        v = db.version(c)
        etag = f'"{v}"'
        if request.headers.get("If-None-Match") == etag:
            return "", 304, {"ETag": etag}
        greetings = [
            {"id": x.id, "name": x.name, "body": x.body}
            for x in db.all_greetings(c)
        ]
        resp = jsonify(version=v, greetings=greetings)
        resp.headers["ETag"] = etag
        return resp

    # ---------------------------------------------------------- the family

    @app.get("/admin")
    @admin_only
    def admin():
        c = conn()
        live = list(reversed(db.all_greetings(c)))
        return render_template(
            "admin.html", greetings=live, deleted=list(reversed(db.all_greetings(c, deleted=True))),
            form_open=db.form_open(c), message=request.args.get("m"),
        )

    def _admin_post_ok():
        if not auth.check_csrf():
            abort(400, "CSRF")

    def _back(gid: int | None = None, m: str | None = None):
        return redirect(url_for("admin", m=m) + (f"#g{gid}" if gid else ""))

    @app.route("/admin/<int:gid>", methods=["GET", "POST"])
    @admin_only
    def admin_edit(gid: int):
        c = conn()
        item = db.get(c, gid)
        if item is None:
            abort(404)
        if request.method == "GET":
            return render_template("edit.html", greeting=item, name=item.name,
                                   body=item.body, errors=(), revisions=db.revisions(c, gid))
        _admin_post_ok()
        name = clean_name(request.form.get("name", ""))
        body = clean_body(request.form.get("body", ""))
        # The family may go over the guests' length limit: fixing a typo in a
        # greeting that is already 300 characters must not be refused.
        errors = validate(name, body, limits=False)
        if errors:
            return render_template("edit.html", greeting=item, name=name, body=body,
                                   errors=errors, revisions=db.revisions(c, gid)), 400
        db.update(c, gid, name, body, by=editor())
        log.info("greeting %d edited by %s", gid, editor())
        return _back(gid, "הברכה נשמרה.")

    @app.post("/admin/<int:gid>/delete")
    @admin_only
    def admin_delete(gid: int):
        _admin_post_ok()
        if not db.set_deleted(conn(), gid, True):
            abort(404)
        log.info("greeting %d deleted by %s", gid, editor())
        return _back(None, "הברכה נמחקה. אפשר לשחזר אותה מרשימת הברכות שנמחקו.")

    @app.post("/admin/<int:gid>/restore")
    @admin_only
    def admin_restore(gid: int):
        _admin_post_ok()
        if not db.set_deleted(conn(), gid, False):
            abort(404)
        log.info("greeting %d restored by %s", gid, editor())
        return _back(gid, "הברכה שוחזרה.")

    @app.post("/admin/form")
    @admin_only
    def admin_form():
        _admin_post_ok()
        is_open = request.form.get("open") == "1"
        db.set_form_open(conn(), is_open)
        log.info("form %s by %s", "opened" if is_open else "closed", editor())
        return _back(None, "הטופס פתוח לברכות." if is_open else "הטופס נסגר.")

    @app.get("/admin/print")
    @admin_only
    def admin_print():
        return render_template("print.html", greetings=db.all_greetings(conn()))

    @app.get("/admin/qr")
    @admin_only
    def admin_qr():
        return render_template("qr.html")

    @app.get("/admin/greetings.csv")
    @admin_only
    def admin_csv():
        out = io.StringIO()
        out.write("﻿")        # so that Excel reads it as UTF-8
        w = csv.writer(out)
        w.writerow(["מספר", "שם", "ברכה", "נשלחה", "עודכנה"])
        for x in db.all_greetings(conn()):
            w.writerow([x.id, x.name, x.body,
                        _localtime(x.created_at, "%Y-%m-%d %H:%M"),
                        _localtime(x.updated_at, "%Y-%m-%d %H:%M")])
        resp = make_response(out.getvalue())
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = 'attachment; filename="greetings.csv"'
        return resp

    # ---------------------------------------------------------- signing in

    @app.get("/login")
    def login():
        nxt = auth.safe_next(request.args.get("next"))
        if not require_login or auth.is_admin(cfg.admins):
            return redirect(nxt)
        return render_template("login.html", next=nxt,
                               google=google_auth.enabled(cfg),
                               error=request.args.get("error"))

    @app.get("/auth/google")
    def google_start():
        if not google_auth.enabled(cfg):
            abort(404)
        nxt = auth.safe_next(request.args.get("next"))
        return redirect(google_auth.begin(cfg, session, nxt))

    @app.get("/auth/google/callback")
    def google_callback():
        if not google_auth.enabled(cfg):
            abort(404)
        if request.args.get("error"):
            log.info("google sign-in declined: %s", request.args.get("error"))
            return redirect(url_for("login"))
        try:
            identity, nxt = google_auth.complete(
                cfg, session,
                code=request.args.get("code", ""),
                state=request.args.get("state", ""),
            )
        except google_auth.GoogleAuthError as e:
            log.warning("google sign-in failed: %s", e)
            return redirect(url_for("login", error="ההתחברות נכשלה. נא לנסות שוב."))
        if identity.email.lower() not in cfg.admins:
            log.info("google sign-in by %s, who is not an admin", identity.email)
            return redirect(url_for(
                "login", error=f"לכתובת {identity.email} אין הרשאה לדף הזה."))
        auth.log_in(identity.email)
        log.info("login: %s from %s", identity.email, request.remote_addr)
        return redirect(auth.safe_next(nxt))

    @app.post("/logout")
    def logout():
        auth.log_out()
        return redirect(url_for("login"))

    return app
