import sys
from dataclasses import dataclass
from pathlib import Path

from .detectors import scan_sources
from .inventory import commit_history, content_hash, digest, hotspots, inventory
from .parsers import capabilities
from .review_units import REVIEW_VERSION, units_for
from .state import detect_moves, observe, require
from .verification import restore_legacy_baseline

SKILL = Path(__file__).resolve().parents[2]
REF = SKILL / "references" / "smell-guide.md"
SCOPE_EVIDENCE_VERSION = 1
HISTORY_RULES = frozenset({"change-coupling"})


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


def analyzer_profiles(thresholds, caps):
    parser = digest(
        [
            caps,
            sys.version_info[:3],
            *(
                module_hash(name)
                for name in (
                    "inventory",
                    "parsers",
                    "syntax_tree",
                    "comments",
                    "case_inventory",
                )
            ),
        ]
    )
    detector = digest(
        [
            parser,
            thresholds,
            *(
                module_hash(name)
                for name in ("detectors", "dependency_graph", "layout")
            ),
        ]
    )
    return parser, detector


def module_hash(name):
    return content_hash(Path(__file__).with_name(f"{name}.py").read_bytes())


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
    scope_inputs = digest(
        [live["scope_fingerprint"], context, [], sorted(relationships)]
    )
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


def reconcile_baseline(state, store, live, scope_inputs):
    baseline = state.get("baseline_snapshot")
    if baseline and not state.get("scope_inputs"):
        restore_legacy_baseline(state)
    if state.get("baseline_snapshot") and not state.get("baseline_inputs"):
        # A legacy scan can establish the baseline only on its exact original inventory.
        if any(
            event["kind"] == "scan"
            and event["snapshot"] == state["baseline_snapshot"]
            and event.get("inventory_fingerprint") == live["fingerprint"]
            and "scope_inputs" not in event
            for event in store.history()
        ):
            state["baseline_inputs"] = scope_inputs
    if (
        state.get("baseline_inputs")
        and state["baseline_inputs"] == state.get("scope_inputs")
        and state.get("inventory", {}).get("fingerprint") == live["fingerprint"]
    ):
        state["baseline_inputs"] = scope_inputs


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
        parser_profile,
        args.core_only,
        store.cached,
        args.full,
        scope.history(),
    )
    scope_inputs, snapshot, units = scope_evidence(live, analyzed, profile, rubric)
    analyzed["hotspots"] = hotspots(scope.root, scope.is_git, analyzed["detector_work"])
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
    for observation in analyzed.pop("candidates"):
        observe(state, observation | {"detector_profile": profile})
    if not args.full:
        refine_work_reasons(
            analyzed["detector_work"], prior_entries, live["entries"], changed_parser
        )
    if args.checkpoint:
        checkpoint_progress(state)
    with store.transaction():
        store.assert_revision(state["revision"])
        store.cache(fresh)
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
        parser_profile,
        core_only,
        store.cached,
        False,
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
