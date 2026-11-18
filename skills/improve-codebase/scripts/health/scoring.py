from collections import Counter

from .review import checks, matching_receipts, review_work
from .state import DEBT, SEVERITIES


def ready_findings(findings):
    dependants = Counter(
        dependency
        for finding in findings.values()
        if finding["status"] in DEBT
        for dependency in finding.get("dependencies", [])
    )

    def fulfilled(key, visited):
        if key in visited or key not in findings:
            return False
        finding = findings[key]
        if finding["status"] == "superseded":
            return bool(finding.get("replacements")) and all(
                fulfilled(other, visited | {key}) for other in finding["replacements"]
            )
        return finding["status"] == "resolved"

    return sorted(
        (
            f
            for f in findings.values()
            if f["status"] in {"open", "in_progress"}
            and all(fulfilled(d, set()) for d in f.get("dependencies", []))
        ),
        key=lambda f: (
            -dependants[f["id"]],
            -SEVERITIES[f["severity"]],
            f["location"]["path"],
            f["id"],
        ),
    )


def evaluate(store, state, current, state_dir, current_source, guide_available, target):
    findings = state["findings"]
    counts = Counter(f["status"] for f in findings.values())
    points = sum(
        SEVERITIES[f["severity"]] for f in findings.values() if f["status"] in DEBT
    )
    inventory = current if current_source else state.get("inventory", {})
    entries = inventory.get("entries", {})
    inv_counts = dict(Counter(item["disposition"] for item in entries.values()))
    valid = matching_receipts(store, state, current["entries"], completion=True)
    review = review_work(state, valid)
    discoveries = sum("discovery" in passes for passes in valid.values())
    confirmations = sum("confirmation" in passes for passes in valid.values())
    total = len(state.get("units", {}))
    gaps = state.get("scan", {}).get("gaps", [])
    reasons = []
    if not current_source:
        reasons.append("scan_required")
    if not inv_counts.get("source"):
        reasons.append("no_in_scope_source")
    if inv_counts.get("incomplete"):
        reasons.append("inventory_incomplete")
    if gaps:
        reasons.append("capabilities_incomplete")
    if not guide_available:
        reasons.append("smell_guide_unavailable")
    actionable = sum(counts[status] for status in DEBT)
    if actionable or counts["candidate"]:
        reasons.append("unresolved_findings")
    if any(
        f["status"] == "superseded"
        and (
            not f.get("replacements")
            or any(d not in findings for d in f["replacements"])
        )
        for f in findings.values()
    ):
        reasons.append("unreconciled_replacements")
    if not total or discoveries != total:
        reasons.append("discovery_review_incomplete")
    if not total or confirmations != total:
        reasons.append("confirmation_review_incomplete")
    verification_reasons, valid_checks = checks(state, state_dir)
    if verification_reasons:
        reasons.append("verification_incomplete")
    clean = not reasons
    stalled = (
        not clean
        and state["idle_cycles"] >= 3
        and state["progress"] == state["progress_at_checkpoint"]
    )
    ready = ready_findings(findings)
    if clean:
        phase = "complete"
    elif not current_source:
        phase = "scan"
    elif (
        state.get("manifest") is None
        or not state.get("baseline_snapshot")
        or any(reason.startswith("baseline ") for reason in verification_reasons)
    ):
        phase = "baseline"
    elif stalled:
        phase = "intervention"
    elif review["discovery"]:
        phase = "review_discovery"
    elif counts["candidate"]:
        phase = "triage"
    elif counts["pending_verification"]:
        phase = "verify_resolution"
    elif ready:
        phase = "transform"
    elif review["confirmation"]:
        phase = "review_confirmation"
    elif (
        gaps
        or inv_counts.get("incomplete")
        or actionable
        or not total
        or not guide_available
    ):
        phase = "partial_blocked"
    else:
        phase = "verify_completion"
    old = {path: item.get("hash") for path, item in entries.items()}
    new = {path: item.get("hash") for path, item in current["entries"].items()}
    changed = (
        sorted(
            path for path in old.keys() | new.keys() if old.get(path) != new.get(path)
        )
        if not current_source
        else []
    )
    profile_conflicts = store.other_profiles()
    independence = Counter(
        passes["confirmation"]["independence"]
        for passes in valid.values()
        if "confirmation" in passes
    )
    return {
        "complete": clean,
        "unmet": reasons,
        "next_phase": phase,
        "strict_debt_points": points,
        "target": target,
        "target_reached": target > 0 and current_source and points <= target,
        "candidate_count": counts["candidate"],
        "actionable_count": actionable,
        "blocked_count": counts["blocked"],
        "accepted_risk_count": counts["accepted_risk"],
        "counts": dict(counts),
        "inventory_counts": inv_counts,
        "capability_failures": gaps,
        "coverage": {
            "total": total,
            "discovery": discoveries,
            "confirmation": confirmations,
            "independence": dict(independence),
        },
        "review_work": review,
        "convergence_passes": (
            int(discoveries == total and not actionable and not counts["candidate"])
            + int(confirmations == total and not actionable and not counts["candidate"])
        )
        if current_source and total
        else 0,
        "verification_unmet": verification_reasons,
        "valid_verification_ids": valid_checks,
        "stale_source": not current_source,
        "changed_paths": changed,
        "stalled": stalled,
        "idle_cycles": state["idle_cycles"],
        "other_scope_or_profile_debt": profile_conflicts,
        "ready_findings": [f["id"] for f in ready],
    }
