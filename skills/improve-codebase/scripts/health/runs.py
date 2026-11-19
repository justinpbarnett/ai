import os
import re
from pathlib import PurePosixPath

from .detectors import resolve_edges
from .inventory import (
    GENERATED,
    MAX_SOURCE_BYTES,
    PROJECT,
    excluded,
    git,
    inventory,
    normalize_scope,
    source_language,
    within,
)
from .parsers import analyze
from .state import DEBT, require, string

WIRING_LANGUAGES = {"unknown", "generic", "csharp", "html", "vue", "css", "scss"}


def run_name(name):
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", name), "invalid run name")
    return name


def current_run(store, name):
    name = run_name(name)
    configuration = store.runs().get(name)
    require(configuration is not None, f"unknown run {name!r}; use run list")
    return configuration


def in_paths(path, paths):
    return any(within(path, prefix) for prefix in paths)


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


def graph(entries, sources, parsed=None):
    if parsed is None:
        parsed = {
            path: analyze(data, entries[path]["language"], False)
            for path, data in sources.items()
        }
    edges, limitations, _, _ = resolve_edges(entries, parsed, sources)
    return edges, limitations, parsed


def base_overlay(root, base, touched, entries, sources, parsed):
    historical = {}
    state_relative = None
    for record in filter(None, git(root, "ls-tree", "-rlz", base).stdout.split(b"\0")):
        metadata, raw_path = record.split(b"\t", 1)
        path = os.fsdecode(raw_path)
        if path not in touched or excluded(path, state_relative):
            continue
        mode, kind, oid, size = metadata.split()
        if (
            kind == b"blob"
            and mode in {b"100644", b"100755"}
            and int(size) <= MAX_SOURCE_BYTES
            and source_language(path)
        ):
            historical[path] = oid.decode()
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
        PurePosixPath(path).parent
        for path in base_sources.keys() | historical.keys()
        if PROJECT.fullmatch(PurePosixPath(path).name)
    }
    for path, oid in historical.items():
        data = git(root, "cat-file", "blob", oid).stdout
        try:
            text = data.decode("utf-8-sig")
        except UnicodeError:
            continue
        if "\x00" in text or GENERATED.search(b"\n".join(data.splitlines()[:12])):
            continue
        language = source_language(path)
        base_entries[path] = {"language": language, "disposition": "context"}
        base_sources[path] = data
        base_parsed[path] = analyze(data, language, False)
    for path in base_sources:
        project = next(
            (
                str(parent)
                for parent in PurePosixPath(path).parents
                if parent in projects
            ),
            ".",
        )
        base_entries[path] = base_entries[path] | {"project": project}
    return graph(base_entries, base_sources, base_parsed)[0]


def fallout_scope(root, state_dir, fences, base, includes):
    paths = normalize_scope(root, includes) if includes else []
    require(
        all(in_paths(path, fences) for path in paths),
        "manual include is outside the requested fence",
    )
    base = (
        git(root, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}")
        .stdout.decode()
        .strip()
    )
    raw = git(
        root,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--name-only",
        "-z",
        base,
        "--",
    ).stdout
    added = git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    live, sources = inventory(root, True, ["."], state_dir, gather=True)
    touched = {os.fsdecode(p) for p in (raw + added).split(b"\0") if p}
    changed = {
        path
        for path in touched
        if path in live["entries"]
        and live["entries"][path]["disposition"] in {"source", "reference"}
    }
    removed = sorted(path for path in touched if not (root / path).exists())
    entries = live["entries"]
    edges, limitations, parsed = graph(entries, sources)
    base_edges = base_overlay(root, base, touched, entries, sources, parsed)
    edited = {path for path in changed if in_paths(path, fences)}
    retired = {
        path for path in removed if in_paths(path, fences) and not excluded(path, None)
    }
    targets = edited | retired
    callers = {
        caller
        for caller, target, _ in set(edges) | set(base_edges)
        if target in targets and caller in sources
    }
    primary = edited | {path for path in callers if in_paths(path, fences)}
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
        "changed_paths": sorted(edited),
        "direct_callers": sorted(callers & primary),
        "outside_fence": sorted((changed | callers) - primary),
        "absent_paths": sorted(retired),
        "manual_paths": paths,
        "graph_limits": {
            path: limitations[path] for path in sorted(primary) if path in limitations
        },
        "requires_wiring_review": sorted(
            path
            for path in targets
            if path in retired
            or entries[path].get("language") in WIRING_LANGUAGES
            or path in limitations
        ),
    }


def change_relation(document):
    relation = string(document, "change_relation")
    require(
        relation in {"regression", "pre_existing", "unclassified"},
        "unknown change relation",
    )
    return {
        "change_relation": relation,
        "relation_evidence": string(document, "relation_evidence"),
    }


def slice_status(state, entries, receipts, view, verification_unmet, current):
    paths = view["paths"]
    units = [
        identifier
        for identifier, unit in state.get("units", {}).items()
        if any(in_paths(p, paths) for p in unit["files"])
    ]
    counts = {
        stage: sum(stage in receipts[key] for key in units)
        for stage in ("discovery", "confirmation")
    }
    unresolved = [
        finding["id"]
        for finding in state["findings"].values()
        if finding["status"] in DEBT | {"candidate"}
        and any(in_paths(path, paths) for path in finding["source_hashes"])
    ]
    gaps = [
        gap
        for gap in state.get("scan", {}).get("gaps", [])
        if in_paths(gap["path"], paths)
    ]
    incomplete = [
        path
        for path, entry in entries.items()
        if entry["disposition"] == "incomplete" and in_paths(path, paths)
    ]
    return view | {
        "verified": bool(
            current
            and units
            and all(count == len(units) for count in counts.values())
            and not (unresolved or gaps or incomplete or verification_unmet)
        ),
        "coverage": {"total": len(units), **counts},
        "unresolved": unresolved,
        "parser_gaps": gaps,
        "incomplete_paths": incomplete,
    }
