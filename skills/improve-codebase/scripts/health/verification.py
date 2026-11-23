from pathlib import Path

from .inventory import content_hash, digest, read_source, safe_file
from .state import array, now, object_value, require, string

VERIFICATION_KINDS = {"baseline", "check", "flow", "final_diff"}
SATISFACTORY_RESULTS = {"passed", "not_applicable"}
VERIFICATION_VERSION = 1


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


def verification_result(state, document):
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
    return {"id": identifier, "kind": kind, "result": result}


def verification_interaction(document, root):
    cwd = Path(string(document, "cwd"))
    require(
        cwd.is_absolute()
        and cwd.resolve() == cwd
        and cwd.is_relative_to(root)
        and cwd.is_dir(),
        "verification cwd must be inside the worktree",
    )
    details = {
        key: string(document, key) for key in ("interaction", "expected", "observed")
    }
    if "exit_status" in document:
        require(type(document["exit_status"]) is int, "exit_status must be an integer")
    return {
        "cwd": str(cwd),
        **details,
        "reason": document.get("reason"),
        "exit_status": document.get("exit_status"),
    }


def verification_baseline(state, document, outcome):
    snapshot = state.get("baseline_snapshot")
    if outcome["kind"] == "baseline":
        if not snapshot and outcome["result"] in SATISFACTORY_RESULTS:
            snapshot = state["snapshot"]
            state["baseline_snapshot"] = snapshot
            state["baseline_inputs"] = state["scope_inputs"]
    else:
        require(
            snapshot and document.get("baseline_snapshot") == snapshot,
            "include the recorded baseline snapshot",
        )
    return snapshot


def verified_artifacts(document, state_dir):
    artifacts = []
    for value in document.get("artifacts", []):
        item = object_value(value, "artifact")
        path = string(item, "path")
        hashed = content_hash(read_source(safe_file(state_dir, path)))
        require(hashed == string(item, "sha256"), "artifact hash does not match")
        artifacts.append({"path": path, "sha256": hashed})
    return artifacts


def record_verification(state, document, root, state_dir):
    require(
        document.get("snapshot") == state.get("snapshot") and state.get("snapshot"),
        "verification snapshot is stale or absent",
    )
    if document.get("kind") == "manifest":
        record_manifest(state, document)
        return {"kind": "manifest", **state["manifest"]}
    outcome = verification_result(state, document)
    details = verification_interaction(document, root)
    baseline = verification_baseline(state, document, outcome)
    artifacts = verified_artifacts(document, state_dir)
    identifier = outcome["id"]
    record = {
        **outcome,
        "snapshot": state["snapshot"],
        "baseline_snapshot": baseline,
        **details,
        "artifacts": artifacts,
        "requirements_hash": digest(state["manifest"]["requirements"][identifier]),
        "verification_version": VERIFICATION_VERSION,
        "at": now(),
        "revision": state["revision"] + 1,
    }
    if outcome["kind"] == "baseline" and (
        baseline == state["snapshot"]
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
