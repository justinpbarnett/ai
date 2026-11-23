from pathlib import Path

from .review_units import STAGES, matching_receipts
from .runs import change_relation
from .state import (
    SEVERITIES,
    array,
    now,
    object_value,
    require,
    string,
    validate_dependencies,
    validate_prerequisite_cycle,
)
from .verification import checks

TRANSITIONS = {
    "candidate": {"open", "false_positive", "superseded"},
    "open": {
        "in_progress",
        "blocked",
        "accepted_risk",
        "pending_verification",
        "superseded",
    },
    "in_progress": {"open", "pending_verification", "blocked", "accepted_risk"},
    "blocked": {"open", "pending_verification", "accepted_risk", "superseded"},
    "accepted_risk": {"open", "blocked", "pending_verification", "superseded"},
    "pending_verification": {"resolved", "open", "blocked"},
    "resolved": {"open"},
    "false_positive": {"candidate"},
    "superseded": {"open"},
}


def confirmed_fields(obj):
    severity = string(obj, "severity")
    require(severity in SEVERITIES, "unknown severity")
    confidence = string(obj, "confidence")
    require(
        confidence in {"low", "medium", "high"},
        "confidence must be low, medium, or high",
    )
    contracts = array(obj, "contracts")
    require(
        contracts and all(isinstance(item, str) and item.strip() for item in contracts),
        "list concrete affected contracts",
    )
    return {
        "severity": severity,
        "confidence": confidence,
        "contracts": contracts,
        **{
            field: string(obj, field)
            for field in ("impact", "transformation", "verification", "evidence")
        },
    }


def replacement_findings(findings, key, document):
    replacements = array(document, "replacements")
    require(
        replacements
        and len(replacements) == len(set(map(str, replacements)))
        and all(
            isinstance(item, str) and item in findings and item != key
            for item in replacements
        ),
        "supply distinct valid replacement findings",
    )
    require(
        all(
            findings[item]["status"]
            in {
                "open",
                "in_progress",
                "pending_verification",
                "blocked",
                "accepted_risk",
                "resolved",
            }
            for item in replacements
        ),
        "replacements need confirmed or verified findings",
    )
    return replacements


def transition_fields(state, finding, document, status):
    after = dict(finding)
    confirming = status == "open" and finding["status"] in {"candidate", "superseded"}
    if confirming:
        after.update(confirmed_fields(document), triaged_at=now())
    if state.get("fallout_base") and (confirming or "change_relation" in document):
        after.update(change_relation(document))
    if status == "open" and "dependencies" in document:
        dependencies = array(document, "dependencies")
        validate_dependencies(state["findings"], finding["id"], dependencies)
        after["dependencies"] = dependencies
    if status in {"blocked", "false_positive"}:
        after["disposition_evidence"] = string(document, "evidence")
    if status == "accepted_risk":
        after["human_authorization"] = string(document, "human_authorization")
    if status == "superseded":
        after["replacements"] = replacement_findings(
            state["findings"], finding["id"], document
        )
    after["status"] = status
    validate_prerequisite_cycle(state["findings"], after)
    return after


def record_resolution(state, before, after, document, removal):
    after["resolution"] = {
        "snapshot": state["snapshot"],
        "evidence": string(document, "evidence"),
        "verification_ids": document["verification_ids"],
        "review_units": document["review_units"],
        "removal": removal,
    }
    completed_on = before.get("resolved_snapshots", [])
    if state["snapshot"] not in completed_on:
        after["resolved_snapshots"] = [*completed_on, state["snapshot"]]
        state["progress"] += 1


def record_transition(state, before, after, reason):
    event = {
        "from": before["status"],
        "to": after["status"],
        "reason": reason,
        "snapshot": state["snapshot"],
        "at": now(),
    }
    if before["status"] == "candidate":
        signature = before["signature"]
        event["signature"] = signature
        if not any(
            previous.get("from") == "candidate"
            and previous.get("signature") == signature
            for previous in before["history"]
        ):
            state["progress"] += 1
    after["history"] = [*before["history"], event]


def triage(store, state, document, state_dir, entries):
    key = string(document, "id")
    before = state["findings"].get(key)
    require(before is not None, "unknown finding ID")
    status, reason = string(document, "status"), string(document, "reason")
    require(
        status in TRANSITIONS[before["status"]],
        f"cannot transition {before['status']} to {status}",
    )
    after = transition_fields(state, before, document, status)
    if status == "pending_verification":
        after["pending_since"] = state["revision"] + 1
        after["pending_snapshot"] = state["snapshot"]
        after["change_evidence"] = string(document, "evidence")
    if status == "resolved":
        removal = verify_resolution(store, state, before, document, state_dir, entries)
        record_resolution(state, before, after, document, removal)
    record_transition(state, before, after, reason)
    state["findings"][key] = after
    return after


def authorized_removal(state, finding, document, entries, missing):
    request = object_value(document.get("removal"), "authorized removal evidence")
    require(
        finding["origin"] != "diagnostic",
        "the diagnostic tool must still account for its original source",
    )
    removed = array(request, "paths")
    surviving = array(request, "surviving_paths")
    require(
        removed
        and all(isinstance(p, str) for p in removed)
        and set(removed) == missing,
        "list exactly the affected paths deliberately deleted, not paths merely excluded",
    )
    root = Path(state["root"])
    require(
        not any(
            (root / path).exists()
            or (root / path).is_symlink()
            or path in state.get("moves", {})
            for path in removed
        ),
        "an existing or relocated path is not an authorized deletion",
    )
    require(
        surviving
        and all(
            isinstance(p, str) and entries.get(p, {}).get("disposition") == "source"
            for p in surviving
        ),
        "identify reviewed, surviving in-scope owners or callers",
    )
    return {
        "paths": removed,
        "surviving_paths": surviving,
        "evidence": string(request, "evidence"),
    }


def resolution_inputs(state, finding, document, entries):
    required_paths = set(finding["source_hashes"])
    missing = {
        path
        for path in required_paths
        if entries.get(path, {}).get("disposition")
        not in {"source", "context", "reference"}
    }
    removal = None
    if (
        entries.get(finding["location"]["path"], {}).get("disposition") != "source"
        or missing
    ):
        removal = authorized_removal(state, finding, document, entries, missing)
        required_paths = (required_paths - missing) | set(removal["surviving_paths"])
    require(
        any(
            entries.get(p, {}).get("hash") != stamp
            for p, stamp in finding["source_hashes"].items()
        ),
        "no relevant source inputs changed",
    )
    return required_paths, removal


def require_scanner_rerun(state, finding, entries, required_paths):
    require(
        finding.get("detector_profile") == state.get("observation_profile", {}),
        "detector profile changed; absence is not resolution evidence",
    )

    def affects_finding(path):
        return path in required_paths or finding["rule"] == "dependency-cycle"

    require(
        state["scan_revision"] >= finding["pending_since"]
        and not any(affects_finding(gap["path"]) for gap in state["scan"]["gaps"])
        and not any(
            entry["disposition"] == "incomplete" and affects_finding(path)
            for path, entry in entries.items()
        ),
        "a successful scan of the affected detector inputs after marking pending is required",
    )


def require_diagnostic_rerun(state, finding):
    result = state.get("diagnostic_runs", {}).get(finding["tool"], {})
    require(
        result.get("snapshot") == state["snapshot"]
        and result.get("revision", 0) >= finding["pending_since"]
        and finding["location"]["path"] in result.get("coverage", [])
        and result.get("profile") == finding.get("diagnostic_profile"),
        "rerun and import the same applicable diagnostic check after marking pending",
    )


def fresh_review_reads(state, finding, document, receipts):
    review_ids = array(document, "review_units")
    require(
        review_ids
        and all(isinstance(unit, str) and unit in receipts for unit in review_ids),
        "supply valid review units",
    )
    return {
        path
        for unit in review_ids
        for receipt in receipts[unit].values()
        if receipt["snapshot"] == state["snapshot"]
        and receipt["revision"] >= finding["pending_since"]
        and finding["id"] not in receipt["findings"]
        for path in receipt["reads"]
    }


def require_focused_evidence(state, finding, document, state_dir):
    _, valid = checks(state, state_dir)
    ids = array(document, "verification_ids")
    require(
        ids
        and all(
            isinstance(item, str)
            and item in valid
            and state["verification"][item]["result"] == "passed"
            and state["verification"][item]["kind"] in {"check", "flow"}
            and state["verification"][item]["revision"] >= finding["pending_since"]
            for item in ids
        ),
        "need current passing focused check or flow evidence after marking pending",
    )


def verify_resolution(store, state, finding, document, state_dir, entries):
    require(
        finding["last_seen_snapshot"] != state["snapshot"],
        "finding is still present on the current snapshot",
    )
    required_paths, removal = resolution_inputs(state, finding, document, entries)
    if finding["origin"] == "scanner":
        require_scanner_rerun(state, finding, entries, required_paths)
    if finding["origin"] == "diagnostic":
        require_diagnostic_rerun(state, finding)
    receipts = matching_receipts(store, state, entries)
    reviewed = fresh_review_reads(state, finding, document, receipts)
    require(
        required_paths <= reviewed,
        "need fresh review of the source and related locations after marking pending",
    )
    require_focused_evidence(state, finding, document, state_dir)
    require(
        not any(
            finding["id"] in receipts[unit].get(stage, {}).get("findings", [])
            for unit in receipts
            for stage in STAGES
        ),
        "a current review still reports this finding",
    )
    return removal
