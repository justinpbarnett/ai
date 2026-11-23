from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from .case_evidence import test_evidence, test_signature
from .comments import comment_evidence, comment_signature
from .dependency_graph import components, resolve_edges
from .hashing import digest
from .layout import (
    change_coupling,
    commit_sets,
    directory_findings,
    locality,
)
from .parsers import GRAMMARS, analyze
from .paths import is_test_path
from .rules import DEPENDENCY_CYCLE, DUPLICATE_BLOCK
from .syntax_tree import (
    GENERIC_STREAM,
    ROLLING_HASH_WIDTH,
    TOKEN_END,
    TOKEN_HASH,
    TOKEN_START,
    Source,
)


def candidate(
    rule, path, anchor, evidence, *, loc=None, related=None, signature_basis=None
):
    location = {"path": path}
    if loc:
        location.update(
            {
                k: loc[k]
                for k in ("line", "column", "end_line", "end_column")
                if k in loc
            }
        )
    return {
        "origin": "scanner",
        "rule": rule,
        "anchor": anchor,
        "location": location,
        "related": related or [],
        "observation": evidence,
        "signature": digest(
            [rule, anchor, evidence if signature_basis is None else signature_basis]
        ),
    }


def window_starts(tokens, length):
    if len(tokens) < length:
        return
    mask = (1 << 64) - 1
    base, width = 37, min(12, len(tokens) - length + 1)
    power = pow(base, length - 1, mask + 1)
    values = [int(token[TOKEN_HASH][-ROLLING_HASH_WIDTH:], 16) for token in tokens]
    value = 0
    for item in values[: length - 1]:
        value = (value * base + item) & mask
    minima, last = deque(), -1
    for index, item in enumerate(values[length - 1 :]):
        value = (value * base + item) & mask
        while minima and minima[-1][0] >= value:
            minima.pop()
        minima.append((value, index))
        if minima[0][1] <= index - width:
            minima.popleft()
        if index >= width - 1 and minima[0][1] != last:
            last = minima[0][1]
            yield last
        value = (value - values[index] * power) & mask


def block_anchors(stream, language, length):
    for start in window_starts(stream, length):
        stop = start + length - 1
        first, last = stream[start][TOKEN_START], stream[stop][TOKEN_END]
        if language == GENERIC_STREAM and last - first < 120:
            continue
        signature = digest([token[TOKEN_HASH] for token in stream[start : stop + 1]])
        yield (DUPLICATE_BLOCK, language, signature), first, last


def duplicate_buckets(parsed, selected, thresholds):
    buckets, sizes = defaultdict(list), {}
    for path in sorted(selected):
        result = parsed[path]
        for name, stream in result["streams"]:
            length = thresholds[
                "duplicate_lines" if name == GENERIC_STREAM else "duplicate_tokens"
            ]
            for key, first, last in block_anchors(stream, name, length):
                matches = buckets[key]
                if not matches or matches[-1][0] != path or matches[-1][2] <= first:
                    matches.append((path, first, last))
                    sizes[key] = length
        for rule, signature, location, size in result["groups"]:
            key = (rule, location["language"], signature)
            buckets[key].append((path, location))
            sizes[key] = size
    return buckets, sizes


def duplicate_order(key, first_match):
    path, position, *_ = first_match
    if key[0] == DUPLICATE_BLOCK:
        start = f"{position:012}"
    else:
        start = f"{position['line']:012}{position['column']:012}"
    return path, start, key


DUPLICATE_LOCATION_LIMIT = 100


def is_covered(intervals, position):
    index = bisect_right(intervals, position, key=lambda interval: interval[0])
    return index > 0 and intervals[index - 1][1] > position


def cover(intervals, start, end):
    left = bisect_left(intervals, start, key=lambda interval: interval[1])
    right = bisect_right(intervals, end, key=lambda interval: interval[0])
    if left < right:
        start = min(start, intervals[left][0])
        end = max(end, intervals[right - 1][1])
    intervals[left:right] = [(start, end)]


def block_locations(matches, language, covered, data, source_map):
    if all(is_covered(covered[(path, language)], start) for path, start, _ in matches):
        return []
    locations = []
    for path, start, end in matches:
        cover(covered[(path, language)], start, end)
        if len(locations) < DUPLICATE_LOCATION_LIMIT:
            if path not in source_map:
                source_map[path] = Source(data[path])
            locations.append({"path": path, **source_map[path].location(start, end)})
    return locations


def group_locations(matches):
    return [
        {
            "path": path,
            **{
                key: metric[key] for key in ("line", "column", "end_line", "end_column")
            },
        }
        for path, metric in matches[:DUPLICATE_LOCATION_LIMIT]
    ]


def duplicates(parsed, data, selected, thresholds):
    buckets, sizes = duplicate_buckets(parsed, selected, thresholds)
    covered, source_map = defaultdict(list), {}
    ordering = sorted(
        (key for key, matches in buckets.items() if len(matches) >= 2),
        key=lambda key: duplicate_order(key, buckets[key][0]),
    )
    for key in ordering:
        rule, language, signature = key
        matches = buckets[key]
        locations = (
            block_locations(matches, language, covered, data, source_map)
            if rule == DUPLICATE_BLOCK
            else group_locations(matches)
        )
        if not locations:
            continue
        yield candidate(
            rule,
            locations[0]["path"],
            signature,
            {
                "language": language,
                "matched_units": sizes[key],
                "occurrences": len(matches),
                "locations_shown": len(locations),
            },
            loc=locations[0],
            related=locations[1:],
        )


@dataclass(frozen=True)
class ParseOptions:
    parser_profile: str
    core_only: bool
    cache_read: Callable
    full: bool


def parse_snapshot(entries, sources, options):
    parsed, fresh, work = {}, {}, {}
    cache_keys = {
        p: f"{options.parser_profile}:"
        + digest(
            [
                entries[p]["hash"],
                entries[p]["language"],
                options.parser_profile,
                is_test_path(p),
            ]
        )
        for p in sources
    }
    cached = {} if options.full else options.cache_read(set(cache_keys.values()))
    for path, data in sources.items():
        key = cache_keys[path]
        result = cached.get(key)
        if result is None:
            result = fresh.get(key) or analyze(
                data, entries[path]["language"], options.core_only, is_test_path(path)
            )
            if not result["gaps"]:
                fresh[key] = result
            work[path] = {
                "status": "investigated" if not result["gaps"] else "pending",
                "reason": "forced refresh"
                if options.full
                else "no valid detector result for current inputs",
            }
        else:
            work[path] = {
                "status": "reused",
                "reason": "matching content and detector capability/configuration",
            }
        parsed[path] = result
    return parsed, fresh, work


METRIC_RULES = {
    "callable": (
        ("callable_lines", "lines"),
        ("parameters", "parameters"),
        ("nesting", "nesting"),
        ("complexity", "complexity"),
    ),
    "type": (("type_lines", "lines"),),
    "element": (("html_nodes", "size"), ("html_nesting", "nesting")),
    "rule": (
        ("css_declarations", "size"),
        ("selector_terms", "selector_terms"),
        ("selector_ids", "selector_ids"),
        ("nesting", "nesting"),
    ),
}


def file_metric_findings(path, lines, metrics, thresholds):
    if lines > thresholds["file_lines"]:
        yield candidate(
            "large-file",
            path,
            "file",
            {"nonblank_lines": lines, "threshold": thresholds["file_lines"]},
        )
    anchors = Counter()
    for metric in metrics:
        anchor = metric["anchor"]
        anchors[anchor] += 1
        if anchors[anchor] != 1:
            anchor += f"#{anchors[anchor]}"
        for rule, field in METRIC_RULES[metric["kind"]]:
            if metric[field] <= thresholds[rule]:
                continue
            evidence = "parameter_evidence" if rule == "parameters" else "evidence"
            yield candidate(
                rule,
                path,
                anchor,
                {
                    "metric": field,
                    "value": metric[field],
                    "threshold": thresholds[rule],
                    "language": metric["language"],
                    "structural_evidence": metric.get(evidence),
                },
                loc=metric,
            )


def scan_gaps(entries, parsed, selected, edges, graph_gaps):
    for path in sorted(selected):
        yield from ({"path": path, **gap} for gap in parsed[path]["gaps"])
    neighbors = set()
    for source, target, _ in edges:
        if source in selected:
            neighbors.add(target)
        if target in selected:
            neighbors.add(source)
    for path in sorted(neighbors - selected):
        if entries[path]["language"] in GRAMMARS:
            yield from ({"path": path, **gap} for gap in parsed[path]["gaps"])
    relevant = selected | neighbors
    yield from (gap for gap in graph_gaps if gap["path"] in relevant)


def cycle_findings(edges, selected):
    by_source = defaultdict(list)
    for edge in edges:
        by_source[edge[0]].append(edge)
    for members in components(edges):
        affected = sorted(set(members) & selected)
        if not affected:
            continue
        member_set = set(members)
        cycle_edges = [
            edge
            for source in members
            for edge in by_source[source]
            if edge[1] in member_set
        ]
        yield candidate(
            DEPENDENCY_CYCLE,
            affected[0],
            "resolved-edges",
            {"members": members, "edges": cycle_edges},
            related=[{"path": path} for path in members if path != affected[0]],
        )


def comment_findings(path, rows, thresholds):
    evidence = comment_evidence(rows)
    if evidence["removable"] >= thresholds["comments"]:
        yield candidate(
            "comments",
            path,
            "file",
            evidence,
            signature_basis=comment_signature(rows),
        )


def test_findings(path, result, language):
    if result["tests"] is not None:
        yield candidate(
            "tests",
            path,
            "file",
            test_evidence(result["tests"], language, bool(result["gaps"])),
            signature_basis=test_signature(
                result["tests"], language, bool(result["gaps"])
            ),
        )


def layout_candidates(selected, edges, history, thresholds):
    files = {path for path in selected if not is_test_path(path)}
    found = [
        candidate(rule, path, anchor, evidence, related=related)
        for rule, path, anchor, evidence, related in directory_findings(
            files, edges, thresholds
        )
    ]
    sets = commit_sets(history, files)
    found.extend(
        candidate(rule, path, anchor, evidence, related=related, signature_basis=[])
        for rule, path, anchor, evidence, related in change_coupling(sets, thresholds)
    )
    return found, locality(history, sets)


def source_sizes(entries, selected):
    partition_sizes = defaultdict(lambda: {"files": 0, "nonblank_lines": 0})
    for path in selected:
        partition = partition_sizes[entries[path]["project"]]
        partition["files"] += 1
        partition["nonblank_lines"] += entries[path]["loc"]
    sizes = sorted(
        ((p, entries[p]["loc"]) for p in selected), key=lambda pair: (-pair[1], pair[0])
    )
    return dict(partition_sizes), sizes


def scan_sources(inventory, sources, thresholds, options, history):
    entries = inventory["entries"]
    selected = {path for path in sources if entries[path]["disposition"] == "source"}
    parsed, fresh, work = parse_snapshot(entries, sources, options)
    edges, limits, graph_gaps, projects = resolve_edges(entries, parsed, sources)
    metrics = {path: parsed[path]["metrics"] for path in sorted(selected)}
    findings = [
        finding
        for path, measured in metrics.items()
        for finding in file_metric_findings(
            path, entries[path]["loc"], measured, thresholds
        )
    ]
    findings.extend(duplicates(parsed, sources, selected, thresholds))
    findings.extend(cycle_findings(edges, selected))
    for path in sorted(selected):
        findings.extend(comment_findings(path, parsed[path]["comments"], thresholds))
        findings.extend(test_findings(path, parsed[path], entries[path]["language"]))
    found, layout = layout_candidates(selected, edges, history, thresholds)
    findings.extend(found)
    if not history["available"]:
        limits["(git history)"] = [f"change coupling unavailable: {history['reason']}"]
    partitions, sizes = source_sizes(entries, selected)
    return {
        "candidates": findings,
        "edges": edges,
        "limitations": limits,
        "gaps": list(scan_gaps(entries, parsed, selected, edges, graph_gaps)),
        "projects": projects,
        "partitions": partitions,
        "file_rankings": sizes,
        "metrics": metrics,
        "layout": layout,
        "detector_work": work,
    }, fresh
