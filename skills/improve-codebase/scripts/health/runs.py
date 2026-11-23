import os
import re
from itertools import chain
from pathlib import PurePosixPath

from .dependency_graph import resolve_edges
from .inventory import (
    MAX_SOURCE_BYTES,
    PROJECT,
    WIRING_LANGUAGES,
    classify_content,
    excluded,
    git,
    inventory,
    normalize_scope,
    owning_project,
    source_language,
)
from .parsers import analyze
from .paths import in_paths
from .scanning import parse_for_graph
from .validation import require


def run_name(name):
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", name), "invalid run name")
    return name


def current_run(store, name):
    name = run_name(name)
    configuration = store.runs().get(name)
    require(configuration is not None, f"unknown run {name!r}; use run list")
    return configuration


def slice_configuration(root, parent_name, parent, requested):
    require(
        not parent.get("slice"), "create a slice from the parent run, not another slice"
    )
    paths = normalize_scope(root, requested)
    require(
        all(in_paths(path, parent["scope"]) for path in paths),
        "slice must be inside the parent scope",
    )
    return parent | {"slice": {"parent": parent_name, "paths": paths}}


def historical_blobs(root, base, touched):
    historical = {}
    for record in filter(None, git(root, "ls-tree", "-rlz", base).stdout.split(b"\0")):
        metadata, raw_path = record.split(b"\t", 1)
        path = os.fsdecode(raw_path)
        if path not in touched or excluded(path, None):
            continue
        mode, kind, oid, size = metadata.split()
        if (
            kind == b"blob"
            and mode in {b"100644", b"100755"}
            and int(size) <= MAX_SOURCE_BYTES
            and source_language(path)
        ):
            historical[path] = oid.decode()
    return historical


def base_overlay(root, base, touched, entries, sources, parsed):
    historical = historical_blobs(root, base, touched)
    if not historical:
        return []
    base_sources = {path: data for path, data in sources.items() if path not in touched}
    base_entries = {
        path: entry for path, entry in entries.items() if path not in touched
    }
    base_parsed = {
        path: result for path, result in parsed.items() if path not in touched
    }
    projects = {
        PurePosixPath(path).parent.as_posix()
        for path in base_sources.keys() | historical.keys()
        if PROJECT.fullmatch(PurePosixPath(path).name)
    }
    for path, oid in historical.items():
        data = git(root, "cat-file", "blob", oid).stdout
        entry = classify_content(path, data, None, False)
        if entry is None or entry["disposition"] != "context":
            continue
        base_entries[path] = entry
        base_sources[path] = data
        base_parsed[path] = analyze(data, entry["language"], False)
    for path in base_sources:
        base_entries[path] = base_entries[path] | {
            "project": owning_project(path, projects)
        }
    return resolve_edges(base_entries, base_parsed, base_sources)[0]


def fallout_changes(root, base):
    raw = git(
        root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--name-status",
        "-z",
        base,
        "--",
    ).stdout
    fields = iter(raw.split(b"\0")[:-1])
    touched, replaced = set(), set()
    for status, raw_path in zip(fields, fields, strict=True):
        path = os.fsdecode(raw_path)
        touched.add(path)
        if status in {b"D", b"T"}:
            replaced.add(path)
    added = git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    touched.update(os.fsdecode(path) for path in added.split(b"\0") if path)
    return touched, replaced


def classify_changes(entries, touched, replaced):
    changed = {
        path
        for path in touched
        if entries.get(path, {}).get("disposition") in {"source", "reference"}
    }
    retired = {path for path in replaced - changed if not excluded(path, None)}
    return changed, retired


def select_fallout(changed, retired, sources, edges, fences):
    targets = changed | retired
    affected = {
        (caller, target)
        for caller, target, _ in edges
        if target in targets and caller in sources
    }
    callers = {caller for caller, _ in affected}
    outside = {path for path in targets | callers if not in_paths(path, fences)}
    primary = (changed | callers) - outside
    wiring_targets = (targets - outside) | {
        target for caller, target in affected if caller in primary
    }
    return (
        primary,
        wiring_targets,
        {
            "changed_paths": sorted(changed - outside),
            "direct_callers": sorted(callers & primary),
            "outside_fence": sorted(outside),
            "absent_paths": sorted(retired - outside),
        },
    )


def wiring_review(targets, retired, entries, limitations):
    return sorted(
        path
        for path in targets
        if path in retired
        or entries[path].get("language") in WIRING_LANGUAGES
        or path in limitations
    )


def resolve_base_commit(root, base):
    result = git(
        root,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{base}^{{commit}}",
        allowed=(0, 128),
    )
    require(not result.returncode, f"unknown --base commit {base!r}")
    return result.stdout.decode().strip()


def fallout_scope(store, root, state_dir, fences, base, includes):
    paths = normalize_scope(root, includes) if includes else []
    require(
        all(in_paths(path, fences) for path in paths),
        "manual include is outside the requested fence",
    )
    base = resolve_base_commit(root, base)
    touched, replaced = fallout_changes(root, base)
    live, sources = inventory(root, True, ["."], state_dir, gather=True)
    entries = live["entries"]
    changed, retired = classify_changes(entries, touched, replaced)
    parsed = parse_for_graph(entries, sources, store)
    edges, limitations, _, _ = resolve_edges(entries, parsed, sources)
    base_edges = base_overlay(root, base, touched, entries, sources, parsed)
    primary, wiring_targets, selection = select_fallout(
        changed, retired, sources, chain(edges, base_edges), fences
    )
    scopes = normalize_scope(root, [*primary, *paths]) if primary or paths else []
    require(
        any(in_paths(path, scopes) for path in sources),
        "fallout did not identify live source; include affected callers explicitly with --include",
    )
    current, _ = inventory(root, True, ["."], state_dir)
    require(
        current["fingerprint"] == live["fingerprint"],
        "source changed while planning fallout; retry",
    )
    return scopes, {
        "base": base,
        **selection,
        "manual_paths": paths,
        "graph_limits": {
            path: limitations[path] for path in sorted(primary) if path in limitations
        },
        "requires_wiring_review": wiring_review(
            wiring_targets, retired, entries, limitations
        ),
    }
