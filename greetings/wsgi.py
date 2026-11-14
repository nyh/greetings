"""Entry point for gunicorn: ``gunicorn greetings.wsgi:app``."""

# Copyright (C) 2026 Nadav Har'El
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging

from . import config
from .web import create_app

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

_path = config.find_config()
if _path is None:
    raise SystemExit("greetings: no config.toml found; set GREETINGS_CONFIG")
app = create_app(config.load(_path), require_login=True)
