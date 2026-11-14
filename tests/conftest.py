# Copyright (C) 2026 Nadav Har'El
# SPDX-License-Identifier: AGPL-3.0-or-later

import re

import pytest

from greetings import config
from greetings.web import create_app


def make_cfg(tmp_path, **kw):
    raw = {"state_dir": str(tmp_path), "admins": ["mom@example.com"]}
    raw.update(kw)
    return config.from_dict(raw)


@pytest.fixture
def cfg(tmp_path):
    return make_cfg(tmp_path)


@pytest.fixture
def app(cfg):
    a = create_app(cfg, require_login=False)
    a.testing = True
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, path="/"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def send(client, name, body, **extra):
    return client.post("/", data={"csrf": csrf(client), "name": name, "body": body, **extra})
