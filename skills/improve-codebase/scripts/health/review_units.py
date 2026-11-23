from collections import defaultdict
from pathlib import Path

from .dependency_graph import project_context
from .inventory import digest, is_project_guide
from .runs import WIRING_LANGUAGES, in_paths

AXES = ("smells", "architecture", "contracts")
STAGES = ("discovery", "confirmation")
REVIEW_VERSION = 3


def paths_by_directory(paths):
    grouped = defaultdict(set)
    for path in paths:
        grouped[Path(path).parent].add(path)
    return grouped


class ReviewUnits:
    def __init__(self, inventory, scan, rubric):
        self.entries = inventory["entries"]
        self.rules = inventory["rules"]
        self.edges = scan["edges"]
        self.limits = scan["limitations"]
        self.rubric = rubric
        self.guides = paths_by_directory(
            path
            for path, entry in self.entries.items()
            if entry["disposition"] == "reference" and is_project_guide(path)
        )
        self.rules_by_directory = paths_by_directory(self.rules)
        self.adjacent = defaultdict(set)
        self.relationships = defaultdict(set)
        self.project_neighbors = defaultdict(set)
        self.partition_inputs = {}
        self.units = {}
        self.index_edges()

    def index_edges(self):
        for left, right, kind in self.edges:
            self.adjacent[left].add(right)
            self.adjacent[right].add(left)
            self.relationships[left].add((left, right, kind))
            self.relationships[right].add((left, right, kind))
            first, second = (
                self.entries[left]["project"],
                self.entries[right]["project"],
            )
            if first != second:
                self.project_neighbors[first].add(second)
                self.project_neighbors[second].add(first)

    def partition_paths(self, project):
        if project not in self.partition_inputs:
            linked, pending = set(), [project]
            while pending:
                name = pending.pop()
                if name not in linked:
                    linked.add(name)
                    pending.extend(self.project_neighbors[name] - linked)
            inputs = set().union(
                *(project_context(name, self.entries) for name in linked)
            )
            self.partition_inputs.update(dict.fromkeys(linked, inputs))
        return self.partition_inputs[project]

    def register(self, axis, files, related, *, wiring=None):
        files = sorted(files)
        context_paths = set(files) | set(related)
        directories = {
            parent for path in context_paths for parent in Path(path).parents
        }
        documentation = {
            guide
            for directory in directories
            for guide in self.guides.get(directory, ())
        }
        rules = {
            path: self.rules[path]
            for directory in directories
            for path in self.rules_by_directory.get(directory, ())
        }
        governing = digest([self.rubric, rules])
        context = {
            p: self.entries[p]["hash"] for p in sorted(context_paths | documentation)
        }
        identifier = digest(
            [axis, files] if wiring is None else [axis, "wiring", wiring]
        )[:24]
        edges = sorted({edge for path in files for edge in self.relationships[path]})
        limits = {
            path: self.limits[path] for path in context_paths if path in self.limits
        }
        inputs = digest([identifier, context, governing, wiring, edges, limits])
        self.units[identifier] = {
            "id": identifier,
            "axis": axis,
            "files": files,
            "inputs": inputs,
            "context": context,
            "relationships": edges,
            "project_partitions": sorted(
                {self.entries[path]["project"] for path in files}
            ),
            "wiring_partition": wiring,
            "governing": governing,
            "rule_hashes": rules,
            "rubric": self.rubric,
            "limitations": limits,
        }

    def register_sources(self, source, uncertain_files):
        for path in sorted(source):
            entry = self.entries[path]
            if entry["language"] in WIRING_LANGUAGES or self.limits.get(path):
                uncertain_files[entry["project"]].add(path)
            for axis in AXES:
                self.register(axis, [path], self.adjacent[path])

    def register_relationships(self, source, uncertain_files):
        for left, right, kind in self.edges:
            if left == right or not ({left, right} & source):
                continue
            if kind == "project":
                for path in {left, right} & source:
                    uncertain_files[self.entries[path]["project"]].add(path)
            related = self.adjacent[left] | self.adjacent[right]
            for axis in ("architecture", "contracts"):
                self.register(axis, [left, right], related)


def units_for(inv, scan, rubric):
    catalog = ReviewUnits(inv, scan, rubric)
    source = {p for p, e in catalog.entries.items() if e["disposition"] == "source"}
    uncertain = defaultdict(set)
    catalog.register_sources(source, uncertain)
    catalog.register_relationships(source, uncertain)
    for project, files in sorted(uncertain.items()):
        for axis in ("architecture", "contracts"):
            catalog.register(
                axis, files, catalog.partition_paths(project), wiring=project
            )
    return catalog.units


def changed_reads(reads, entries):
    return sorted(
        path
        for path, stamp in reads.items()
        if entries.get(path, {}).get("hash") != stamp
    )


def confirmation_matches(saved, discovery, completion):
    return (
        not (completion and saved["found_new_work"])
        and discovery is not None
        and discovery["packet_id"] == saved["discovery_packet"]
    )


def matching_receipts(store, state, entries, *, completion=False, stale_inputs=None):
    units = state.get("units", {})
    receipts = store.receipts({unit["inputs"] for unit in units.values()})
    valid = {}
    for unit_id, unit in units.items():
        passes = {}
        for stage in STAGES:
            saved = receipts[unit["inputs"]].get(stage)
            if saved is None or (
                saved.get("profile") != store.key and saved["findings"]
            ):
                continue
            changed = changed_reads(saved["reads"], entries)
            if changed:
                if stale_inputs is not None:
                    stale_inputs.setdefault(unit_id, {})[stage] = changed
                continue
            if stage == "confirmation" and not confirmation_matches(
                saved, passes.get("discovery"), completion
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
