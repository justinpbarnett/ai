import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from functools import partial
from pathlib import Path

from .detectors import scan_sources, settings
from .diagnostics import FORMATS, ingest
from .inventory import (
    content_hash,
    digest,
    discover_root,
    hotspots,
    inventory,
    normalize_scope,
)
from .parsers import capabilities
from .review import (
    AXES,
    REVIEW_VERSION,
    STAGES,
    import_review,
    prepare,
    record_verification,
    restore_legacy_baseline,
    triage,
    units_for,
)
from .scoring import evaluate
from .state import (
    Store,
    detect_moves,
    object_value,
    observe,
    read_json,
    require,
    safe_state_dir,
)

SKILL = Path(__file__).resolve().parents[2]
REF = SKILL / "references" / "smell-guide.md"
SCOPE_EVIDENCE_VERSION = 1


def options(parser):
    parser.add_argument(
        "--root", default=".", help="project directory (Git uses its worktree root)"
    )
    parser.add_argument(
        "--scope",
        action="append",
        help="repeatable worktree-relative path, defaults to all authored files",
    )
    parser.add_argument(
        "--state-dir",
        help="explicit state directory; default is <root>/.improve-codebase",
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        help="local JSON overriding individual detector sensitivity thresholds",
    )
    parser.add_argument(
        "--format", choices=("text", "json"), default="text", help="output format"
    )


def arguments(argv):
    parser = argparse.ArgumentParser(
        description="Investigate, track, and verify codebase improvements without rewriting source."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd, description in {
        "doctor": "inspect capabilities and optional tool locations",
        "scan": "refresh inventory, use valid detector history, and queue new candidates",
        "status": "show debt, coverage, fresh evidence, and unmet gates",
        "next": "show the next safe phase and dependency-ready findings",
        "report": "show the inventory, findings, and history",
        "complete": "return 0 only if clean completion is currently evidenced",
    }.items():
        command = sub.add_parser(cmd, help=description)
        options(command)
        if cmd in {"doctor", "scan"}:
            command.add_argument(
                "--core-only", action="store_true", help="run without optional parsers"
            )
        if cmd == "scan":
            command.add_argument(
                "--full", action="store_true", help="recompute every mechanical result"
            )
            command.add_argument(
                "--checkpoint",
                action="store_true",
                help="mark the end of one real investigation/fix cycle for stall detection",
            )
        if cmd in {"status", "next", "report", "complete"}:
            command.add_argument(
                "--target",
                type=int,
                default=0,
                help="report a debt target without changing clean completion",
            )
    review = sub.add_parser(
        "review", help="prepare score-blind packets or import review receipts"
    ).add_subparsers(dest="action", required=True)
    packet = review.add_parser(
        "prepare", help="create one bounded packet from the current scan"
    )
    options(packet)
    packet.add_argument("--axis", choices=AXES)
    packet.add_argument("--pass", dest="stage", choices=STAGES)
    packet.add_argument(
        "--partition", help="filter to a project partition named in the report"
    )
    packet.add_argument(
        "--exclude-unit",
        action="append",
        default=[],
        help="skip an already delegated unit ID; repeat as needed",
    )
    packet.add_argument(
        "--limit", type=int, default=12, help="maximum assigned units (1–50)"
    )
    packet.add_argument(
        "--full",
        action="store_true",
        help="include already investigated units; use --exclude-unit to paginate",
    )
    receipt = review.add_parser(
        "import", help="record review coverage and findings atomically"
    )
    options(receipt)
    receipt.add_argument(
        "--input", type=Path, required=True, help="JSON response to a prepared packet"
    )
    for name, action, description in (
        ("finding", "update", "triage or transition a finding with evidence"),
        (
            "verification",
            "record",
            "record required checks and before/after observations",
        ),
    ):
        command = (
            sub.add_parser(name, help=description)
            .add_subparsers(dest="action", required=True)
            .add_parser(action)
        )
        options(command)
        command.add_argument(
            "--input",
            type=Path,
            required=True,
            help="JSON update with expected revision and current snapshot",
        )
    importer = sub.add_parser(
        "import-diagnostics", help="import a local machine-readable diagnostic report"
    )
    options(importer)
    importer.add_argument("--tool", choices=FORMATS, required=True)
    importer.add_argument(
        "--input", type=Path, required=True, help="local tool JSON/SARIF output"
    )
    importer.add_argument(
        "--metadata",
        type=Path,
        required=True,
        help="JSON recording provenance, coverage, and tool exit status",
    )
    return parser.parse_args(argv)


def analyzer_profiles(thresholds, caps):
    parser = digest(
        [caps, sys.version_info[:3], module_hash("inventory"), module_hash("parsers")]
    )
    detector = digest([parser, thresholds, module_hash("detectors")])
    return parser, detector


def module_hash(name):
    return content_hash(Path(__file__).with_name(f"{name}.py").read_bytes())


def rubric_version():
    return digest(
        [
            REVIEW_VERSION,
            *(
                content_hash(path.read_bytes()) if path.is_file() else None
                for path in (REF, SKILL / "references" / "workflow.md")
            ),
        ]
    )


def scope_evidence(live, analyzed, profile, rubric):
    units = units_for(live, analyzed, rubric)
    context, partitions, relationships = {}, set(), set()
    for unit in units.values():
        context.update(unit["context"])
        if unit["partition_fingerprint"] is not None:
            partitions.add(unit["partition_fingerprint"])
        relationships.update(unit["relationships"])
    scope_inputs = digest(
        [live["scope_fingerprint"], context, sorted(partitions), sorted(relationships)]
    )
    snapshot = digest(
        [
            SCOPE_EVIDENCE_VERSION,
            scope_inputs,
            profile,
            rubric,
            sorted(unit["inputs"] for unit in units.values()),
            sorted(digest(item) for item in analyzed["candidates"]),
            sorted(digest(item) for item in analyzed["gaps"]),
        ]
    )
    return scope_inputs, snapshot, units


def scan(args, store, state, thresholds, collect, root, is_git, scopes):
    live, files = collect(gather=True)
    caps = capabilities(args.core_only)
    parser_profile, profile = analyzer_profiles(thresholds, caps)
    rubric = rubric_version()
    analyzed, fresh = scan_sources(
        live, files, thresholds, parser_profile, args.core_only, store.cached, args.full
    )
    scope_inputs, snapshot, units = scope_evidence(live, analyzed, profile, rubric)
    analyzed["hotspots"] = hotspots(root, is_git, analyzed["detector_work"])
    # Do not commit mixed-source data if files changed during analysis.
    latest, _ = collect()
    require(
        live["fingerprint"] == latest["fingerprint"],
        "source changed during scan; retry on a stable snapshot",
    )
    moves = detect_moves(state.get("inventory", {}).get("entries", {}), live["entries"])
    changed_profile = (
        bool(state.get("observation_profile"))
        and state["observation_profile"] != profile
    )
    old_units = state.get("units", {})
    if snapshot != state.get("snapshot"):
        state["previous_units"] = {
            key: {
                "inputs": unit["inputs"],
                "files": [unit["context"][p] for p in unit["files"]],
            }
            for key, unit in old_units.items()
        }
    previous_snapshot = state.get("snapshot")
    previous_inventory = state.get("inventory", {})
    if state.get("baseline_snapshot") and not state.get("scope_inputs"):
        restore_legacy_baseline(state)
    if state.get("baseline_snapshot") and not state.get("baseline_inputs"):
        # Legacy scans can establish the baseline only on their original, exact inventory.
        if any(
            event["kind"] == "scan"
            and event["snapshot"] == state["baseline_snapshot"]
            and event.get("inventory_fingerprint") == live["fingerprint"]
            and "scope_inputs" not in event
            for event in store.history()
        ):
            state["baseline_inputs"] = scope_inputs
    changed_parser = state.get("parser_profile") != parser_profile
    state.update(
        root=str(root),
        scope=scopes,
        thresholds=thresholds,
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
    prior_entries = previous_inventory.get("entries", {})
    for path, work in analyzed["detector_work"].items():
        if work["status"] == "reused":
            continue
        if path not in prior_entries:
            work["reason"] = "new source path" if not args.full else work["reason"]
        elif (
            prior_entries[path].get("hash") != live["entries"][path].get("hash")
            and not args.full
        ):
            work["reason"] = "source content changed"
        elif changed_parser and not args.full:
            work["reason"] = "parser version or capability changed"
    if args.checkpoint:
        if state["progress"] > state["progress_at_checkpoint"]:
            state["idle_cycles"] = 0
        else:
            state["idle_cycles"] += 1
        state["progress_at_checkpoint"] = state["progress"]
    with store.transaction():
        store.assert_revision(state["revision"])
        store.cache(fresh)
        store.save(
            state,
            "scan",
            {
                "profile_changed": changed_profile,
                "previous_snapshot": previous_snapshot,
                "moves": moves,
                "checkpoint": args.checkpoint,
                "idle_cycles": state["idle_cycles"],
                "inventory_fingerprint": live["fingerprint"],
                "scope_inputs": scope_inputs,
            },
        )
    return live


def scan_is_current(store, state, current, files, thresholds):
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
        current, files, thresholds, parser_profile, core_only, store.cached, False
    )
    _, snapshot, _ = scope_evidence(current, analyzed, profile, rubric)
    return snapshot == state["snapshot"]


def current_inventory(store, state, thresholds, collect):
    current, files = collect()
    if (
        state.get("scope_inputs")
        and state["inventory"]["fingerprint"] != current["fingerprint"]
    ):
        current, files = collect(gather=True)
    return current, scan_is_current(store, state, current, files, thresholds)


def execute(args, envelope):
    root, is_git = discover_root(args.root)
    scopes = normalize_scope(root, args.scope)
    thresholds = settings(read_json(args.thresholds) if args.thresholds else {})
    writes = args.command in {
        "scan",
        "review",
        "import-diagnostics",
        "finding",
        "verification",
    }
    # Only a scan initializes an ignored state location.
    state_dir = safe_state_dir(root, is_git, args.state_dir, args.command == "scan")
    envelope.update(
        root=str(root),
        git_worktree=is_git,
        scope=scopes,
        state_dir=str(state_dir),
        state_path=str(state_dir / "state.sqlite3"),
    )
    if args.command == "doctor":
        return {
            "python": sys.version.split()[0],
            "capabilities": capabilities(args.core_only),
            "tools": {
                tool: shutil.which(tool)
                for tool in (
                    "git",
                    "uv",
                    "ruff",
                    "eslint",
                    "stylelint",
                    "dotnet",
                    "node",
                )
            },
            "smell_guide": str(REF),
            "smell_guide_available": REF.is_file(),
            "git_protection": "local exclude verified before writes"
            if is_git
            else "not a Git worktree",
            "thresholds": thresholds,
        }, 0
    if writes and args.command != "scan":
        require(
            (state_dir / "state.sqlite3").is_file(), "scan before recording evidence"
        )
        state_dir = safe_state_dir(root, is_git, args.state_dir, True)
    collect = partial(inventory, root, is_git, scopes, state_dir)
    store = Store(state_dir / "state.sqlite3", root, scopes, thresholds, write=writes)
    try:
        state = store.load()
        target = getattr(args, "target", 0)
        require(target >= 0, "debt target must not be negative")
        if args.command == "scan":
            current = scan(
                args, store, state, thresholds, collect, root, is_git, scopes
            )
            fresh = True
        else:
            current, fresh = current_inventory(store, state, thresholds, collect)
        entries = current["entries"]
        stale_message = "scan before writing evidence: inputs are stale or unscanned"
        if writes and args.command != "scan":
            require(fresh, stale_message)
            if args.command == "review" and args.action == "prepare":
                require(1 <= args.limit <= 50, "packet limit must be between 1 and 50")
                with store.transaction():
                    store.assert_revision(state["revision"])
                    result = prepare(
                        store,
                        state,
                        entries,
                        root=root,
                        axis=args.axis,
                        stage=args.stage,
                        limit=args.limit,
                        full=args.full,
                        exclude=args.exclude_unit,
                        partition=args.partition,
                    )
                return result, 0
            document = object_value(
                read_json(
                    args.metadata
                    if args.command == "import-diagnostics"
                    else args.input
                ),
                "input",
            )
            with store.transaction():
                if args.command == "review":
                    # Independent packets use snapshot + exact-context checks, not the last packet's revision.
                    latest = store.load()
                    if latest["revision"] != state["revision"]:
                        latest_inventory, fresh = current_inventory(
                            store, latest, thresholds, collect
                        )
                        require(
                            fresh
                            and latest_inventory["fingerprint"]
                            == current["fingerprint"],
                            stale_message,
                        )
                    state = latest
                    result = import_review(store, state, document, entries)
                else:
                    store.assert_revision(
                        document.get(
                            "revision",
                            state["revision"]
                            if args.command == "import-diagnostics"
                            else None,
                        )
                    )
                    store.assert_revision(state["revision"])
                    require(
                        document.get("snapshot") == state["snapshot"],
                        "input snapshot is stale",
                    )
                    if args.command == "import-diagnostics":
                        result = ingest(
                            store, state, root, args.tool, args.input, document
                        )
                    elif args.command == "finding":
                        result = triage(store, state, document, state_dir, entries)
                        store.save(state, "finding", {"finding": result})
                    else:
                        result = record_verification(state, document, root, state_dir)
                        store.save(state, "verification", {"record": result})
                current_again, _ = collect()
                require(
                    current_again["fingerprint"] == current["fingerprint"],
                    "source changed during import; no evidence was committed",
                )
            return {
                "revision": state["revision"],
                "snapshot": state["snapshot"],
                "result": result,
            }, 0
        report = evaluate(
            store,
            state,
            current,
            state_dir,
            fresh,
            REF.is_file(),
            target,
        )
        report.update(
            revision=state["revision"],
            snapshot=state.get("snapshot"),
            baseline_snapshot=state.get("baseline_snapshot"),
            profile=store.key,
        )
        report["command"] = args.command
        if args.command in {"scan", "report"}:
            report.update(
                inventory=current if fresh else state.get("inventory", current),
                scan=state.get("scan"),
                moves=state.get("moves", {}),
                findings=list(state["findings"].values()),
                capabilities=state.get("capabilities"),
            )
        if args.command == "report":
            report.update(
                verification=state["verification"],
                original_baseline=state.get("original_baseline", {}),
                verification_manifest=state["manifest"],
                history=store.history(),
                diagnostic_runs=state.get("diagnostic_runs", {}),
            )
        if args.command == "next":
            report["backlog"] = [
                f
                for f in state["findings"].values()
                if f["status"] not in {"resolved", "false_positive", "superseded"}
            ]
        return report, int(args.command == "complete" and not report["complete"])
    finally:
        store.close()


def render_text(output):
    lines = [f"State: {output['state_path']}"]
    if "strict_debt_points" not in output:
        lines.append(json.dumps(output, indent=2, ensure_ascii=True))
        return "\n".join(lines)
    coverage = output["coverage"]
    lines.extend(
        (
            f"Scope: {', '.join(map(repr, output['scope']))}",
            f"Debt: {output['strict_debt_points']} points; {output['candidate_count']} candidates, {output['blocked_count']} blocked, {output['accepted_risk_count']} accepted risks",
            f"Coverage: {coverage['discovery']}/{coverage['total']} discovery, {coverage['confirmation']}/{coverage['total']} confirmation; {coverage['independence']}",
            f"Revision: {output['revision']}; snapshot: {output['snapshot']}",
            f"Next: {output['next_phase']}",
        )
    )
    if output["unmet"]:
        lines.append("Unmet: " + ", ".join(output["unmet"]))
    for item in output["verification_unmet"]:
        lines.append(f"  {item}")
    failures = output["capability_failures"]
    for item in failures[:12]:
        lines.append(
            f"  {item['path']!r}: {item['surface']} {item['kind']} ({item.get('reason', 'see range in JSON')})"
        )
    if len(failures) > 12:
        lines.append(
            f"  {len(failures) - 12} more capability failures; see report JSON."
        )
    ready = output["ready_findings"]
    if output["next_phase"] == "transform" and ready:
        lines.append(f"Next ready finding: {ready[0]}")
    findings = output.get("findings", output.get("backlog", []))
    limit = len(findings) if output["command"] == "report" else 24
    for item in findings[:limit]:
        loc = item["location"]
        lines.append(
            f"{item['id']} {item['status']}: {item['rule']} at {loc['path']!r}:{loc.get('line', 1)} ({item['anchor']!r})"
        )
    if len(findings) > limit:
        lines.append(
            f"{len(findings) - limit} more findings; use report for the full list."
        )
    if output["command"] == "report" and output.get("history"):
        points = " → ".join(
            str(row["strict_debt_points"]) for row in output["history"][-8:]
        )
        lines.append(f"Recent debt points by recorded revision: {points}")
    work = output["review_work"]
    lines.append(
        "Review work: "
        + ", ".join(
            f"{work[key]} {key}"
            for key in ("reused", "new", "changed", "invalidated", "pending")
        )
    )
    if output["other_scope_or_profile_debt"]:
        lines.append(
            f"Known debt in {len(output['other_scope_or_profile_debt'])} other scope/profile run(s); this result does not close them."
        )
    return "\n".join(lines)


def main(argv=None):
    args = arguments(argv)
    envelope = {}
    try:
        payload, code = execute(args, envelope)
        result = envelope | payload
        print(
            json.dumps(result, ensure_ascii=True, allow_nan=False)
            if args.format == "json"
            else render_text(result)
        )
        return code
    except FileNotFoundError as exc:
        error, code = str(exc), 2
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError) as exc:
        error, code = str(exc), 2
    except (OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        error, code = str(exc), 3
    except KeyboardInterrupt:
        error, code = "interrupted; no partial updates committed", 3
    print(f"improve-codebase: {error}", file=sys.stderr)
    if args.format == "json":
        print(
            json.dumps(
                envelope | {"complete": False, "error": error, "exit_status": code},
                ensure_ascii=True,
            )
        )
    return code
