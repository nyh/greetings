"""Command line: ``greetings init``, ``greetings serve``, ``greetings export``."""

# Copyright (C) 2026 Nadav Har'El
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

from . import config, db


def _load(args) -> config.Config:
    path = config.find_config(args.config)
    if path is None:
        sys.exit("greetings: no config.toml found. Run `greetings init` first, "
                 "or set GREETINGS_CONFIG.")
    try:
        return config.load(path)
    except config.ConfigError as e:
        sys.exit(f"greetings: {e}")


def cmd_init(args) -> None:
    path = Path(args.config or "config.toml")
    if path.exists():
        sys.exit(f"greetings: {path} already exists; not overwriting it")
    state_dir = Path(args.state_dir).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.TEMPLATE.format(state_dir=state_dir), encoding="utf-8")
    cfg = config.load(path)
    db.init(cfg.db_path)
    print(f"wrote {path}; database in {cfg.db_path}")


def cmd_serve(args) -> None:
    from .web import create_app

    cfg = _load(args)
    host = args.bind
    loopback = host in ("127.0.0.1", "localhost", "::1")
    require_login = args.login
    if not loopback and not require_login and not args.insecure:
        sys.exit(f"greetings: refusing to serve the family's pages without a login on "
                 f"{host}; anyone on the network could reach them. Add --login, or "
                 f"--insecure if this network is yours alone (e.g. to try the form "
                 f"from a phone at home).")
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    app = create_app(cfg, require_login=require_login)
    print(f"guests: http://{host}:{args.port}/   screen: /screen   family: /admin"
          + ("" if require_login else "   (no login)"))
    app.run(host=host, port=args.port, debug=args.debug, threaded=True)


def cmd_export(args) -> None:
    cfg = _load(args)
    conn = db.connect(cfg.db_path)
    w = csv.writer(sys.stdout)
    w.writerow(["id", "name", "body", "created_at", "updated_at"])
    for x in db.all_greetings(conn):
        w.writerow([x.id, x.name, x.body, x.created_at, x.updated_at])


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="greetings")
    p.add_argument("--config", help="config.toml (default: search, see README)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="write a config.toml and create the database")
    pi.add_argument("--state-dir", default="state",
                    help="where the database and secret key go (default: ./state)")
    pi.set_defaults(fn=cmd_init)

    ps = sub.add_parser("serve", help="development server")
    ps.add_argument("--bind", default="127.0.0.1")
    ps.add_argument("--port", type=int, default=5000)
    ps.add_argument("--login", action="store_true",
                    help="require Google sign-in for the screen and admin pages")
    ps.add_argument("--insecure", action="store_true",
                    help="allow serving beyond loopback with no login")
    ps.add_argument("--debug", action="store_true")
    ps.set_defaults(fn=cmd_serve)

    pe = sub.add_parser("export", help="all greetings as CSV on standard output")
    pe.set_defaults(fn=cmd_export)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
