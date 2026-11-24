from dataclasses import dataclass
from pathlib import Path

from .detectors import scan_sources
from .hashing import content_hash, digest
from .history import commit_history, hotspots
from .inventory import inventory
from .ledger import claim_order, detect_moves, observe, relocation_destination
from .parsers import ParseOptions, capabilities, parser_cache_prefix
from .profiles import analyzer_profiles, current_parser_profile
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


def surviving_relocations(state, live, moves):
    merged_relocations = {
        old: new
        for old, new in state.get("relocations", {}).items()
        if not live["entries"].get(old, {}).get("hash")
    } | moves
    return {
        old: new
        for old, new in merged_relocations.items()
        if relocation_destination(merged_relocations, old, live["entries"]) is not None
    }


def kept_cache_prefixes(parser_profile, core_only):
    return {
        parser_cache_prefix(parser_profile),
        parser_cache_prefix(current_parser_profile(capabilities(not core_only))),
    }


def save_scan(store, state, fresh, kept_prefixes, event):
    with store.transaction():
        store.assert_revision(state["revision"])
        store.cache(fresh)
        store.delete_detector_cache_outside_prefixes(kept_prefixes)
        store.save(state, "scan", event)


def require_stable_source(scope, live):
    latest, _ = scope.collect()
    require(
        live["fingerprint"] == latest["fingerprint"],
        "source changed during scan; retry on a stable snapshot",
    )


def scan(store, state, scope, *, core_only, full, checkpoint):
    live, files = scope.collect(gather=True)
    caps = capabilities(core_only)
    parser_profile, profile = analyzer_profiles(scope.thresholds, caps)
    rubric = rubric_version()
    analyzed, fresh = scan_sources(
        live,
        files,
        scope.thresholds,
        ParseOptions(parser_profile, core_only, store.cached, full),
        scope.history(),
    )
    scope_inputs, snapshot, units = scope_evidence(live, analyzed, profile, rubric)
    analyzed["hotspots"] = hotspots(scope.root, scope.is_git, analyzed["metrics"])
    require_stable_source(scope, live)
    previous_snapshot = state.get("snapshot")
    prior_entries = state.get("inventory", {}).get("entries", {})
    moves = detect_moves(prior_entries, live["entries"])
    relocations = surviving_relocations(state, live, moves)
    old_profile = state.get("observation_profile")
    changed_parser = state.get("parser_profile") != parser_profile
    if snapshot != previous_snapshot:
        remember_previous_units(state)
    reconcile_baseline(state, store, live, scope_inputs)
    candidates = analyzed.pop("candidates")
    if not full:
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
        core_only=core_only,
        scope_inputs=scope_inputs,
        scope_evidence_version=SCOPE_EVIDENCE_VERSION,
        moves=moves,
        relocations=relocations,
        rubric=rubric,
        units=units,
        scan_revision=state["revision"] + 1,
        scan_repeated_snapshot=previous_snapshot == snapshot,
    )
    for observation in claim_order(state, candidates, live["entries"]):
        observe(state, observation | {"detector_profile": profile})
    if checkpoint:
        checkpoint_progress(state)
    save_scan(
        store,
        state,
        fresh,
        kept_cache_prefixes(parser_profile, core_only),
        {
            "profile_changed": bool(old_profile) and old_profile != profile,
            "previous_snapshot": previous_snapshot,
            "moves": moves,
            "checkpoint": checkpoint,
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
