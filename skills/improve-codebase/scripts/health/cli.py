import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from functools import partial
from itertools import islice
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
from .runs import current_run, fallout_scope, run_name, slice_configuration
from .scoring import evaluate
from .state import (
    Store,
    array,
    detect_moves,
    object_value,
    observe,
    read_json,
    require,
    safe_state_dir,
    string,
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
    parser.add_argument("--run", help="resume a named run or slice in this worktree")
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
        if cmd != "doctor" and cmd != "report":
            command.add_argument(
                "--summary",
                action="store_true",
                help="omit detailed inventories and queues",
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
    runs = sub.add_parser(
        "run", help="save or list resumable worktree runs and slices"
    ).add_subparsers(dest="action", required=True)
    start = runs.add_parser(
        "start", help="name a scope and optionally derive it from a Git diff"
    )
    options(start)
    start.add_argument("name")
    start.add_argument("--base", help="Git base commit for fallout mode")
    start.add_argument(
        "--include",
        action="append",
        default=[],
        help="additional affected path for fallout mode",
    )
    view = runs.add_parser("slice", help="name a view of a parent run's backlog")
    options(view)
    view.add_argument("name")
    view.add_argument(
        "--path",
        action="append",
        required=True,
        help="path inside the parent scope; repeat as needed",
    )
    options(runs.add_parser("list", help="list the runs in this state directory"))
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
        "--unit",
        action="append",
        default=[],
        help="select this exact unit ID; repeat as needed",
    )
    packet.add_argument(
        "--path", action="append", help="select units touching a path; repeat as needed"
    )
    packet.add_argument(
        "--receipt-template",
        action="store_true",
        help="include an unfilled receipt in JSON output",
    )
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
            help="JSON with revision and snapshot plus a single event or an atomic updates/records array",
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
                **unit,
                "file_hashes": [unit["context"][p] for p in unit["files"]],
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
    if (
        state.get("baseline_inputs")
        and state["baseline_inputs"] == state.get("scope_inputs")
        and previous_inventory.get("fingerprint") == live["fingerprint"]
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


def configure_run(args, store, root, is_git, state_dir, scopes, thresholds):
    if args.action == "list":
        require(
            not (args.run or args.scope or args.thresholds),
            "run list does not take a run, scope, or thresholds",
        )
        return {"runs": store.runs()}
    name = run_name(args.name)
    require(
        name not in store.runs(), f"run {name!r} already exists; resume it with --run"
    )
    if args.action == "slice":
        require(args.run, "pass --run with the parent run name")
        configuration = slice_configuration(
            root, args.run, current_run(store, args.run), args.path
        )
    else:
        require(not args.run, "pass the new run name as a positional argument")
        require(args.base or not args.include, "--include requires --base")
        configuration = {"root": str(root), "scope": scopes, "thresholds": thresholds}
        if args.base:
            require(is_git, "fallout mode requires a Git worktree")
            paths, fallout = fallout_scope(
                root, state_dir, scopes, args.base, args.include
            )
            configuration.update(scope=paths, fallout=fallout)
    with store.transaction():
        require(
            name not in store.runs(),
            f"run {name!r} already exists; resume it with --run",
        )
        store.save_run(name, configuration)
    return {"run": name, "configuration": configuration}


def record_batch(args, store, state, document, entries, root, state_dir):
    finding = args.command == "finding"
    key = "updates" if finding else "records"
    kind = "finding" if finding else "verification"
    if key in document:
        require(
            document.keys() == {"revision", "snapshot", key},
            "batch requires only revision, snapshot, and event list",
        )
        events = array(document, key)
        require(events, "batch must not be empty")
    else:
        events = [document]
    results, seen = [], set()
    for value in events:
        event = object_value(value, "batch event")
        require(key not in event, "nested batches are not supported")
        if key in document:
            require(
                not {"revision", "snapshot"} & event.keys(),
                "put revision and snapshot on the batch, not each event",
            )
            identifier = (
                None
                if not finding and event.get("kind") == "manifest"
                else string(event, "id")
            )
            require(
                identifier not in seen, "duplicate event for the same ID in a batch"
            )
            seen.add(identifier)
            event = event | {"snapshot": document["snapshot"]}
        results.append(
            triage(store, state, event, state_dir, entries)
            if finding
            else record_verification(state, event, root, state_dir)
        )
    result = results if key in document else results[0]
    if key in document:
        store.save(state, f"{kind}_batch", {key: result})
    else:
        store.save(state, kind, {"finding" if finding else "record": result})
    return result


def execute(args, envelope):
    root, is_git = discover_root(args.root)
    require(
        not args.run or not (args.scope or args.thresholds),
        "named runs already specify scope and thresholds",
    )
    scopes = normalize_scope(root, args.scope)
    thresholds = settings(read_json(args.thresholds) if args.thresholds else {})
    run_write = args.command == "run" and args.action != "list"
    writes = run_write or args.command in {
        "scan",
        "review",
        "import-diagnostics",
        "finding",
        "verification",
    }
    initialize = not args.run and (args.command == "scan" or run_write)
    state_dir = safe_state_dir(root, is_git, args.state_dir, initialize)
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
    if writes and not initialize:
        require(
            (state_dir / "state.sqlite3").is_file(),
            "no named run ledger in this worktree"
            if args.run
            else "scan before recording evidence",
        )
        state_dir = safe_state_dir(root, is_git, args.state_dir, True)
    store = Store(state_dir / "state.sqlite3", root, scopes, thresholds, write=writes)
    try:
        if args.command == "run":
            return configure_run(
                args, store, root, is_git, state_dir, scopes, thresholds
            ), 0
        run = current_run(store, args.run) if args.run else {}
        view = run.get("slice")
        base = run.get("fallout", {}).get("base")
        if run:
            scopes, thresholds = run["scope"], run["thresholds"]
            store.select(scopes, thresholds, base)
            envelope.update(run=args.run, scope=scopes, fallout=run.get("fallout"))
        collect = partial(inventory, root, is_git, scopes, state_dir)
        state = store.load()
        if base:
            state["fallout_base"] = base
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
                        include=args.unit,
                        paths=normalize_scope(root, args.path) if args.path else [],
                        slice_paths=view["paths"] if view else [],
                        template=args.receipt_template,
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
                    else:
                        result = record_batch(
                            args, store, state, document, entries, root, state_dir
                        )
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
            view=view,
            summary=getattr(args, "summary", False),
        )
        report.update(
            revision=state["revision"],
            snapshot=state.get("snapshot"),
            baseline_snapshot=state.get("baseline_snapshot"),
            profile=store.key,
        )
        report["command"] = args.command
        if args.command in {"scan", "report"} and not getattr(args, "summary", False):
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
        if args.command == "next" and not args.summary:
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
    if output.get("run"):
        lines.append(f"Run: {output['run']}")
    if view := output.get("slice"):
        counts = view["coverage"]
        lines.append(
            f"Slice: {counts['discovery']}/{counts['total']} discovery, {counts['confirmation']}/{counts['total']} confirmation; {'verified' if view['verified'] else 'partial'}. The completion gate applies to {view['parent']}."
        )
    if output.get("fallout"):
        lines.append(
            f"Fallout base: {output['fallout']['base']}; classifications: {output.get('change_relations', {})}"
        )
    if output["unmet"]:
        lines.append("Unmet: " + ", ".join(output["unmet"]))
    for item in output["verification_unmet"]:
        lines.append(f"  {item}")
    failures = output["capability_failures"]
    for item in failures[:12]:
        lines.append(
            f"  Scanner gap {item['path']!r}: {item['surface']} {item['kind']} ({item.get('reason', 'see range in JSON')})"
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
    if output["command"] == "next" and isinstance(work.get("discovery"), list):
        due = (
            item
            for stage in STAGES
            for item in work[stage]
            if item.get("changed_inputs")
        )
        for item in islice(due, 3):
            details = {
                key: value[:5] if isinstance(value, list) else value
                for key, value in item["changed_inputs"].items()
            }
            lines.append(f"  {item['axis']} {item['id']}: {details!r}")
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
