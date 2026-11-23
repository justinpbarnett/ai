from collections import defaultdict
from datetime import UTC, datetime

from .hashing import digest
from .validation import require

DEBT = {"open", "in_progress", "pending_verification", "blocked", "accepted_risk"}
UNRESOLVED = DEBT | {"candidate"}
SEVERITIES = {"critical": 16, "high": 8, "medium": 3, "low": 1}


def strict_debt_points(findings):
    return sum(
        SEVERITIES[finding["severity"]]
        for finding in findings.values()
        if finding["status"] in DEBT
    )


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def finding_id(finding):
    return digest(
        [
            finding["origin"],
            finding["rule"],
            finding["location"]["path"],
            finding["anchor"],
            finding.get("identity", ""),
        ]
    )[:24]


def evidence_paths(finding):
    return sorted(
        {finding["location"]["path"], *(loc["path"] for loc in finding["related"])}
    )


def moved_finding(findings, finding, moves):
    if not moves:
        return None
    destinations = finding["source_hashes"]
    matches = [
        item
        for item in findings.values()
        if moves.get(item["location"]["path"]) in destinations
        and item["origin"] == finding["origin"]
        and item["rule"] == finding["rule"]
        and item["anchor"] == finding["anchor"]
        and item.get("identity", "") == finding.get("identity", "")
        and item["signature"] == finding["signature"]
    ]
    return matches[0] if len(matches) == 1 else None


def same_folder_finding(findings, finding):
    if not finding["anchor"].startswith("directory:"):
        return None
    matches = [
        item
        for item in findings.values()
        if item["origin"] == finding["origin"]
        and item["rule"] == finding["rule"]
        and item["anchor"] == finding["anchor"]
        and item.get("identity", "") == finding.get("identity", "")
    ]
    return matches[0] if len(matches) == 1 else None


def recorded_severity_applies(prior, finding):
    return bool(prior and prior.get("triaged_at") and "severity" in finding)


def resolve_identity(state, finding):
    findings = state["findings"]
    location_key = finding_id(finding)
    location_keys = state.setdefault("finding_keys", {})
    identifier = location_keys.get(location_key, location_key)
    prior = findings.get(identifier)
    if prior is None:
        prior = moved_finding(
            findings, finding, state.get("moves")
        ) or same_folder_finding(findings, finding)
        if prior is not None:
            identifier = prior["id"]
    location_keys[location_key] = identifier
    return identifier, prior


def recurrence_status(prior, finding):
    if prior is None:
        return "candidate"
    status = prior["status"]
    if status == "resolved":
        return "open"
    if status == "false_positive" and prior["signature"] != finding["signature"]:
        return "candidate"
    return status


def merged_aliases(previous, prior, finding):
    aliases = previous["aliases"]
    if prior and prior["location"]["path"] != finding["location"]["path"]:
        aliases = sorted(set(aliases) | {prior["location"]["path"]})
    return aliases


def extended_history(previous, prior, status, snapshot):
    history = previous["history"]
    if prior and status != prior["status"]:
        history = [
            *history,
            {
                "from": prior["status"],
                "to": status,
                "reason": "evidence changed or problem recurred",
                "snapshot": snapshot,
                "at": now(),
            },
        ]
    return history


def counts_as_progress(state, prior, finding):
    return prior is None and (
        finding["origin"] != "scanner" or not state.get("scan_repeated_snapshot")
    )


def observe(state, finding, *, entries=None):
    findings = state["findings"]
    if entries is None:
        entries = state["inventory"]["entries"]
    finding["source_hashes"] = {
        path: entries[path]["hash"] for path in evidence_paths(finding)
    }
    identifier, prior = resolve_identity(state, finding)
    if recorded_severity_applies(prior, finding):
        finding["severity"] = prior["severity"]
    status = recurrence_status(prior, finding)
    revision = state["revision"] + 1
    previous = prior or {
        "first_seen_snapshot": state["snapshot"],
        "first_seen_revision": revision,
        "aliases": [],
        "history": [],
    }
    findings[identifier] = (
        previous
        | finding
        | {
            "id": identifier,
            "status": status,
            "aliases": merged_aliases(previous, prior, finding),
            "history": extended_history(previous, prior, status, state["snapshot"]),
            "last_seen_snapshot": state["snapshot"],
            "last_seen_revision": revision,
        }
    )
    if counts_as_progress(state, prior, finding):
        state["progress"] += 1
    return identifier


def detect_moves(previous, current):
    old, new = defaultdict(list), defaultdict(list)
    for left, right, index in ((previous, current, old), (current, previous, new)):
        for path, entry in left.items():
            if entry.get("hash") and not right.get(path, {}).get("hash"):
                index[entry["hash"]].append(path)
    return {
        paths[0]: new[key][0]
        for key, paths in old.items()
        if len(paths) == 1 and len(new[key]) == 1
    }


def finding_prerequisites(finding):
    field = "replacements" if finding["status"] == "superseded" else "dependencies"
    return finding.get(field, [])


def validate_dependencies(findings, identifier, dependencies):
    require(
        all(
            isinstance(d, str) and d in findings and d != identifier
            for d in dependencies
        ),
        "unknown or self-referencing finding dependency",
    )
    require(len(dependencies) == len(set(dependencies)), "duplicate dependency")


def validate_prerequisite_cycle(findings, proposed):
    pending, visited = list(finding_prerequisites(proposed)), set()
    while pending:
        other = pending.pop()
        require(other != proposed["id"], "finding dependency or replacement cycle")
        if other not in visited:
            visited.add(other)
            pending.extend(finding_prerequisites(findings[other]))
