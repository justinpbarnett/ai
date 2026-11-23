import json
import os
import sqlite3
import zlib
from collections import defaultdict
from contextlib import contextmanager

from .hashing import digest
from .ledger import UNRESOLVED, now, strict_debt_points
from .thresholds import ledger_thresholds
from .validation import require

SCHEMA_VERSION = 1
RUNS_TABLE = (
    "CREATE TABLE IF NOT EXISTS runs (name TEXT PRIMARY KEY, payload BLOB NOT NULL)"
)
SCHEMA = (
    "CREATE TABLE identity (root TEXT NOT NULL)",
    "CREATE TABLE scopes (key TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload BLOB NOT NULL)",
    "CREATE TABLE detector_cache (key TEXT PRIMARY KEY, payload BLOB NOT NULL)",
    "CREATE TABLE receipts (unit TEXT NOT NULL, pass TEXT NOT NULL, scope TEXT NOT NULL, payload BLOB NOT NULL, PRIMARY KEY(unit, pass, scope))",
    "CREATE TABLE packets (id TEXT PRIMARY KEY, scope TEXT NOT NULL, consumed INTEGER NOT NULL, payload BLOB NOT NULL)",
    "CREATE TABLE history (id INTEGER PRIMARY KEY, scope TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL, payload BLOB NOT NULL)",
)


def packed(value):
    return zlib.compress(
        json.dumps(
            value, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ).encode(),
        level=3,
    )


def unpacked(payload):
    try:
        return json.loads(zlib.decompress(payload))
    except zlib.error as exc:
        raise ValueError(
            "state payload is corrupt; preserve the ledger and ask before archiving it"
        ) from exc


class Store:
    def __init__(self, path, root, scopes, thresholds, *, write=False):
        self.path = path
        self.select(scopes, thresholds)
        self.connection = None
        if not write and not path.exists():
            return
        for artifact in (
            path,
            *(
                path.with_name(path.name + suffix)
                for suffix in ("-journal", "-wal", "-shm")
            ),
        ):
            require(
                not artifact.is_symlink(), "state database files must not be symlinks"
            )
            if artifact.exists():
                require(
                    artifact.is_file() and artifact.stat().st_nlink == 1,
                    "state database files must be regular, unshared files",
                )
        if write:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "wb"
            ):
                pass
        self.connection = sqlite3.connect(
            path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
            uri=True,
            timeout=10,
            isolation_level=None,
        )
        self.connection.execute("PRAGMA trusted_schema = OFF")
        try:
            if write:
                with self.transaction():
                    self.validate(root, initialize=True)
            else:
                self.validate(root, initialize=False)
        except BaseException:
            self.close()
            raise

    def select(self, scopes, thresholds, base=None):
        profile = [scopes, ledger_thresholds(thresholds)]
        self.key = digest([*profile, base] if base else profile)

    def runs(self):
        if (
            self.connection is None
            or not self.connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'runs'"
            ).fetchone()
        ):
            return {}
        return {
            name: unpacked(payload)
            for name, payload in self.connection.execute(
                "SELECT name, payload FROM runs ORDER BY name"
            )
        }

    def save_run(self, name, configuration):
        self.connection.execute(RUNS_TABLE)
        self.connection.execute(
            "INSERT INTO runs VALUES (?, ?)", (name, packed(configuration))
        )

    def close(self):
        if self.connection is not None:
            self.connection.close()

    def validate(self, root, *, initialize):
        schema = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if schema == 0 and initialize:
            require(
                not self.connection.execute(
                    "SELECT name FROM sqlite_schema LIMIT 1"
                ).fetchone(),
                "refusing to initialize an unrelated database",
            )
            for statement in SCHEMA:
                self.connection.execute(statement)
            self.connection.execute(
                "INSERT INTO identity(root) VALUES (?)", (str(root),)
            )
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return
        require(
            schema == SCHEMA_VERSION,
            f"unsupported state schema {schema}; expected {SCHEMA_VERSION}",
        )
        identity = self.connection.execute("SELECT root FROM identity").fetchall()
        require(
            identity == [(str(root),)], "state database belongs to a different worktree"
        )

    @contextmanager
    def transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def load(self):
        row = (
            None
            if self.connection is None
            else self.connection.execute(
                "SELECT revision, payload FROM scopes WHERE key = ?", (self.key,)
            ).fetchone()
        )
        if row is None:
            return {
                "revision": 0,
                "findings": {},
                "verification": {},
                "manifest": None,
                "progress": 0,
                "idle_cycles": 0,
                "progress_at_checkpoint": 0,
            }
        return unpacked(row[1]) | {"revision": row[0]}

    def stored_revision(self):
        row = self.connection.execute(
            "SELECT revision FROM scopes WHERE key = ?", (self.key,)
        ).fetchone()
        return 0 if row is None else row[0]

    def assert_revision(self, revision):
        require(
            type(revision) is int and self.stored_revision() == revision,
            "stale or invalid state revision; reload status",
        )

    def save(self, state, kind, details):
        require(self.connection.in_transaction, "ledger saves need a transaction")
        self.assert_revision(state["revision"])
        state["revision"] += 1
        self.connection.execute(
            "INSERT OR REPLACE INTO scopes VALUES (?, ?, ?)",
            (self.key, state["revision"], packed(state)),
        )
        self.connection.execute(
            "INSERT INTO history(scope, at, kind, payload) VALUES (?, ?, ?, ?)",
            (
                self.key,
                now(),
                kind,
                packed(
                    {
                        "revision": state["revision"],
                        "snapshot": state.get("snapshot"),
                        "strict_debt_points": strict_debt_points(state["findings"]),
                        **details,
                    }
                ),
            ),
        )

    def history(self):
        if self.connection is None:
            return []
        return [
            {"at": at, "kind": kind, **unpacked(data)}
            for at, kind, data in self.connection.execute(
                "SELECT at, kind, payload FROM history WHERE scope = ? ORDER BY id",
                (self.key,),
            )
        ]

    def rows(self, table, column, keys):
        if self.connection is None:
            return
        keys = sorted(keys)
        for start in range(0, len(keys), 500):
            chunk = keys[start : start + 500]
            bind = ",".join("?" for _ in chunk)
            yield from self.connection.execute(
                f"SELECT * FROM {table} WHERE {column} IN ({bind})", chunk
            )

    def cached(self, keys):
        return {
            key: unpacked(value)
            for key, value in self.rows("detector_cache", "key", keys)
        }

    def cache(self, values):
        self.connection.executemany(
            "INSERT OR IGNORE INTO detector_cache VALUES (?, ?)",
            ((key, packed(value)) for key, value in values.items()),
        )

    def delete_detector_cache_outside_profiles(self, profiles):
        bind = ",".join("?" for _ in profiles)
        self.connection.execute(
            "DELETE FROM detector_cache WHERE instr(key, ':') = 0"
            f" OR substr(key, 1, instr(key, ':') - 1) NOT IN ({bind})",
            sorted(profiles),
        )

    def receipts(self, units):
        current, shared = defaultdict(dict), defaultdict(lambda: defaultdict(dict))
        for unit, stage, scope, payload in self.rows("receipts", "unit", units):
            receipt = unpacked(payload)
            if scope == self.key:
                current[unit][stage] = receipt
            elif not receipt["findings"] and not receipt.get("observations"):
                shared[unit][scope][stage] = receipt
        for unit, scopes in shared.items():
            if not current[unit]:
                scope = min(scopes, key=lambda key: (-len(scopes[key]), key))
                current[unit] = scopes[scope]
        return current

    def save_packet(self, packet_id, packet):
        self.connection.execute(
            "INSERT INTO packets (id, scope, consumed, payload) VALUES (?, ?, 0, ?)",
            (packet_id, self.key, packed(packet)),
        )

    def load_packet(self, packet_id):
        row = self.connection.execute(
            "SELECT payload FROM packets WHERE id = ? AND scope = ? AND consumed = 0",
            (packet_id, self.key),
        ).fetchone()
        return None if row is None else unpacked(row[0])

    def consume_packet(self, packet_id):
        self.connection.execute(
            "DELETE FROM packets WHERE id = ? OR consumed = 1", (packet_id,)
        )

    def save_receipts(self, receipts):
        self.connection.executemany(
            "INSERT OR REPLACE INTO receipts (unit, pass, scope, payload)"
            " VALUES (?, ?, ?, ?)",
            (
                (unit, stage, scope, packed(receipt))
                for unit, stage, scope, receipt in receipts
            ),
        )

    def other_profiles(self):
        if self.connection is None:
            return []
        result = []
        for _, blob in self.connection.execute(
            "SELECT key, payload FROM scopes WHERE key != ?", (self.key,)
        ):
            state = unpacked(blob)
            findings = [
                f["id"] for f in state["findings"].values() if f["status"] in UNRESOLVED
            ]
            if findings:
                result.append(
                    {
                        "scope": state.get("scope"),
                        "thresholds": state.get("thresholds"),
                        "unresolved": findings,
                    }
                )
        return result
