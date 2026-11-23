from pathlib import Path

from .diagnostics import ingest
from .review import batch_identity as triage_identity
from .review import triage
from .review_packets import import_review
from .scanning import current_inventory
from .validation import array, object_value, read_json, require
from .verification import batch_identity as verification_identity
from .verification import record_verification


def record_batch(command, store, state, document, entries):
    finding = command == "finding"
    state_dir = store.path.parent
    root = Path(state["root"])
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
            identifier = (triage_identity if finding else verification_identity)(event)
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


STALE_INPUTS = "scan before writing evidence: inputs are stale or unscanned"


def latest_state_with_same_inputs(store, state, current, scope):
    latest = store.load()
    if latest["revision"] != state["revision"]:
        latest_inventory, fresh = current_inventory(store, latest, scope)
        require(
            fresh and latest_inventory["fingerprint"] == current["fingerprint"],
            STALE_INPUTS,
        )
    return latest


def import_evidence(args, store, state, current, scope):
    diagnostic = args.command == "import-diagnostics"
    document = object_value(
        read_json(args.metadata if diagnostic else args.input), "input"
    )
    entries = current["entries"]
    with store.transaction():
        if args.command == "review":
            state = latest_state_with_same_inputs(store, state, current, scope)
            result = import_review(store, state, document, entries)
        else:
            store.assert_revision(
                document.get("revision", state["revision"] if diagnostic else None)
            )
            store.assert_revision(state["revision"])
            require(
                document.get("snapshot") == state["snapshot"], "input snapshot is stale"
            )
            if diagnostic:
                result = ingest(
                    store, state, Path(state["root"]), args.tool, args.input, document
                )
            else:
                result = record_batch(args.command, store, state, document, entries)
        current_again, _ = scope.collect()
        require(
            current_again["fingerprint"] == current["fingerprint"],
            "source changed during import; no evidence was committed",
        )
    return {
        "revision": state["revision"],
        "snapshot": state["snapshot"],
        "result": result,
    }
