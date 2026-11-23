import ast
import sys
from dataclasses import dataclass
from pathlib import Path

from .detectors import ParseOptions, parse_snapshot, scan_sources
from .hashing import content_hash, digest
from .history import commit_history, hotspots
from .inventory import inventory
from .ledger import detect_moves, observe
from .parsers import capabilities
from .review_units import REVIEW_VERSION, units_for
from .rules import HISTORY_RULES
from .validation import require
from .verification import reconcile_baseline

SKILL = Path(__file__).resolve().parents[2]
REF = SKILL / "references" / "smell-guide.md"
SCOPE_EVIDENCE_VERSION = 1


@dataclass(frozen=True)
class ScanScope:
    root: Path
    is_git: bool
    scopes: list[str]
    thresholds: dict[str, int]
    state_dir: Path

    def history(self):
        return commit_history(self.root, self.is_git)

    def collect(self, *, gather=False):
        return inventory(
            self.root, self.is_git, self.scopes, self.state_dir, gather=gather
        )


PARSER_ENTRIES = ("parsers", "syntax_tree", "comments", "case_inventory")
DETECTOR_ENTRIES = ("detectors", "thresholds", "dependency_graph", "layout", "history")


def current_parser_profile(caps):
    return digest(
        [
            caps,
            sys.version_info[:3],
            *(module_hash(name) for name in sorted(import_closure(PARSER_ENTRIES))),
        ]
    )


def analyzer_profiles(thresholds, caps):
    parser = current_parser_profile(caps)
    detector_modules = import_closure(DETECTOR_ENTRIES) - import_closure(PARSER_ENTRIES)
    detector = digest(
        [
            parser,
            thresholds,
            *(module_hash(name) for name in sorted(detector_modules)),
        ]
    )
    return parser, detector


def import_closure(entries):
    seen = set()
    pending = list(entries)
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            pending.extend(relative_imports(name))
    return seen


def relative_imports(name):
    tree = ast.parse(module_path(name).read_bytes())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                imported.add(node.module)
            else:
                imported.update(alias.name for alias in node.names)
    return imported


def module_path(name):
    return Path(__file__).with_name(f"{name}.py")


def module_hash(name):
    return content_hash(module_path(name).read_bytes())


def parse_for_graph(entries, sources, store):
    options = ParseOptions(
        current_parser_profile(capabilities(False)), False, store.cached, False
    )
    return parse_snapshot(entries, sources, options)[0]


def rubric_version():
    return digest(
        [
            REVIEW_VERSION,
            *(
                content_hash(path.read_bytes()) if path.is_file() else None
                for path in (
                    REF,
                    SKILL / "references" / "workflow.md",
                    SKILL / "references" / "lean-rules.md",
                )
            ),
        ]
    )


def scope_evidence(live, analyzed, profile, rubric):
    units = units_for(live, analyzed, rubric)
    context, relationships = {}, set()
    for unit in units.values():
        context.update(unit["context"])
        relationships.update(unit["relationships"])
    scope_inputs = digest([live["scope_fingerprint"], context, sorted(relationships)])
    snapshot = digest(
        [
            SCOPE_EVIDENCE_VERSION,
            scope_inputs,
            profile,
            rubric,
            sorted(unit["inputs"] for unit in units.values()),
            sorted(
                digest(item)
                for item in analyzed["candidates"]
                if item["rule"] not in HISTORY_RULES
            ),
            sorted(digest(item) for item in analyzed["gaps"]),
        ]
    )
    return scope_inputs, snapshot, units


def remember_previous_units(state):
    state["previous_units"] = {
        key: {**unit, "file_hashes": [unit["context"][path] for path in unit["files"]]}
        for key, unit in state.get("units", {}).items()
    }


def refine_work_reasons(detector_work, prior_entries, entries, changed_parser):
    for path, work in detector_work.items():
        if work["status"] == "reused":
            continue
        if path not in prior_entries:
            work["reason"] = "new source path"
        elif prior_entries[path].get("hash") != entries[path].get("hash"):
            work["reason"] = "source content changed"
        elif changed_parser:
            work["reason"] = "parser version or capability changed"


def checkpoint_progress(state):
    if state["progress"] > state["progress_at_checkpoint"]:
        state["idle_cycles"] = 0
    else:
        state["idle_cycles"] += 1
    state["progress_at_checkpoint"] = state["progress"]


def scan(args, store, state, scope):
    live, files = scope.collect(gather=True)
    caps = capabilities(args.core_only)
    parser_profile, profile = analyzer_profiles(scope.thresholds, caps)
    rubric = rubric_version()
    analyzed, fresh = scan_sources(
        live,
        files,
        scope.thresholds,
        ParseOptions(parser_profile, args.core_only, store.cached, args.full),
        scope.history(),
    )
    scope_inputs, snapshot, units = scope_evidence(live, analyzed, profile, rubric)
    analyzed["hotspots"] = hotspots(scope.root, scope.is_git, analyzed["metrics"])
    latest, _ = scope.collect()
    require(
        live["fingerprint"] == latest["fingerprint"],
        "source changed during scan; retry on a stable snapshot",
    )
    previous_snapshot = state.get("snapshot")
    prior_entries = state.get("inventory", {}).get("entries", {})
    moves = detect_moves(prior_entries, live["entries"])
    old_profile = state.get("observation_profile")
    changed_parser = state.get("parser_profile") != parser_profile
    if snapshot != previous_snapshot:
        remember_previous_units(state)
    reconcile_baseline(state, store, live, scope_inputs)
    candidates = analyzed.pop("candidates")
    if not args.full:
        refine_work_reasons(
            analyzed["detector_work"], prior_entries, live["entries"], changed_parser
        )
    state.update(
        root=str(scope.root),
        scope=scope.scopes,
        thresholds=scope.thresholds,
        inventory=live,
        snapshot=snapshot,
        scan=analyzed,
        capabilities=caps,
        observation_profile=profile,
        parser_profile=parser_profile,
        core_only=args.core_only,
        scope_inputs=scope_inputs,
        scope_evidence_version=SCOPE_EVIDENCE_VERSION,
        moves=moves,
        rubric=rubric,
        units=units,
        scan_revision=state["revision"] + 1,
        scan_repeated_snapshot=previous_snapshot == snapshot,
    )
    for observation in candidates:
        observe(state, observation | {"detector_profile": profile})
    if args.checkpoint:
        checkpoint_progress(state)
    with store.transaction():
        store.assert_revision(state["revision"])
        store.cache(fresh)
        store.delete_detector_cache_outside_profiles(
            {
                current_parser_profile(capabilities(False)),
                current_parser_profile(capabilities(True)),
            }
        )
        store.save(
            state,
            "scan",
            {
                "profile_changed": bool(old_profile) and old_profile != profile,
                "previous_snapshot": previous_snapshot,
                "moves": moves,
                "checkpoint": args.checkpoint,
                "idle_cycles": state["idle_cycles"],
                "inventory_fingerprint": live["fingerprint"],
                "scope_inputs": scope_inputs,
            },
        )
    return live


def scan_is_current(store, state, current, files, thresholds, read_history):
    if state.get("scope_evidence_version") != SCOPE_EVIDENCE_VERSION:
        return False
    core_only = state["core_only"]
    parser_profile, profile = analyzer_profiles(thresholds, capabilities(core_only))
    rubric = rubric_version()
    if profile != state["observation_profile"] or rubric != state["rubric"]:
        return False
    if current["fingerprint"] == state["inventory"]["fingerprint"]:
        return True
    analyzed, _ = scan_sources(
        current,
        files,
        thresholds,
        ParseOptions(parser_profile, core_only, store.cached, False),
        read_history(),
    )
    _, snapshot, _ = scope_evidence(current, analyzed, profile, rubric)
    return snapshot == state["snapshot"]


def current_inventory(store, state, scope):
    current, files = scope.collect()
    if (
        state.get("scope_inputs")
        and state["inventory"]["fingerprint"] != current["fingerprint"]
    ):
        current, files = scope.collect(gather=True)
    return current, scan_is_current(
        store, state, current, files, scope.thresholds, scope.history
    )
