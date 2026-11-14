"""The greetings database: one SQLite file.

Nothing is ever really lost here. Deleting sets ``deleted_at`` and can be
undone, and every edit first copies the previous text into ``revisions``.

Every write also increments a change counter in ``meta``. The screen polls with
the counter it last saw, so an unchanged list costs one integer comparison.
"""

# Copyright (C) 2026 Nadav Har'El
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS greetings (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    body        TEXT NOT NULL,
    owner       TEXT,               -- SHA-256 of the guest's cookie token
    created_at  TEXT NOT NULL,      -- ISO 8601, UTC
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT
);
CREATE INDEX IF NOT EXISTS greetings_owner ON greetings(owner);

CREATE TABLE IF NOT EXISTS revisions (
    greeting_id INTEGER NOT NULL REFERENCES greetings(id),
    name        TEXT NOT NULL,
    body        TEXT NOT NULL,
    edited_at   TEXT NOT NULL,      -- when this version was replaced
    edited_by   TEXT NOT NULL       -- 'guest' or the admin's address
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO meta VALUES ('version', '0');
INSERT OR IGNORE INTO meta VALUES ('form_open', '1');
"""


@dataclass(frozen=True)
class Greeting:
    id: int
    name: str
    body: str
    created_at: str
    updated_at: str
    deleted_at: str | None
    edited: bool = False        # has at least one earlier revision

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    # isolation_level=None: we open transactions ourselves, with BEGIN
    # IMMEDIATE, so two writers never deadlock upgrading a read lock.
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


class _Write:
    """A write transaction that also bumps the change counter."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.conn.execute(
                "UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'version'"
            )
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")


def _greeting(row: sqlite3.Row) -> Greeting:
    return Greeting(
        id=row["id"],
        name=row["name"],
        body=row["body"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
        edited=bool(row["edited"]) if "edited" in row.keys() else False,
    )


_SELECT = """
SELECT g.*, EXISTS(SELECT 1 FROM revisions r WHERE r.greeting_id = g.id) AS edited
FROM greetings g
"""


def version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()[0])


def form_open(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT value FROM meta WHERE key = 'form_open'").fetchone()[0] == "1"


def set_form_open(conn: sqlite3.Connection, is_open: bool) -> None:
    with _Write(conn) as c:
        c.execute("UPDATE meta SET value = ? WHERE key = 'form_open'", ("1" if is_open else "0",))


def get(conn: sqlite3.Connection, gid: int) -> Greeting | None:
    row = conn.execute(_SELECT + "WHERE g.id = ?", (gid,)).fetchone()
    return _greeting(row) if row else None


def by_owner(conn: sqlite3.Connection, owner: str) -> Greeting | None:
    """The guest's live greeting, if they have one. A deleted one does not
    count: the guest then gets a fresh form."""
    row = conn.execute(
        _SELECT + "WHERE g.owner = ? AND g.deleted_at IS NULL ORDER BY g.id DESC LIMIT 1",
        (owner,),
    ).fetchone()
    return _greeting(row) if row else None


def all_greetings(conn: sqlite3.Connection, *, deleted: bool = False) -> list[Greeting]:
    """Oldest first. ``deleted=True`` returns only the deleted ones."""
    cond = "IS NOT NULL" if deleted else "IS NULL"
    rows = conn.execute(_SELECT + f"WHERE g.deleted_at {cond} ORDER BY g.id").fetchall()
    return [_greeting(r) for r in rows]


def add(conn: sqlite3.Connection, name: str, body: str, owner: str | None) -> int:
    t = now()
    with _Write(conn) as c:
        cur = c.execute(
            "INSERT INTO greetings (name, body, owner, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, body, owner, t, t),
        )
        return cur.lastrowid


def update(conn: sqlite3.Connection, gid: int, name: str, body: str, by: str) -> bool:
    """Replace the text, keeping the old one in ``revisions``. An edit that
    changes nothing is not recorded and does not wake the screen."""
    with _Write(conn) as c:
        row = c.execute("SELECT name, body FROM greetings WHERE id = ?", (gid,)).fetchone()
        if row is None:
            return False
        if (row["name"], row["body"]) == (name, body):
            return True
        t = now()
        c.execute(
            "INSERT INTO revisions (greeting_id, name, body, edited_at, edited_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (gid, row["name"], row["body"], t, by),
        )
        c.execute(
            "UPDATE greetings SET name = ?, body = ?, updated_at = ? WHERE id = ?",
            (name, body, t, gid),
        )
        return True


def set_deleted(conn: sqlite3.Connection, gid: int, deleted: bool) -> bool:
    with _Write(conn) as c:
        cur = c.execute(
            "UPDATE greetings SET deleted_at = ? WHERE id = ?",
            (now() if deleted else None, gid),
        )
        return cur.rowcount == 1


def revisions(conn: sqlite3.Connection, gid: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM revisions WHERE greeting_id = ? ORDER BY rowid DESC", (gid,)
    ).fetchall()
