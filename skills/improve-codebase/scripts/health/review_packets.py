import uuid
from dataclasses import dataclass
from functools import partial

from .hashing import digest
from .ledger import now, observe
from .review import change_relation, confirmed_fields
from .review_units import (
    STAGES,
    matching_receipts,
    review_work,
    unit_changes,
    unit_matches_paths,
)
from .validation import array, object_value, require, string

MAX_PACKET_UNITS = 50


@dataclass(frozen=True)
class PacketSelection:
    axis: str | None
    stage: str | None
    limit: int
    full: bool
    exclude: list[str]
    partition: str | None
    include: list[str]
    paths: list[str]
    slice_paths: list[str]
    template: bool

    def validate(self, units):
        require(
            1 <= self.limit <= MAX_PACKET_UNITS,
            f"packet limit must be between 1 and {MAX_PACKET_UNITS}",
        )
        require(
            all(identifier in units for identifier in [*self.include, *self.exclude]),
            "requested unit does not exist on this scan",
        )
        require(
            not set(self.include) & set(self.exclude),
            "unit cannot be both requested and excluded",
        )
        require(
            len(set(self.include)) <= self.limit,
            "requested unit count exceeds the packet limit",
        )

    def validate_requested(self, eligible):
        if self.include:
            require(
                {unit["id"] for unit in eligible} == set(self.include)
                and len({unit["axis"] for unit in eligible}) == 1,
                "requested units must be eligible for the same pass and axis; use --full to revisit covered units",
            )

    def selects(self, unit, inventory):
        return (
            unit["id"] not in self.exclude
            and (not self.include or unit["id"] in self.include)
            and (not self.paths or unit_matches_paths(unit, self.paths))
            and (not self.slice_paths or unit_matches_paths(unit, self.slice_paths))
            and (not self.axis or unit["axis"] == self.axis)
            and (
                not self.partition
                or any(
                    inventory["entries"][path]["project"] == self.partition
                    for path in unit["files"]
                )
            )
        )


def eligible_units(state, work, valid, selection):
    units = state["units"]
    selection.validate(units)
    selected = partial(selection.selects, inventory=state["inventory"])
    stage = selection.stage or next(
        (
            phase
            for phase in STAGES
            if any(selected(units[row["id"]]) for row in work[phase])
        ),
        "discovery",
    )
    if selection.full:
        ids = [
            key
            for key, unit in units.items()
            if selected(unit) and (stage == "discovery" or "discovery" in valid[key])
        ]
    else:
        ids = [row["id"] for row in work[stage] if selected(units[row["id"]])]
    eligible = [units[key] for key in ids]
    selection.validate_requested(eligible)
    return stage, eligible


def build_packet(state, root, axis, stage, assigned):
    rules = sorted(
        {
            path
            for unit in assigned
            for path in unit.get("rule_hashes", state["inventory"]["rules"])
        }
    )
    return {
        "id": uuid.uuid4().hex,
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


def save_packet(store, packet, valid):
    stage = packet["pass"]
    ids = [unit["id"] for unit in packet["units"]]
    stored = packet | {
        "prior_receipts": {
            key: valid[key].get(stage, {}).get("packet_id") for key in ids
        },
        "discovery_packets": {
            key: valid[key]["discovery"]["packet_id"]
            for key in ids
            if stage == "confirmation"
        },
    }
    store.save_packet(packet["id"], stored)


def receipt_template(packet):
    return {
        "packet_id": packet["id"],
        "snapshot": packet["snapshot"],
        "sweep_id": packet["sweep_id"],
        "axis": packet["axis"],
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


def prepare(store, state, entries, root, selection):
    require(state.get("snapshot"), "scan before preparing reviews")
    work = review_work(state, matching_receipts(store, state, entries, completion=True))
    valid = matching_receipts(store, state, entries)
    stage, eligible = eligible_units(state, work, valid, selection)
    if not eligible:
        return {"packet": None, "remaining": 0, "pass": stage}
    axis = selection.axis or eligible[0]["axis"]
    eligible = sorted(
        (unit for unit in eligible if unit["axis"] == axis),
        key=lambda unit: (unit.get("wiring_partition") is not None, unit["files"]),
    )
    packet = build_packet(state, root, axis, stage, eligible[: selection.limit])
    save_packet(store, packet, valid)
    result = {"packet": packet, "remaining": len(eligible) - len(packet["units"])}
    if selection.template:
        result["receipt_template"] = receipt_template(packet)
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


def semantic_finding(doc, entries, unit, reads, *, fallout=False):
    obj = object_value(doc, "semantic finding")
    primary = location(obj.get("location"), entries)
    require(
        primary["path"] in reads
        and entries[primary["path"]]["disposition"] == "source",
        "finding must point to reviewed, in-scope source",
    )
    related = [
        location(item, entries)
        for item in (array(obj, "related") if "related" in obj else [])
    ]
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


@dataclass(frozen=True)
class ReceiptUpload:
    packet: dict
    reviewer: str
    independence: str
    incoming: dict
    expected: dict


def read_upload(store, document):
    packet_id = string(document, "packet_id")
    packet = store.load_packet(packet_id)
    require(packet is not None, "unknown or already imported review packet")
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
    return ReceiptUpload(packet, reviewer, independence, incoming, expected)


def validate_unit(upload, identifier, state, known):
    packet = upload.packet
    unit = upload.expected[identifier]
    item = upload.incoming[identifier]
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
    stage = packet["pass"]
    current_stage = known.get(stage, {})
    prior = packet.get("prior_receipts")
    require(
        prior is None or current_stage.get("packet_id") == prior.get(identifier),
        f"a newer {stage} receipt exists for unit {identifier}; prepare a fresh packet",
    )
    return unit, item


def validated_reads(item, unit, entries):
    reads = object_value(item.get("reads"), "reads")
    stale = sorted(
        path
        for path, stamp in reads.items()
        if not isinstance(stamp, str) or entries.get(path, {}).get("hash") != stamp
    )
    require(
        reads and not stale,
        f"review input paths or hashes are stale or invalid: {stale!r}",
    )
    require(
        all(reads.get(path) == hashed for path, hashed in unit["context"].items()),
        "receipt omits files or relationships from the packet",
    )
    return reads


def confirm_discovery(upload, discovery, discovery_packet):
    require(
        discovery_packet and discovery.get("packet_id") == discovery_packet,
        "discovery receipt changed; prepare confirmation again",
    )
    require(
        upload.independence == "sequential" or discovery["reviewer"] != upload.reviewer,
        "independent confirmation needs a different reviewer",
    )


def observe_review_findings(state, entries, findings, previously_known):
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
    return identifiers, changed


def import_unit(upload, identifier, state, entries, known, profile):
    unit, item = validate_unit(upload, identifier, state, known)
    reads = validated_reads(item, unit, entries)
    evidence = string(item, "evidence")
    findings = [
        semantic_finding(
            value, entries, unit, reads, fallout=bool(state.get("fallout_base"))
        )
        for value in array(item, "findings")
    ]
    packet = upload.packet
    stage = packet["pass"]
    discovery_packet = packet["discovery_packets"].get(identifier)
    discovery = known.get("discovery", {})
    if stage == "confirmation":
        confirm_discovery(upload, discovery, discovery_packet)
    previously_known = known.get(stage)
    identifiers, changed = observe_review_findings(
        state, entries, findings, previously_known
    )
    receipt = {
        "profile": profile,
        "packet_id": packet["id"],
        "discovery_packet": discovery_packet,
        "sweep_id": packet["sweep_id"],
        "axis": packet["axis"],
        "snapshot": state["snapshot"],
        "reviewer": upload.reviewer,
        "independence": upload.independence,
        "reads": reads,
        "evidence": evidence,
        "findings": identifiers,
        "observations": outside_observations(item, entries, reads),
        "packet_snapshot": packet["snapshot"],
        "found_new_work": changed,
        "at": now(),
        "revision": state["revision"] + 1,
    }
    rows = []
    if stage == "confirmation" and discovery.get("profile") != profile:
        rows.append((unit["inputs"], "discovery", profile, discovery))
    rows.append((unit["inputs"], stage, profile, receipt))
    if not previously_known:
        state["progress"] += 1
    return rows, identifiers


def import_review(store, state, document, entries):
    upload = read_upload(store, document)
    packet = upload.packet
    valid = matching_receipts(store, state, entries)
    rebased = packet["snapshot"] != state["snapshot"]
    require(
        not rebased or "prior_receipts" in packet,
        "legacy packet is stale; prepare a fresh packet",
    )
    receipts, observed = [], []
    for identifier in upload.incoming:
        rows, findings = import_unit(
            upload, identifier, state, entries, valid.get(identifier, {}), store.key
        )
        receipts.extend(rows)
        observed.extend(findings)
    store.save_receipts(
        receipts,
        {unit["inputs"]: unit["context"] for unit in upload.expected.values()},
    )
    store.consume_packet(packet["id"])
    store.save(
        state,
        "review",
        {
            "packet_id": packet["id"],
            "unit_ids": list(upload.incoming),
            "receipt_packet_ids": sorted({row[3]["packet_id"] for row in receipts}),
            "findings": observed,
        },
    )
    return {
        "accepted_units": len(upload.incoming),
        "findings": observed,
        "rebased": rebased,
    }
