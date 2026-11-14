"""Configuration: loading, defaults and validation.

Everything personal about the event — its title, who may see the screen —
lives in config.toml, which is not in git, so the code says nothing about it.
"""

# Copyright (C) 2026 Nadav Har'El
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_ENV = "GREETINGS_CONFIG"

# Search order, first match wins (after $GREETINGS_CONFIG).
CONFIG_SEARCH = (
    Path("config.toml"),
    Path.home() / ".config" / "greetings" / "config.toml",
    Path("/etc/greetings/config.toml"),
)


class ConfigError(Exception):
    """The configuration file is missing, malformed or self-contradictory."""


@dataclass(frozen=True)
class Screen:
    cards: int = 6            # greetings on screen at once
    change_secs: float = 6    # one card is replaced this often
    min_secs: float = 12      # no card is replaced before it was up this long
    new_secs: float = 120     # a new greeting's first turn, unless more arrive
                              # together than there are cards
    poll_secs: float = 2      # how often the screen asks for changes
    background: str = "#4a2a6b"   # the color at the top; darker toward the bottom


@dataclass(frozen=True)
class Google:
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""


@dataclass(frozen=True)
class Config:
    state_dir: Path
    base_url: str = ""                 # "" = take it from each request
    behind_proxy: bool = False
    title: str = "מזל טוב!"            # the screen's heading
    form_heading: str = "כתבו ברכה"    # the guest form's heading
    admins: tuple[str, ...] = ()       # Google addresses allowed in
    max_name: int = 40
    max_length: int = 300
    # New greetings one IP address may send per minute. Loose on purpose:
    # every guest on the venue's Wi-Fi shares one address.
    new_per_minute: int = 30
    timezone: str = "Asia/Jerusalem"
    session_days: int = 30
    screen: Screen = field(default_factory=Screen)
    google: Google = field(default_factory=Google)
    path: Path | None = None           # where it was loaded from

    @property
    def db_path(self) -> Path:
        return self.state_dir / "greetings.sqlite"

    @property
    def secret_key_path(self) -> Path:
        return self.state_dir / "secret_key"


def find_config(explicit: str | None = None) -> Path | None:
    if explicit:
        return Path(explicit)
    env = os.environ.get(CONFIG_ENV)
    if env:
        return Path(env)
    for p in CONFIG_SEARCH:
        if p.is_file():
            return p
    return None


def _section(raw: dict, name: str, cls):
    sub = raw.pop(name, {}) or {}
    if not isinstance(sub, dict):
        raise ConfigError(f"[{name}] must be a table")
    known = set(cls.__dataclass_fields__)
    unknown = set(sub) - known
    if unknown:
        raise ConfigError(f"unknown keys in [{name}]: {', '.join(sorted(unknown))}")
    return cls(**sub)


def load(path: Path) -> Config:
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"{path}: not found") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    return from_dict(raw, path)


def from_dict(raw: dict, path: Path | None = None) -> Config:
    raw = dict(raw)
    screen = _section(raw, "screen", Screen)
    google = _section(raw, "google", Google)
    if "state_dir" not in raw:
        raise ConfigError("state_dir is not set")
    state_dir = Path(raw.pop("state_dir")).expanduser()
    if path is not None and not state_dir.is_absolute():
        state_dir = (path.parent / state_dir).resolve()
    known = set(Config.__dataclass_fields__) - {"state_dir", "screen", "google", "path"}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"unknown keys: {', '.join(sorted(unknown))}")
    if "admins" in raw:
        raw["admins"] = tuple(a.strip().lower() for a in raw["admins"])
    cfg = Config(state_dir=state_dir, screen=screen, google=google, path=path, **raw)
    cfg_base = cfg.base_url
    if cfg_base and (cfg_base.endswith("/") or "://" not in cfg_base):
        raise ConfigError(f"base_url {cfg_base!r}: scheme and host, no trailing slash")
    if cfg.max_length < 1 or cfg.max_name < 1:
        raise ConfigError("max_length and max_name must be positive")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", cfg.screen.background):
        raise ConfigError(f"[screen] background {cfg.screen.background!r}: "
                          f"a color like \"#4a2a6b\"")
    if cfg.screen.cards < 1:
        raise ConfigError("[screen] cards must be positive")
    if cfg.google.enabled and not cfg.base_url:
        raise ConfigError("[google] needs base_url, for the redirect URI")
    return cfg


TEMPLATE = """\
# greetings configuration. See PLAN.md / INSTALL.md.

# Where the database and the secret key live.
state_dir = "{state_dir}"

# On the server, exactly, with no trailing slash:
# base_url     = "https://greetings.example.org"
# behind_proxy = true        # believe Apache's X-Forwarded-* headers

title        = "מזל טוב!"     # the screen's heading
form_heading = "כתבו ברכה"    # the guest form's heading

# Google addresses allowed to see the screen and the admin page.
admins = []

max_name   = 40      # characters
max_length = 300     # characters

[screen]
cards       = 6      # greetings on screen at once
change_secs = 6      # one card is replaced this often
min_secs    = 12     # a card stays up at least this long
new_secs    = 120    # a new greeting's first turn on screen
background  = "#4a2a6b"   # the color at the top; darker toward the bottom

[google]
enabled       = false
client_id     = ""
client_secret = ""
"""
