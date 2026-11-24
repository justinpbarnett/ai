import json
import shutil
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from itertools import islice

from .arguments import CommandHandlers, arguments
from .evidence import STALE_INPUTS, import_evidence
from .inventory import normalize_scope
from .ledger import UNRESOLVED
from .parsers import capabilities
from .review_packets import PacketSelection, prepare
from .review_units import STAGES
from .rules import settings
from .runs import (
    current_run,
    fallout_scope,
    resolve_base_commit,
    run_name,
    slice_configuration,
)
from .scanning import REF, ScanScope, current_inventory, scan
from .scoring import evaluate
from .state import Store, corrupt_database_message, is_corrupt_database
from .state_dir import STATE_DATABASE, discover_root, safe_state_dir
from .validation import read_json, require


def validate_run_arguments(args, root, is_git):
    if args.action == "list":
        require(
            not (args.run or args.scope or args.thresholds),
            "run list does not take a run, scope, or thresholds",
        )
        return
    run_name(args.name)
    if args.action == "slice":
        require(args.run, "pass --run with the parent run name")
    else:
        require(not args.run, "pass the new run name as a positional argument")
        require(args.base or not args.include, "--include requires --base")
        if args.base:
            require(is_git, "fallout mode requires a Git worktree")
            resolve_base_commit(root, args.base)


def plan_fallout(args, root, is_git, scopes, thresholds):
    state_dir = safe_state_dir(root, is_git, args.state_dir, False)
    store = Store(state_dir / STATE_DATABASE, root, scopes, thresholds)
    try:
        require_new_run(store, args.name)
        return fallout_scope(store, root, state_dir, scopes, args.base, args.include)
    finally:
        store.close()


def require_new_run(store, name):
    require(
        name not in store.runs(), f"run {name!r} already exists; resume it with --run"
    )


def configure_run(args, store, scope, plan):
    if args.action == "list":
        return {"runs": store.runs()}
    name = run_name(args.name)
    require_new_run(store, name)
    if args.action == "slice":
        configuration = slice_configuration(
            scope.root, args.run, current_run(store, args.run), args.path
        )
    else:
        configuration = {
            "root": str(scope.root),
            "scope": scope.scopes,
            "thresholds": scope.thresholds,
        }
        if plan:
            paths, fallout = plan
            configuration.update(scope=paths, fallout=fallout)
    with store.transaction():
        require_new_run(store, name)
        store.save_run(name, configuration)
    return {"run": name, "configuration": configuration}


def doctor_report(core_only, is_git, thresholds):
    return {
        "python": sys.version.split()[0],
        "capabilities": capabilities(core_only),
        "tools": {
            tool: shutil.which(tool)
            for tool in ("git", "uv", "ruff", "eslint", "stylelint", "dotnet", "node")
        },
        "smell_guide": str(REF),
        "smell_guide_available": REF.is_file(),
        "git_protection": "local exclude verified before writes"
        if is_git
        else "not a Git worktree",
        "thresholds": thresholds,
    }


def prepare_packet(args, store, state, entries, root, view):
    with store.transaction():
        store.assert_revision(state["revision"])
        selection = PacketSelection(
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
        return prepare(store, state, entries, root, selection)


def base_report(args, store, state, current, fresh, view):
    summary = getattr(args, "summary", False)
    report = evaluate(
        store,
        state,
        current,
        store.path.parent,
        fresh,
        REF.is_file(),
        getattr(args, "target", 0),
        view=view,
        summary=summary,
    )
    report.update(
        revision=state["revision"],
        snapshot=state.get("snapshot"),
        baseline_snapshot=state.get("baseline_snapshot"),
        profile=store.key,
    )
    report["command"] = args.command
    return report


def inventory_fields(state, current, fresh):
    return dict(
        inventory=current if fresh else state.get("inventory", current),
        scan=state.get("scan"),
        moves=state.get("moves", {}),
        findings=list(state["findings"].values()),
        capabilities=state.get("capabilities"),
    )


def scan_report(args, store, state, current, fresh, view):
    report = base_report(args, store, state, current, fresh, view)
    if not args.summary:
        report.update(inventory_fields(state, current, fresh))
    return report


def next_report(args, store, state, current, fresh, view):
    report = base_report(args, store, state, current, fresh, view)
    if not args.summary:
        report["backlog"] = [
            f for f in state["findings"].values() if f["status"] in UNRESOLVED
        ]
    return report


def full_report(args, store, state, current, fresh, view):
    report = base_report(args, store, state, current, fresh, view)
    report.update(inventory_fields(state, current, fresh))
    report.update(
        verification=state["verification"],
        original_baseline=state.get("original_baseline", {}),
        verification_manifest=state["manifest"],
        history=store.history(),
        diagnostic_runs=state.get("diagnostic_runs", {}),
    )
    return report


def command_workspace(args, envelope):
    root, is_git = discover_root(args.root)
    require(
        not args.run or not (args.scope or args.thresholds),
        "named runs already specify scope and thresholds",
    )
    scopes = normalize_scope(root, args.scope)
    thresholds = settings(read_json(args.thresholds) if args.thresholds else {})
    plan = None
    if args.command == "run":
        validate_run_arguments(args, root, is_git)
        if args.action == "start" and args.base:
            plan = plan_fallout(args, root, is_git, scopes, thresholds)
    initialize = not args.run and args.writes and args.command in {"scan", "run"}
    state_dir = safe_state_dir(root, is_git, args.state_dir, initialize)
    envelope.update(
        root=str(root),
        git_worktree=is_git,
        scope=scopes,
        state_dir=str(state_dir),
        state_path=str(state_dir / STATE_DATABASE),
    )
    if args.writes and not initialize:
        require(
            (state_dir / STATE_DATABASE).is_file(),
            "no named run ledger in this worktree"
            if args.run
            else "scan before recording evidence",
        )
        state_dir = safe_state_dir(root, is_git, args.state_dir, True)
    return ScanScope(root, is_git, scopes, thresholds, state_dir), plan


def doctor_command(args, scope, envelope):
    return doctor_report(args.core_only, scope.is_git, scope.thresholds), 0


@contextmanager
def open_store(args, scope):
    store = Store(
        scope.state_dir / STATE_DATABASE,
        scope.root,
        scope.scopes,
        scope.thresholds,
        write=args.writes,
    )
    try:
        yield store
    finally:
        store.close()


def run_command(args, scope, envelope, plan=None):
    with open_store(args, scope) as store:
        return configure_run(args, store, scope, plan), 0


def load_ledger(args, store, scope, envelope):
    run = current_run(store, args.run) if args.run else {}
    view = run.get("slice")
    base = run.get("fallout", {}).get("base")
    if run:
        scope = replace(
            scope, scopes=run["scope"], thresholds=settings(run["thresholds"])
        )
        store.select(scope.scopes, scope.thresholds, base)
        envelope.update(run=args.run, scope=scope.scopes, fallout=run.get("fallout"))
    state = store.load()
    if base:
        state["fallout_base"] = base
    require(getattr(args, "target", 0) >= 0, "debt target must not be negative")
    return scope, state, view


def scan_command(args, scope, envelope):
    with open_store(args, scope) as store:
        scope, state, view = load_ledger(args, store, scope, envelope)
        current = scan(
            store,
            state,
            scope,
            core_only=args.core_only,
            full=args.full,
            checkpoint=args.checkpoint,
        )
        return scan_report(args, store, state, current, True, view), 0


def report_for(build, args, scope, envelope):
    with open_store(args, scope) as store:
        scope, state, view = load_ledger(args, store, scope, envelope)
        current, fresh = current_inventory(store, state, scope)
        return build(args, store, state, current, fresh, view)


def status_command(args, scope, envelope):
    return report_for(base_report, args, scope, envelope), 0


def next_command(args, scope, envelope):
    return report_for(next_report, args, scope, envelope), 0


def report_command(args, scope, envelope):
    return report_for(full_report, args, scope, envelope), 0


def complete_command(args, scope, envelope):
    report = report_for(base_report, args, scope, envelope)
    return report, int(not report["complete"])


def fresh_ledger(args, store, scope, envelope):
    scope, state, view = load_ledger(args, store, scope, envelope)
    current, fresh = current_inventory(store, state, scope)
    require(fresh, STALE_INPUTS)
    return scope, state, current, view


def prepare_command(args, scope, envelope):
    with open_store(args, scope) as store:
        scope, state, current, view = fresh_ledger(args, store, scope, envelope)
        return prepare_packet(
            args, store, state, current["entries"], scope.root, view
        ), 0


def evidence_command(args, scope, envelope):
    with open_store(args, scope) as store:
        scope, state, current, _ = fresh_ledger(args, store, scope, envelope)
        return import_evidence(args, store, state, current, scope), 0


HANDLERS = CommandHandlers(
    doctor=doctor_command,
    scan=scan_command,
    status=status_command,
    next=next_command,
    report=report_command,
    complete=complete_command,
    run=run_command,
    prepare=prepare_command,
    evidence=evidence_command,
)


def execute(args, envelope):
    scope, plan = command_workspace(args, envelope)
    if plan:
        return args.handler(args, scope, envelope, plan)
    return args.handler(args, scope, envelope)


def scope_lines(output):
    coverage = output["coverage"]
    yield f"Scope: {', '.join(map(repr, output['scope']))}"
    yield f"Debt: {output['strict_debt_points']} points; {output['candidate_count']} candidates, {output['blocked_count']} blocked, {output['accepted_risk_count']} accepted risks"
    yield f"Coverage: {coverage['discovery']}/{coverage['total']} discovery, {coverage['confirmation']}/{coverage['total']} confirmation; {coverage['independence']}"
    yield f"Revision: {output['revision']}; snapshot: {output['snapshot']}"
    yield f"Next: {output['next_phase']}"
    if output.get("run"):
        yield f"Run: {output['run']}"
    if view := output.get("slice"):
        counts = view["coverage"]
        yield f"Slice: {counts['discovery']}/{counts['total']} discovery, {counts['confirmation']}/{counts['total']} confirmation; {'verified' if view['verified'] else 'partial'}. The completion gate applies to {view['parent']}."
    if output.get("fallout"):
        yield f"Fallout base: {output['fallout']['base']}; classifications: {output.get('change_relations', {})}"


def blocker_lines(output):
    if output["unmet"]:
        yield "Unmet: " + ", ".join(output["unmet"])
    for item in output["verification_unmet"]:
        yield f"  {item}"
    failures = output["capability_failures"]
    for item in failures[:12]:
        yield f"  Scanner gap {item['path']!r}: {item['surface']} {item['kind']} ({item.get('reason', 'see range in JSON')})"
    if len(failures) > 12:
        yield f"  {len(failures) - 12} more capability failures; see report JSON."


def finding_lines(output):
    ready = output["ready_findings"]
    if output["next_phase"] == "transform" and ready:
        yield f"Next ready finding: {ready[0]}"
    findings = output.get("findings", output.get("backlog", []))
    limit = len(findings) if "history" in output else 24
    for item in findings[:limit]:
        loc = item["location"]
        yield f"{item['id']} {item['status']}: {item['rule']} at {loc['path']!r}:{loc.get('line', 1)} ({item['anchor']!r})"
    if len(findings) > limit:
        yield f"{len(findings) - limit} more findings; use report for the full list."
    if output.get("history"):
        points = " → ".join(
            str(row["strict_debt_points"]) for row in output["history"][-8:]
        )
        yield f"Recent debt points by recorded revision: {points}"


def review_lines(output):
    work = output["review_work"]
    yield "Review work: " + ", ".join(
        f"{work[key]} {key}"
        for key in ("reused", "new", "changed", "invalidated", "pending")
    )
    if "backlog" in output and isinstance(work.get("discovery"), list):
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
            yield f"  {item['axis']} {item['id']}: {details!r}"
    if output["other_scope_or_profile_debt"]:
        yield f"Known debt in {len(output['other_scope_or_profile_debt'])} other scope/profile run(s); this result does not close them."


def render_text(output):
    state_line = f"State: {output['state_path']}"
    if "strict_debt_points" not in output:
        return "\n".join((state_line, json.dumps(output, indent=2, ensure_ascii=True)))
    return "\n".join(
        (
            state_line,
            *scope_lines(output),
            *blocker_lines(output),
            *finding_lines(output),
            *review_lines(output),
        )
    )


def main(argv=None):
    args = arguments(argv, HANDLERS)
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
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as exc:
        error, code = str(exc), 2
    except (ValueError, RecursionError) as exc:
        error, code = str(exc), 2
    except sqlite3.DatabaseError as exc:
        if is_corrupt_database(exc):
            error, code = corrupt_database_message(exc), 2
        else:
            error, code = str(exc), 3
    except (OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        error, code = str(exc), 3
    except KeyboardInterrupt:
        error, code = "interrupted; no partial updates committed", 3
    except Exception as exc:
        error, code = f"{type(exc).__name__}: {exc}", 3
    print(f"improve-codebase: {error}", file=sys.stderr)
    if args.format == "json":
        print(
            json.dumps(
                envelope | {"complete": False, "error": error, "exit_status": code},
                ensure_ascii=True,
            )
        )
    return code
