import json
import os
import sqlite3
import stat
import zlib
from collections import defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .inventory import STATE_DIR, digest, git

SCHEMA_VERSION = 1
RUNS_TABLE = (
    "CREATE TABLE IF NOT EXISTS runs (name TEXT PRIMARY KEY, payload BLOB NOT NULL)"
)
DEBT = {"open", "in_progress", "pending_verification", "blocked", "accepted_risk"}
SEVERITIES = {"critical": 16, "high": 8, "medium": 3, "low": 1}
MAX_INPUT_BYTES = 32 * 1024 * 1024
SCHEMA = (
    "CREATE TABLE identity (root TEXT NOT NULL)",
    "CREATE TABLE scopes (key TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload BLOB NOT NULL)",
    "CREATE TABLE detector_cache (key TEXT PRIMARY KEY, payload BLOB NOT NULL)",
    "CREATE TABLE receipts (unit TEXT NOT NULL, pass TEXT NOT NULL, scope TEXT NOT NULL, payload BLOB NOT NULL, PRIMARY KEY(unit, pass, scope))",
    "CREATE TABLE packets (id TEXT PRIMARY KEY, scope TEXT NOT NULL, consumed INTEGER NOT NULL, payload BLOB NOT NULL)",
    "CREATE TABLE history (id INTEGER PRIMARY KEY, scope TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL, payload BLOB NOT NULL)",
)


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def packed(value):
    return zlib.compress(
        json.dumps(
            value, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ).encode(),
        level=3,
    )


def unpacked(payload):
    return json.loads(zlib.decompress(payload))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def string(obj, key):
    value = obj.get(key)
    require(
        isinstance(value, str) and value.strip(), f"{key} must be a nonempty string"
    )
    return value


def array(obj, key):
    value = obj.get(key)
    require(isinstance(value, list), f"{key} must be a list")
    return value


def object_value(value, name):
    require(isinstance(value, dict), f"{name} must be an object")
    return value


def read_json(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    require(len(data) <= MAX_INPUT_BYTES, "JSON input exceeds size limit")

    def reject_constant(value):
        raise ValueError(f"invalid JSON number {value}")

    def unique_object(items):
        result = dict(items)
        require(len(items) == len(result), "duplicate JSON object key")
        return result

    return json.loads(
        data, parse_constant=reject_constant, object_pairs_hook=unique_object
    )


def check_ignore(root, relative, *git_options):
    return not git(
        root,
        *git_options,
        "check-ignore",
        "--quiet",
        "--no-index",
        "--",
        relative + "/",
        allowed=(0, 1),
    ).returncode


def add_local_exclusion(root, relative):
    raw = git(root, "rev-parse", "--git-path", "info/exclude").stdout.rstrip(b"\n")
    path = root / os.fsdecode(raw)
    require(path.resolve() == path, "Git local exclude is redirected by a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    with lock.open("xb") as stream:
        try:
            old = path.read_bytes() if path.exists() else b""
            rule = f"/{relative}/".encode()
            require(
                rule not in old.splitlines(),
                "local Git exclusion is overridden; fix the ignore rules before writing state",
            )
            stream.write(
                old + (b"\n" if old and not old.endswith(b"\n") else b"") + rule + b"\n"
            )
            if path.exists():
                os.fchmod(stream.fileno(), stat.S_IMODE(path.stat().st_mode))
            stream.flush()
            os.fsync(stream.fileno())
            # A temporary fallback rule tests Git's precedence without changing the real excludes.
            require(
                check_ignore(root, relative, "-c", f"core.excludesFile={lock}"),
                "an existing Git ignore negation overrides the proposed local state exclusion",
            )
            os.replace(lock, path)
        finally:
            lock.unlink(missing_ok=True)
    require(
        check_ignore(root, relative), "cannot protect state with Git local excludes"
    )


def safe_state_dir(root, is_git, requested, write):
    default = root / STATE_DIR
    path = Path(os.path.abspath(Path(requested).expanduser())) if requested else default
    require(
        path.resolve() == path, "state directory must not be a symlink or traverse one"
    )
    require(
        path not in (root, *root.parents)
        and not (path == root / ".git" or path.is_relative_to(root / ".git")),
        "state directory cannot cover the worktree or Git metadata",
    )
    if is_git and path.is_relative_to(root):
        relative = path.relative_to(root).as_posix()
        tracked = git(
            root, "--literal-pathspecs", "ls-files", "-z", "--", relative
        ).stdout
        require(not tracked, f"state path is tracked: {relative!r}")
        if write and not check_ignore(root, relative):
            require(
                path == default,
                "custom state inside a worktree must already be ignored",
            )
            add_local_exclusion(root, relative)
    if path.exists():
        require(path.is_dir(), "state location is not a directory")
    return path


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
        profile = [scopes, thresholds]
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

    def assert_revision(self, revision):
        require(
            type(revision) is int and self.load()["revision"] == revision,
            "stale or invalid state revision; reload status",
        )

    def save(self, state, kind, details):
        state["revision"] += 1
        self.connection.execute(
            "INSERT OR REPLACE INTO scopes VALUES (?, ?, ?)",
            (self.key, state["revision"], packed(state)),
        )
        debt = sum(
            SEVERITIES[f["severity"]]
            for f in state["findings"].values()
            if f["status"] in DEBT
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
                        "strict_debt_points": debt,
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

    def other_profiles(self):
        if self.connection is None:
            return []
        result = []
        for _, blob in self.connection.execute(
            "SELECT key, payload FROM scopes WHERE key != ?", (self.key,)
        ):
            state = unpacked(blob)
            findings = [
                f["id"]
                for f in state["findings"].values()
                if f["status"] in DEBT or f["status"] == "candidate"
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


def finding_id(finding):
    return digest(
        [
            finding["origin"],
            finding["rule"],
            finding["location"]["path"],
            finding["anchor"],
            finding.get("identity", ""),
        ]
    )[:24]


def evidence_paths(finding):
    return sorted(
        {finding["location"]["path"], *(loc["path"] for loc in finding["related"])}
    )


def moved_finding(findings, finding, moves):
    if not moves:
        return None
    destinations = finding["source_hashes"]
    matches = [
        item
        for item in findings.values()
        if moves.get(item["location"]["path"]) in destinations
        and item["origin"] == finding["origin"]
        and item["rule"] == finding["rule"]
        and item["anchor"] == finding["anchor"]
        and item.get("identity", "") == finding.get("identity", "")
        and item["signature"] == finding["signature"]
    ]
    return matches[0] if len(matches) == 1 else None


def observe(state, finding, *, entries=None):
    findings = state["findings"]
    if entries is None:
        entries = state["inventory"]["entries"]
    finding["source_hashes"] = {
        path: entries[path]["hash"] for path in evidence_paths(finding)
    }
    location_key = finding_id(finding)
    location_keys = state.setdefault("finding_keys", {})
    identifier = location_keys.get(location_key, location_key)
    prior = findings.get(identifier)
    if prior is None:
        prior = moved_finding(findings, finding, state.get("moves"))
        if prior is not None:
            identifier = prior["id"]
    location_keys[location_key] = identifier
    status = prior["status"] if prior else "candidate"
    if prior and prior.get("triaged_at") and "severity" in finding:
        # A duplicate review cannot silently reclassify recorded debt.
        finding["severity"] = prior["severity"]
    if prior and (
        (status == "false_positive" and prior["signature"] != finding["signature"])
        or status == "resolved"
    ):
        status = "open" if status == "resolved" else "candidate"
    revision = state["revision"] + 1
    previous = prior or {
        "first_seen_snapshot": state["snapshot"],
        "first_seen_revision": revision,
        "aliases": [],
        "history": [],
    }
    aliases = previous["aliases"]
    if prior and prior["location"]["path"] != finding["location"]["path"]:
        aliases = sorted(set(aliases) | {prior["location"]["path"]})
    history = previous["history"]
    if prior and status != prior["status"]:
        history = [
            *history,
            {
                "from": prior["status"],
                "to": status,
                "reason": "evidence changed or problem recurred",
                "snapshot": state["snapshot"],
                "at": now(),
            },
        ]
    findings[identifier] = (
        previous
        | finding
        | {
            "id": identifier,
            "status": status,
            "aliases": aliases,
            "history": history,
            "last_seen_snapshot": state["snapshot"],
            "last_seen_revision": revision,
        }
    )
    if prior is None and (
        finding["origin"] != "scanner" or not state.get("scan_repeated_snapshot")
    ):
        state["progress"] += 1
    return identifier


def detect_moves(previous, current):
    old, new = defaultdict(list), defaultdict(list)
    for left, right, index in ((previous, current, old), (current, previous, new)):
        for path, entry in left.items():
            if entry.get("hash") and not right.get(path, {}).get("hash"):
                index[entry["hash"]].append(path)
    return {
        paths[0]: new[key][0]
        for key, paths in old.items()
        if len(paths) == 1 and len(new[key]) == 1
    }


def finding_prerequisites(finding):
    field = "replacements" if finding["status"] == "superseded" else "dependencies"
    return finding.get(field, [])


def validate_dependencies(findings, identifier, dependencies):
    require(
        all(
            isinstance(d, str) and d in findings and d != identifier
            for d in dependencies
        ),
        "unknown or self-referencing finding dependency",
    )
    require(len(dependencies) == len(set(dependencies)), "duplicate dependency")


def validate_prerequisite_cycle(findings, proposed):
    pending, visited = list(finding_prerequisites(proposed)), set()
    while pending:
        other = pending.pop()
        require(other != proposed["id"], "finding dependency or replacement cycle")
        if other not in visited:
            visited.add(other)
            pending.extend(finding_prerequisites(findings[other]))
