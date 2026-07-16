"""Purchase-token store for the activation server (stdlib sqlite3, no ORM).

A purchase token is what JELOTIA hands a customer after a sale. Its row is the
*entitlement*: which tier, for whom, with what cap/expiry, bound to the machine
or not, and how many machines may redeem it. The store holds no secret — the
signing key lives only in the server process — so it is safe to back up.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    token             TEXT PRIMARY KEY,
    tier              TEXT NOT NULL,
    licensee          TEXT NOT NULL DEFAULT '',
    max_files_per_day INTEGER NOT NULL DEFAULT 0,
    expires           TEXT NOT NULL DEFAULT '',
    features          TEXT NOT NULL DEFAULT '',
    bind_machine      INTEGER NOT NULL DEFAULT 0,
    max_activations   INTEGER NOT NULL DEFAULT 1,
    revoked           INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    issued_at   TEXT NOT NULL,
    UNIQUE(token, fingerprint)
);
"""


@dataclass
class Token:
    token: str
    tier: str
    licensee: str = ""
    max_files_per_day: int = 0
    expires: str = ""            # "AAAA-MM-JJ" or "" for perpetual
    features: str = ""           # csv of extra Enterprise features
    bind_machine: bool = False   # Personal binds to the activating machine
    max_activations: int = 1     # how many machines may redeem this token
    revoked: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TokenStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        # check_same_thread=False so a threaded ASGI server can share the conn;
        # every write commits immediately, and access is short-lived.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- writes ------------------------------------------------------------ #

    def add_token(self, tok: Token) -> None:
        self._conn.execute(
            "INSERT INTO tokens(token, tier, licensee, max_files_per_day, expires, "
            "features, bind_machine, max_activations, revoked, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                tok.token, tok.tier, tok.licensee, tok.max_files_per_day, tok.expires,
                tok.features, int(tok.bind_machine), tok.max_activations,
                int(tok.revoked), _now(),
            ),
        )
        self._conn.commit()

    def revoke(self, token: str) -> bool:
        cur = self._conn.execute(
            "UPDATE tokens SET revoked = 1 WHERE token = ?", (token,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def record_activation(self, token: str, fingerprint: str) -> None:
        """Idempotent: a repeat activation of the same machine is a no-op (the
        UNIQUE(token, fingerprint) makes a reinstall re-issue without consuming
        a new slot)."""
        self._conn.execute(
            "INSERT OR IGNORE INTO activations(token, fingerprint, issued_at) "
            "VALUES(?,?,?)",
            (token, fingerprint, _now()),
        )
        self._conn.commit()

    # -- reads ------------------------------------------------------------- #

    def get(self, token: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM tokens WHERE token = ?", (token,)
        ).fetchone()

    def activation_count(self, token: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM activations WHERE token = ?", (token,)
        ).fetchone()[0]

    def has_activation(self, token: str, fingerprint: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM activations WHERE token = ? AND fingerprint = ?",
            (token, fingerprint),
        ).fetchone() is not None

    def list_tokens(self) -> List[sqlite3.Row]:
        return list(self._conn.execute(
            "SELECT t.*, "
            "(SELECT COUNT(*) FROM activations a WHERE a.token = t.token) AS used "
            "FROM tokens t ORDER BY t.created_at DESC"
        ).fetchall())
