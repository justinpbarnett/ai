import uuid
from collections import defaultdict
from pathlib import Path

from .detectors import project_context
from .inventory import content_hash, digest, is_project_guide, read_source, safe_file
from .runs import WIRING_LANGUAGES, change_relation, in_paths
from .state import (
    SEVERITIES,
    array,
    now,
    object_value,
    observe,
    packed,
    require,
    string,
    unpacked,
)

AXES = ("smells", "architecture", "contracts")
STAGES = ("discovery", "confirmation")
VERIFICATION_KINDS = {"baseline", "check", "flow", "final_diff"}
SATISFACTORY_RESULTS = {"passed", "not_applicable"}
REVIEW_VERSION = 3
VERIFICATION_VERSION = 1


def units_for(inv, scan, rubric):
    entries = inv["entries"]
    source = {p for p, e in entries.items() if e["disposition"] == "source"}
    adjacent = defaultdict(set)
    relationships = defaultdict(set)
    project_neighbors = defaultdict(set)
    for left, right, kind in scan["edges"]:
        adjacent[left].add(right)
        adjacent[right].add(left)
        relationships[left].add((left, right, kind))
        relationships[right].add((left, right, kind))
        projects = entries[left]["project"], entries[right]["project"]
        if projects[0] != projects[1]:
            project_neighbors[projects[0]].add(projects[1])
            project_neighbors[projects[1]].add(projects[0])
    units, partition_inputs, uncertain_files = {}, {}, defaultdict(set)
    guides, rules_by_directory = defaultdict(set), defaultdict(set)
    for path, entry in entries.items():
        if entry["disposition"] == "reference" and is_project_guide(path):
            guides[Path(path).parent].add(path)
    for path in inv["rules"]:
        rules_by_directory[Path(path).parent].add(path)

    def partition_paths(project):
        if project not in partition_inputs:
            linked, pending = set(), [project]
            while pending:
                name = pending.pop()
                if name not in linked:
                    linked.add(name)
                    pending.extend(project_neighbors[name] - linked)
            inputs = set().union(*(project_context(name, entries) for name in linked))
            partition_inputs.update(dict.fromkeys(linked, inputs))
        return partition_inputs[project]

    def register(axis, files, related, *, wiring=None):
        files = sorted(files)
        context_paths = set(files) | set(related)
        directories = {
            parent for path in context_paths for parent in Path(path).parents
        }
        documentation = {
            guide for directory in directories for guide in guides.get(directory, ())
        }
        rules = {
            path: inv["rules"][path]
            for directory in directories
            for path in rules_by_directory.get(directory, ())
        }
        governing = digest([rubric, rules])
        context = {p: entries[p]["hash"] for p in sorted(context_paths | documentation)}
        identifier = digest(
            [axis, files] if wiring is None else [axis, "wiring", wiring]
        )[:24]
        edges = sorted({edge for path in files for edge in relationships[path]})
        limits = {
            path: scan["limitations"][path]
            for path in context_paths
            if path in scan["limitations"]
        }
        inputs = digest([identifier, context, governing, wiring, edges, limits])
        units[identifier] = {
            "id": identifier,
            "axis": axis,
            "files": files,
            "inputs": inputs,
            "context": context,
            "relationships": edges,
            "project_partitions": sorted({entries[path]["project"] for path in files}),
            "wiring_partition": wiring,
            "governing": governing,
            "rule_hashes": rules,
            "rubric": rubric,
            "limitations": limits,
        }

    for path in sorted(source):
        entry = entries[path]
        if entry["language"] in WIRING_LANGUAGES or scan["limitations"].get(path):
            uncertain_files[entry["project"]].add(path)
        for axis in AXES:
            register(axis, [path], adjacent[path])
    for left, right, kind in scan["edges"]:
        if left != right and (left in source or right in source):
            if kind == "project":
                for path in {left, right} & source:
                    uncertain_files[entries[path]["project"]].add(path)
            for axis in ("architecture", "contracts"):
                register(axis, [left, right], adjacent[left] | adjacent[right])
    for project, files in sorted(uncertain_files.items()):
        for axis in ("architecture", "contracts"):
            register(axis, files, partition_paths(project), wiring=project)
    return units


def matching_receipts(store, state, entries, *, completion=False, stale_inputs=None):
    units = state.get("units", {})
    receipts = store.receipts({unit["inputs"] for unit in units.values()})
    valid = {}
    for unit_id, unit in units.items():
        passes = {}
        for stage in STAGES:
            saved = receipts[unit["inputs"]].get(stage)
            if saved is not None and (
                saved.get("profile") == store.key or not saved["findings"]
            ):
                changed = sorted(
                    path
                    for path, stamp in saved["reads"].items()
                    if entries.get(path, {}).get("hash") != stamp
                )
                if changed:
                    if stale_inputs is not None:
                        stale_inputs.setdefault(unit_id, {})[stage] = changed
                    continue
                if completion and stage == "confirmation" and saved["found_new_work"]:
                    continue
                if stage == "confirmation" and (
                    "discovery" not in passes
                    or passes["discovery"]["packet_id"] != saved["discovery_packet"]
                ):
                    continue
                passes[stage] = saved
        valid[unit_id] = passes
    return valid


def changed_keys(old, new):
    return sorted(
        key for key in old.keys() | new.keys() if old.get(key) != new.get(key)
    )


def unit_changes(old, new):
    changes = {}
    if old.get("context") is not None:
        paths = changed_keys(old["context"], new["context"])
        if paths:
            changes["context_paths"] = paths
    if old.get("relationships") != new.get("relationships"):
        before = {tuple(edge) for edge in old.get("relationships", [])}
        after = {tuple(edge) for edge in new.get("relationships", [])}
        changes["relationships"] = {
            "added": sorted(after - before),
            "removed": sorted(before - after),
        }
    rules = changed_keys(old.get("rule_hashes", {}), new.get("rule_hashes", {}))
    if rules:
        changes["governing_paths"] = rules
    if old.get("rubric") != new.get("rubric"):
        changes["review_rubric_changed"] = True
    limits = changed_keys(old.get("limitations", {}), new.get("limitations", {}))
    if limits:
        changes["limitation_paths"] = limits
    if old.get("wiring_partition") != new.get("wiring_partition") or old.get(
        "partition_fingerprint"
    ):
        changes["wiring_coverage_changed"] = True
    return changes


def unit_matches_paths(unit, paths):
    return any(in_paths(path, paths) for path in unit["files"])


def review_work(state, receipts, *, stale_inputs=None):
    old_units = state.get("previous_units", {})
    result = {stage: [] for stage in STAGES}
    result.update({"reused": 0, "new": 0, "changed": 0, "invalidated": 0, "pending": 0})
    for identifier, unit in state.get("units", {}).items():
        valid = receipts[identifier]
        if len(valid) == len(STAGES):
            result["reused"] += 1
            continue
        stage = "confirmation" if valid else "discovery"
        if valid:
            reason = "distinct confirmation pending"
            result["pending"] += 1
        elif identifier not in old_units:
            reason = "new or never-investigated unit"
            result["new"] += 1
        elif old_units[identifier].get(
            "file_hashes", old_units[identifier].get("files")
        ) != [unit["context"][p] for p in unit["files"]]:
            reason = "source content changed"
            result["changed"] += 1
        elif old_units[identifier]["inputs"] != unit["inputs"]:
            reason = "related inputs, rules, or review profile changed"
            result["invalidated"] += 1
        else:
            reason = "review unfinished or declared supporting evidence changed"
            result["pending"] += 1
        details = {}
        prior = old_units.get(identifier)
        if prior and prior["inputs"] != unit["inputs"]:
            details = unit_changes(prior, unit)
        if stale_inputs and stale_inputs.get(identifier):
            details["declared_reads_changed"] = stale_inputs[identifier]
        result[stage].append(
            {
                "id": identifier,
                "axis": unit["axis"],
                "files": unit["files"],
                "wiring_partition": unit.get("wiring_partition"),
                "reason": reason,
                **({"changed_inputs": details} if details else {}),
            }
        )
    return result


def prepare(
    store,
    state,
    entries,
    *,
    root,
    axis,
    stage,
    limit,
    full,
    exclude,
    partition,
    include,
    paths,
    slice_paths,
    template,
):
    require(state.get("snapshot"), "scan before preparing reviews")
    work = review_work(state, matching_receipts(store, state, entries, completion=True))
    valid = matching_receipts(store, state, entries)
    units = state["units"]
    require(
        all(identifier in units for identifier in [*include, *exclude]),
        "requested unit does not exist on this scan",
    )
    require(
        not set(include) & set(exclude), "unit cannot be both requested and excluded"
    )
    require(len(set(include)) <= limit, "requested unit count exceeds the packet limit")

    def selected(unit):
        return (
            unit["id"] not in exclude
            and (not include or unit["id"] in include)
            and (not paths or unit_matches_paths(unit, paths))
            and (not slice_paths or unit_matches_paths(unit, slice_paths))
            and (not axis or unit["axis"] == axis)
            and (
                not partition
                or any(
                    state["inventory"]["entries"][path]["project"] == partition
                    for path in unit["files"]
                )
            )
        )

    stage = stage or next(
        (
            phase
            for phase in STAGES
            if any(selected(units[x["id"]]) for x in work[phase])
        ),
        "discovery",
    )
    if full:
        ids = [
            key
            for key, unit in units.items()
            if selected(unit) and (stage == "discovery" or "discovery" in valid[key])
        ]
    else:
        ids = [item["id"] for item in work[stage] if selected(units[item["id"]])]
    if include:
        require(
            set(ids) == set(include) and len({units[key]["axis"] for key in ids}) == 1,
            "requested units must be eligible for the same pass and axis; use --full to revisit covered units",
        )
    if not ids:
        return {"packet": None, "remaining": 0, "pass": stage}
    axis = axis or units[ids[0]]["axis"]
    ids = sorted(
        (key for key in ids if units[key]["axis"] == axis),
        key=lambda key: (
            units[key].get("wiring_partition") is not None,
            units[key]["files"],
        ),
    )
    packet_id = uuid.uuid4().hex
    assigned = [units[key] for key in ids[:limit]]
    rules = sorted(
        {
            path
            for unit in assigned
            for path in unit.get("rule_hashes", state["inventory"]["rules"])
        }
    )
    packet = {
        "id": packet_id,
        "sweep_id": digest([state["snapshot"], stage]),
        "snapshot": state["snapshot"],
        "root": str(root),
        "axis": axis,
        "pass": stage,
        "units": assigned,
        "fallout_base": state.get("fallout_base"),
        "governing_paths": rules,
        "created_at": now(),
    }
    stored = packet | {
        "prior_receipts": {
            key: valid[key].get(stage, {}).get("packet_id") for key in ids[:limit]
        },
        "discovery_packets": {
            key: valid[key]["discovery"]["packet_id"]
            for key in ids[:limit]
            if stage == "confirmation"
        },
    }
    store.connection.execute(
        "INSERT INTO packets VALUES (?, ?, 0, ?)",
        (packet_id, store.key, packed(stored)),
    )
    result = {"packet": packet, "remaining": len(ids) - len(packet["units"])}
    if template:
        result["receipt_template"] = {
            "packet_id": packet_id,
            "snapshot": packet["snapshot"],
            "sweep_id": packet["sweep_id"],
            "axis": axis,
            "reviewer": "",
            "independence": "sequential",
            "units": [
                {
                    "id": unit["id"],
                    "inputs": unit["inputs"],
                    "reads": unit["context"],
                    "evidence": "",
                    "findings": [],
                }
                for unit in packet["units"]
            ],
        }
    return result


def location(document, entries):
    obj = object_value(document, "location")
    path = string(obj, "path")
    require(
        entries.get(path, {}).get("disposition") in {"source", "context", "reference"},
        f"location is not inventoried code or documentation: {path!r}",
    )
    coords = {
        key: obj[key]
        for key in ("line", "column", "end_line", "end_column")
        if key in obj
    }
    require(
        all(type(value) is int and value > 0 for value in coords.values()),
        "invalid source coordinate",
    )
    require(
        coords.get("end_line", coords.get("line", 0)) >= coords.get("line", 0),
        "reversed source range",
    )
    return {"path": path, **coords}


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


def semantic_finding(doc, entries, unit, reads, *, fallout=False):
    obj = object_value(doc, "semantic finding")
    primary = location(obj.get("location"), entries)
    require(
        primary["path"] in reads
        and entries[primary["path"]]["disposition"] == "source",
        "finding must point to reviewed, in-scope source",
    )
    related = [location(item, entries) for item in obj.get("related", [])]
    require(
        all(loc["path"] in reads for loc in related),
        "related location must be in reviewed inputs",
    )
    require(
        primary["path"] in unit["files"]
        or any(loc["path"] in unit["files"] for loc in related),
        "finding must connect to the assigned unit",
    )
    rule, anchor = string(obj, "rule"), string(obj, "anchor")
    fields = confirmed_fields(obj)
    return {
        "origin": "semantic",
        "rule": rule,
        "anchor": anchor,
        "location": primary,
        "related": related,
        "signature": digest([rule, anchor, fields["evidence"], fields["impact"]]),
        "observation": {"axis": unit["axis"]},
        "review_unit": unit["id"],
        **fields,
        **(change_relation(obj) if fallout else {}),
    }


def outside_observations(item, entries, reads):
    return (
        [
            outside_observation(value, entries, reads)
            for value in array(item, "observations")
        ]
        if "observations" in item
        else []
    )


def outside_observation(value, entries, reads):
    obj = object_value(value, "out-of-scope observation")
    loc = location(obj.get("location"), entries)
    path = loc["path"]
    require(
        path in reads and entries[path]["disposition"] == "context",
        "observation must cite reviewed source outside the run scope",
    )
    return {"location": loc, "evidence": string(obj, "evidence")}


def import_review(store, state, document, entries):
    packet_id = string(document, "packet_id")
    row = store.connection.execute(
        "SELECT payload, consumed FROM packets WHERE id = ? AND scope = ?",
        (packet_id, store.key),
    ).fetchone()
    require(row is not None and not row[1], "unknown or already imported review packet")
    packet = unpacked(row[0])
    require(
        packet["snapshot"] == document.get("snapshot"),
        "receipt snapshot does not match its packet",
    )
    require(
        packet["axis"] == document.get("axis")
        and packet["sweep_id"] == document.get("sweep_id"),
        "review axis or sweep ID does not match packet",
    )
    reviewer = string(document, "reviewer")
    independence = string(document, "independence")
    require(
        independence in {"independent", "sequential"},
        "independence must be independent or sequential",
    )
    incoming = {}
    for value in array(document, "units"):
        item = object_value(value, "review unit")
        identifier = string(item, "id")
        require(identifier not in incoming, "duplicate review unit")
        incoming[identifier] = item
    expected = {unit["id"]: unit for unit in packet["units"]}
    require(
        expected and incoming.keys() == expected.keys(),
        "receipt must account for every assigned unit exactly once",
    )
    valid = matching_receipts(store, state, entries)
    stage = packet["pass"]
    rebased = packet["snapshot"] != state["snapshot"]
    require(
        not rebased or "prior_receipts" in packet,
        "legacy packet is stale; prepare a fresh packet",
    )
    receipts, observed = [], []
    for identifier, item in incoming.items():
        unit = expected[identifier]
        current = state["units"].get(identifier)
        require(current is not None, f"review unit no longer exists: {identifier}")
        if current["inputs"] != unit["inputs"]:
            raise ValueError(
                f"review unit inputs changed: {identifier}; {unit_changes(unit, current)}"
            )
        require(
            item.get("inputs") == unit["inputs"],
            "unit input fingerprint does not match packet",
        )
        current_stage = valid[identifier].get(stage, {})
        prior = packet.get("prior_receipts")
        require(
            prior is None or current_stage.get("packet_id") == prior.get(identifier),
            f"a newer {stage} receipt exists for unit {identifier}; prepare a fresh packet",
        )
        reads = object_value(item.get("reads"), "reads")
        stale_reads = sorted(
            path
            for path, stamp in reads.items()
            if not isinstance(stamp, str) or entries.get(path, {}).get("hash") != stamp
        )
        require(
            reads and not stale_reads,
            f"review input paths or hashes are stale or invalid: {stale_reads!r}",
        )
        require(
            all(reads.get(path) == hashed for path, hashed in unit["context"].items()),
            "receipt omits files or relationships from the packet",
        )
        evidence = string(item, "evidence")
        findings = [
            semantic_finding(
                value, entries, unit, reads, fallout=bool(state.get("fallout_base"))
            )
            for value in array(item, "findings")
        ]
        discovery_packet = packet["discovery_packets"].get(identifier)
        discovery = valid[identifier].get("discovery", {})
        if stage == "confirmation":
            require(
                discovery_packet and discovery.get("packet_id") == discovery_packet,
                "discovery receipt changed; prepare confirmation again",
            )
            require(
                independence == "sequential" or discovery["reviewer"] != reviewer,
                "independent confirmation needs a different reviewer",
            )
        previously_known = valid[identifier].get(stage)
        # A new result at the same input replaces the current receipt, never invents an extra pass.
        identifiers = []
        changed = False
        for finding in findings:
            found = observe(state, finding, entries=entries)
            recorded = state["findings"][found]
            if recorded["status"] == "candidate" and not recorded.get("triaged_at"):
                recorded.update(status="open", triaged_at=now())
            identifiers.append(found)
            changed |= found not in (previously_known or {}).get(
                "findings", []
            ) and recorded["status"] not in {"false_positive", "superseded"}
        observed.extend(identifiers)
        receipt = {
            "profile": store.key,
            "packet_id": packet_id,
            "discovery_packet": discovery_packet,
            "sweep_id": packet["sweep_id"],
            "axis": packet["axis"],
            "snapshot": state["snapshot"],
            "reviewer": reviewer,
            "independence": independence,
            "reads": reads,
            "evidence": evidence,
            "findings": identifiers,
            "observations": outside_observations(item, entries, reads),
            "packet_snapshot": packet["snapshot"],
            "found_new_work": changed,
            "at": now(),
            "revision": state["revision"] + 1,
        }
        if stage == "confirmation" and discovery.get("profile") != store.key:
            receipts.append((unit["inputs"], "discovery", store.key, packed(discovery)))
        receipts.append((unit["inputs"], stage, store.key, packed(receipt)))
        if not previously_known:
            state["progress"] += 1
    store.connection.executemany(
        "INSERT OR REPLACE INTO receipts VALUES (?, ?, ?, ?)", receipts
    )
    store.connection.execute(
        "UPDATE packets SET consumed = 1 WHERE id = ?", (packet_id,)
    )
    store.save(
        state,
        "review",
        {
            "packet": packet,
            "receipts": [unpacked(r[3]) for r in receipts],
            "findings": observed,
        },
    )
    return {"accepted_units": len(incoming), "findings": observed, "rebased": rebased}


def record_manifest(state, document):
    requirements = {}
    for value in array(document, "requirements"):
        item = object_value(value, "verification requirement")
        identifier, kind = string(item, "id"), string(item, "kind")
        require(
            kind in VERIFICATION_KINDS and identifier not in requirements,
            "unknown or duplicate verification requirement",
        )
        requirements[identifier] = {
            "kind": kind,
            "description": string(item, "description"),
            "discovered_from": string(item, "discovered_from"),
        }
    require(
        VERIFICATION_KINDS == {item["kind"] for item in requirements.values()},
        "manifest must account for baseline, checks, real flows, and final diff",
    )
    if state["manifest"] is not None:
        require(string(document, "reason"), "manifest change requires a reason")
        require(
            state["manifest"]["requirements"].keys() <= requirements.keys(),
            "cannot remove verification requirements; record a justified not-applicable disposition",
        )
        require(
            all(
                requirements[k]["kind"] == item["kind"]
                for k, item in state["manifest"]["requirements"].items()
            ),
            "cannot change a requirement's kind",
        )
    state["manifest"] = {
        "requirements": requirements,
        "rules": digest(state["inventory"]["rules"]),
        "reason": document.get("reason"),
    }


def preserve_baseline(state, record):
    if record["result"] in SATISFACTORY_RESULTS:
        originals = state.setdefault("original_baseline", {})
        identifier = record["id"]
        if originals.get(identifier, {}).get("result") not in SATISFACTORY_RESULTS:
            originals[identifier] = record


def restore_legacy_baseline(state):
    for record in state["verification"].values():
        if (
            record["kind"] == "baseline"
            and record["snapshot"] == state["baseline_snapshot"]
        ):
            preserve_baseline(state, record)


def record_verification(state, document, root, state_dir):
    require(
        document.get("snapshot") == state.get("snapshot") and state.get("snapshot"),
        "verification snapshot is stale or absent",
    )
    if document.get("kind") == "manifest":
        record_manifest(state, document)
        return {"kind": "manifest", **state["manifest"]}
    identifier = string(document, "id")
    require(
        state["manifest"] is not None
        and identifier in state["manifest"]["requirements"],
        "declare the verification requirement first",
    )
    kind = string(document, "kind")
    require(
        kind == state["manifest"]["requirements"][identifier]["kind"],
        "verification kind does not match manifest",
    )
    result = string(document, "result")
    require(
        result in {"passed", "failed", "unavailable", "not_applicable"},
        "unknown verification result",
    )
    if result == "not_applicable":
        require(
            kind != "final_diff",
            "final diff review must be recorded even when unchanged",
        )
        string(document, "reason")
    cwd = Path(string(document, "cwd"))
    require(
        cwd.is_absolute()
        and cwd.resolve() == cwd
        and cwd.is_relative_to(root)
        and cwd.is_dir(),
        "verification cwd must be inside the worktree",
    )
    command, expected, observed = (
        string(document, key) for key in ("interaction", "expected", "observed")
    )
    if "exit_status" in document:
        require(type(document["exit_status"]) is int, "exit_status must be an integer")
    baseline_snapshot = state.get("baseline_snapshot")
    if kind == "baseline" and result in SATISFACTORY_RESULTS and not baseline_snapshot:
        baseline_snapshot = state["snapshot"]
        state["baseline_snapshot"] = baseline_snapshot
        state["baseline_inputs"] = state["scope_inputs"]
    if kind != "baseline":
        require(
            baseline_snapshot
            and document.get("baseline_snapshot") == baseline_snapshot,
            "include the recorded baseline snapshot",
        )
    artifacts = []
    for value in document.get("artifacts", []):
        item = object_value(value, "artifact")
        path = string(item, "path")
        hashed = content_hash(read_source(safe_file(state_dir, path)))
        require(hashed == string(item, "sha256"), "artifact hash does not match")
        artifacts.append({"path": path, "sha256": hashed})
    record = {
        "id": identifier,
        "kind": kind,
        "result": result,
        "snapshot": state["snapshot"],
        "baseline_snapshot": baseline_snapshot,
        "cwd": str(cwd),
        "interaction": command,
        "expected": expected,
        "observed": observed,
        "reason": document.get("reason"),
        "exit_status": document.get("exit_status"),
        "artifacts": artifacts,
        "requirements_hash": digest(state["manifest"]["requirements"][identifier]),
        "verification_version": VERIFICATION_VERSION,
        "at": now(),
        "revision": state["revision"] + 1,
    }
    if kind == "baseline" and (
        baseline_snapshot == state["snapshot"]
        or state.get("baseline_inputs") == state["scope_inputs"]
    ):
        preserve_baseline(state, record)
    state["verification"][identifier] = record
    return record


def checks(state, state_dir):
    manifest = state.get("manifest")
    if not manifest:
        return ["declare check and flow manifest"], []
    reasons, valid = [], []
    if manifest["rules"] != digest(state["inventory"]["rules"]):
        reasons.append(
            "verification manifest must be reviewed against changed governing files"
        )
    for key, item in manifest["requirements"].items():
        if item["kind"] == "baseline":
            record = state.get("original_baseline", {}).get(key, {})
            current = record.get("baseline_snapshot") == state.get("baseline_snapshot")
        else:
            record = state["verification"].get(key, {})
            current = (
                record.get("snapshot") == state["snapshot"]
                and record.get("verification_version") == VERIFICATION_VERSION
            )
        if (
            not current
            or record.get("result") not in SATISFACTORY_RESULTS
            or record.get("requirements_hash") != digest(item)
        ):
            reasons.append(
                f"{item['kind']} {key}: missing, stale, failed, or unavailable evidence"
            )
            continue
        try:
            require(
                all(
                    content_hash(read_source(safe_file(state_dir, a["path"])))
                    == a["sha256"]
                    for a in record["artifacts"]
                ),
                "artifact changed",
            )
        except (OSError, ValueError, RuntimeError):
            reasons.append(
                f"{item['kind']} {key}: evidence artifact missing or changed"
            )
            continue
        valid.append(key)
    return reasons, valid


def triage(store, state, document, state_dir, entries):
    key = string(document, "id")
    before = state["findings"].get(key)
    require(before is not None, "unknown finding ID")
    status, reason = string(document, "status"), string(document, "reason")
    allowed = {
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
    require(
        status in allowed[before["status"]],
        f"cannot transition {before['status']} to {status}",
    )
    after = dict(before)
    if status == "open" and before["status"] in {"candidate", "superseded"}:
        after.update(confirmed_fields(document), triaged_at=now())
        if state.get("fallout_base"):
            after.update(change_relation(document))
    elif state.get("fallout_base") and "change_relation" in document:
        after.update(change_relation(document))
    if status == "open" and "dependencies" in document:
        from .state import validate_dependencies

        dependencies = array(document, "dependencies")
        validate_dependencies(state["findings"], key, dependencies)
        after["dependencies"] = dependencies
    if status in {"blocked", "false_positive"}:
        after["disposition_evidence"] = string(document, "evidence")
    if status == "accepted_risk":
        after["human_authorization"] = string(document, "human_authorization")
    if status == "superseded":
        replacements = array(document, "replacements")
        require(
            replacements
            and len(replacements) == len(set(map(str, replacements)))
            and all(
                isinstance(item, str) and item in state["findings"] and item != key
                for item in replacements
            ),
            "supply distinct valid replacement findings",
        )
        require(
            all(
                state["findings"][item]["status"]
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
        require(
            all(
                key not in replacement_chain(state["findings"], item)
                for item in replacements
            ),
            "replacement cycle",
        )
        after["replacements"] = replacements
    if status == "pending_verification":
        after["pending_since"] = state["revision"] + 1
        after["pending_snapshot"] = state["snapshot"]
        after["change_evidence"] = string(document, "evidence")
    if status == "resolved":
        removal = verify_resolution(store, state, before, document, state_dir, entries)
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
    after["status"] = status
    after["history"] = [
        *before["history"],
        {
            "from": before["status"],
            "to": status,
            "reason": reason,
            "snapshot": state["snapshot"],
            "at": now(),
        },
    ]
    state["findings"][key] = after
    return after


def replacement_chain(findings, key):
    visited, stack = set(), [key]
    while stack:
        item = stack.pop()
        if item not in visited:
            visited.add(item)
            if findings[item]["status"] == "superseded":
                stack.extend(findings[item].get("replacements", []))
    return visited


def verify_resolution(store, state, finding, doc, state_dir, entries):
    require(
        finding["last_seen_snapshot"] != state["snapshot"],
        "finding is still present on the current snapshot",
    )
    pending = finding["pending_since"]
    primary = finding["location"]["path"]
    required_paths = set(finding["source_hashes"])
    missing = {
        p
        for p in required_paths
        if entries.get(p, {}).get("disposition")
        not in {"source", "context", "reference"}
    }
    removal = None
    if entries.get(primary, {}).get("disposition") != "source" or missing:
        request = object_value(doc.get("removal"), "authorized removal evidence")
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
        required_paths = (required_paths - missing) | set(surviving)
        removal = {
            "paths": removed,
            "surviving_paths": surviving,
            "evidence": string(request, "evidence"),
        }
    require(
        any(
            entries.get(p, {}).get("hash") != stamp
            for p, stamp in finding["source_hashes"].items()
        ),
        "no relevant source inputs changed",
    )
    if finding["origin"] == "scanner":
        profile = state.get("observation_profile", {})
        require(
            finding.get("detector_profile") == profile,
            "detector profile changed; absence is not resolution evidence",
        )
        require(
            state["scan_revision"] >= pending
            and not any(
                gap["path"] in required_paths or finding["rule"] == "dependency-cycle"
                for gap in state["scan"]["gaps"]
            )
            and not any(
                entry["disposition"] == "incomplete"
                and (path in required_paths or finding["rule"] == "dependency-cycle")
                for path, entry in entries.items()
            ),
            "a successful scan of the affected detector inputs after marking pending is required",
        )
    if finding["origin"] == "diagnostic":
        result = state.get("diagnostic_runs", {}).get(finding["tool"], {})
        require(
            result.get("snapshot") == state["snapshot"]
            and result.get("revision", 0) >= pending
            and primary in result.get("coverage", [])
            and result.get("profile") == finding.get("diagnostic_profile"),
            "rerun and import the same applicable diagnostic check after marking pending",
        )
    receipts = matching_receipts(store, state, entries)
    review_ids = array(doc, "review_units")
    require(
        review_ids
        and all(isinstance(unit, str) and unit in receipts for unit in review_ids),
        "supply valid review units",
    )
    reviewed = set()
    for unit in review_ids:
        for receipt in receipts[unit].values():
            if (
                receipt["snapshot"] == state["snapshot"]
                and receipt["revision"] >= pending
                and finding["id"] not in receipt["findings"]
            ):
                reviewed.update(receipt["reads"])
    require(
        required_paths <= reviewed,
        "need fresh review of the source and related locations after marking pending",
    )
    _, valid = checks(state, state_dir)
    ids = array(doc, "verification_ids")
    require(
        ids
        and all(
            isinstance(item, str)
            and item in valid
            and state["verification"][item]["result"] == "passed"
            and state["verification"][item]["kind"] in {"check", "flow"}
            and state["verification"][item]["revision"] >= pending
            for item in ids
        ),
        "need current passing focused check or flow evidence after marking pending",
    )
    require(
        not any(
            finding["id"] in receipts[unit].get(stage, {}).get("findings", [])
            for unit in receipts
            for stage in STAGES
        ),
        "a current review still reports this finding",
    )
    return removal
