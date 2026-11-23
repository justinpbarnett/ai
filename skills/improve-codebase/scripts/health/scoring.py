from collections import Counter, defaultdict, deque

from .review_units import STAGES, changed_keys, matching_receipts, review_work
from .runs import slice_status
from .state import DEBT, SEVERITIES, finding_prerequisites
from .verification import checks


def fulfilled_prerequisites(findings):
    fulfilled = set()
    awaiting = {}
    superseded_by = defaultdict(list)
    for key, finding in findings.items():
        if finding["status"] == "resolved":
            fulfilled.add(key)
        elif finding["status"] == "superseded":
            replacements = finding_prerequisites(finding)
            awaiting[key] = len(replacements)
            for replacement in replacements:
                superseded_by[replacement].append(key)

    pending = deque(fulfilled)
    while pending:
        for key in superseded_by.pop(pending.popleft(), ()):
            awaiting[key] -= 1
            if awaiting[key] == 0:
                fulfilled.add(key)
                pending.append(key)
    return fulfilled


def ready_findings(findings):
    fulfilled = fulfilled_prerequisites(findings)
    dependants = Counter(
        dependency
        for finding in findings.values()
        if finding["status"] in DEBT
        for dependency in finding_prerequisites(finding)
    )

    return sorted(
        (
            f
            for f in findings.values()
            if f["status"] in {"open", "in_progress"}
            and all(d in fulfilled for d in finding_prerequisites(f))
        ),
        key=lambda f: (
            -dependants[f["id"]],
            -SEVERITIES[f["severity"]],
            f["location"]["path"],
            f["id"],
        ),
    )


def coverage_summary(valid):
    confirmations = [
        passes["confirmation"] for passes in valid.values() if "confirmation" in passes
    ]
    return {
        "total": len(valid),
        "discovery": sum("discovery" in passes for passes in valid.values()),
        "confirmation": len(confirmations),
        "independence": dict(Counter(row["independence"] for row in confirmations)),
    }


def review_summary(state, valid, stale_inputs, *, summary):
    review = review_work(state, valid, stale_inputs=stale_inputs)
    outside = {
        (row["location"]["path"], row["location"].get("line", 0), row["evidence"]): row
        for passes in valid.values()
        for receipt in passes.values()
        for row in receipt.get("observations", [])
    }
    return {
        "coverage": coverage_summary(valid),
        "review_work": {
            key: len(value) if key in STAGES else value for key, value in review.items()
        }
        if summary
        else review,
        "out_of_scope_observation_count": len(outside),
        **(
            {"out_of_scope_observations": list(outside.values())} if not summary else {}
        ),
    }


def finding_summary(state):
    findings = state["findings"]
    counts = Counter(finding["status"] for finding in findings.values())
    report = {
        "strict_debt_points": sum(
            SEVERITIES[finding["severity"]]
            for finding in findings.values()
            if finding["status"] in DEBT
        ),
        "candidate_count": counts["candidate"],
        "actionable_count": sum(counts[status] for status in DEBT),
        "blocked_count": counts["blocked"],
        "accepted_risk_count": counts["accepted_risk"],
        "counts": dict(counts),
        "ready_findings": [finding["id"] for finding in ready_findings(findings)],
    }
    if state.get("fallout_base"):
        report["change_relations"] = dict(
            Counter(
                finding.get("change_relation", "unclassified")
                for finding in findings.values()
                if finding.get("triaged_at")
                and finding["status"] not in {"false_positive", "candidate"}
            )
        )
    return report


def completion_blockers(report, findings, guide_available):
    inventory = report["inventory_counts"]
    coverage = report["coverage"]
    total = coverage["total"]
    missing_replacements = any(
        finding["status"] == "superseded"
        and (
            not finding.get("replacements")
            or any(key not in findings for key in finding["replacements"])
        )
        for finding in findings.values()
    )
    blockers = (
        (report["stale_source"], "scan_required"),
        (not inventory.get("source"), "no_in_scope_source"),
        (inventory.get("incomplete"), "inventory_incomplete"),
        (report["capability_failures"], "capabilities_incomplete"),
        (not guide_available, "smell_guide_unavailable"),
        (
            report["actionable_count"] or report["candidate_count"],
            "unresolved_findings",
        ),
        (missing_replacements, "unreconciled_replacements"),
        (not total or coverage["discovery"] != total, "discovery_review_incomplete"),
        (
            not total or coverage["confirmation"] != total,
            "confirmation_review_incomplete",
        ),
        (report["verification_unmet"], "verification_incomplete"),
    )
    return [reason for blocked, reason in blockers if blocked]


def next_phase(report, state):
    if report["complete"]:
        return "complete"
    if report["stale_source"]:
        return "scan"
    if (
        state.get("manifest") is None
        or not state.get("baseline_snapshot")
        or any(
            reason.startswith("baseline ") for reason in report["verification_unmet"]
        )
    ):
        return "baseline"
    if report["stalled"]:
        return "intervention"
    if report["review_work"]["discovery"]:
        return "review_discovery"
    if report["candidate_count"]:
        return "triage"
    if report["counts"].get("pending_verification"):
        return "verify_resolution"
    if report["ready_findings"]:
        return "transform"
    if report["review_work"]["confirmation"]:
        return "review_confirmation"
    if (
        report["actionable_count"]
        or not report["coverage"]["total"]
        or any(
            reason in report["unmet"]
            for reason in (
                "capabilities_incomplete",
                "inventory_incomplete",
                "smell_guide_unavailable",
            )
        )
    ):
        return "partial_blocked"
    return "verify_completion"


def convergence_passes(report):
    coverage = report["coverage"]
    total = coverage["total"]
    if not total or report["stale_source"] or "unresolved_findings" in report["unmet"]:
        return 0
    return sum(coverage[stage] == total for stage in STAGES)


def evaluate(
    store,
    state,
    current,
    state_dir,
    current_source,
    guide_available,
    target,
    *,
    view=None,
    summary=False,
):
    inventory = current if current_source else state.get("inventory", {})
    entries = inventory.get("entries", {})
    stale_inputs = {}
    valid = matching_receipts(
        store, state, current["entries"], completion=True, stale_inputs=stale_inputs
    )
    verification_reasons, valid_checks = checks(state, state_dir)
    slice_result = (
        slice_status(
            state,
            entries,
            valid,
            view,
            verification_reasons,
            current_source and guide_available,
        )
        if view
        else None
    )
    changed = (
        []
        if current_source
        else changed_keys(
            {path: item.get("hash") for path, item in entries.items()},
            {path: item.get("hash") for path, item in current["entries"].items()},
        )
    )
    findings = finding_summary(state)
    report = {
        **findings,
        **review_summary(state, valid, stale_inputs, summary=summary),
        "target": target,
        "target_reached": target > 0
        and current_source
        and findings["strict_debt_points"] <= target,
        "inventory_counts": dict(
            Counter(item["disposition"] for item in entries.values())
        ),
        "capability_failures": state.get("scan", {}).get("gaps", []),
        **({"slice": slice_result} if view else {}),
        "verification_unmet": verification_reasons,
        "valid_verification_ids": valid_checks,
        "stale_source": not current_source,
        "changed_paths": changed,
        "idle_cycles": state["idle_cycles"],
        "other_scope_or_profile_debt": store.other_profiles(),
    }
    reasons = completion_blockers(report, state["findings"], guide_available)
    report.update(
        complete=not reasons,
        unmet=reasons,
        stalled=bool(reasons)
        and state["idle_cycles"] >= 3
        and state["progress"] == state["progress_at_checkpoint"],
    )
    return report | {
        "next_phase": next_phase(report, state),
        "convergence_passes": convergence_passes(report),
    }
