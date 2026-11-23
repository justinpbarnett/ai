from collections import Counter, defaultdict, deque

from .dependency_graph import components, resolve_edges
from .inventory import digest
from .parsers import GRAMMARS, Source, analyze

DEFAULTS = {
    "file_lines": 500,
    "callable_lines": 80,
    "parameters": 6,
    "nesting": 4,
    "complexity": 15,
    "type_lines": 350,
    "html_nodes": 160,
    "html_nesting": 12,
    "css_declarations": 25,
    "selector_terms": 9,
    "selector_ids": 1,
    "duplicate_tokens": 50,
    "duplicate_lines": 8,
}


def candidate(rule, path, anchor, evidence, *, loc=None, related=None):
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
        "signature": digest([rule, anchor, evidence]),
    }


def settings(document):
    if not isinstance(document, dict) or document.keys() - DEFAULTS.keys():
        raise ValueError(
            "thresholds must be an object containing only supported detector names"
        )
    for name, value in document.items():
        minimum = (
            50 if name == "duplicate_tokens" else 8 if name == "duplicate_lines" else 1
        )
        if type(value) is not int or not minimum <= value <= 10000:
            raise ValueError(f"{name} requires an integer between {minimum} and 10000")
    return DEFAULTS | document


def window_starts(tokens, length):
    """Winnow rolling hashes, preserving a shared anchor for matching runs of length + window - 1."""
    if len(tokens) < length:
        return
    mask = (1 << 64) - 1
    base, width = 37, min(12, len(tokens) - length + 1)
    power = pow(base, length - 1, mask + 1)
    values = [int(token[0][-16:], 16) for token in tokens]
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
        first, last = stream[start][1], stream[stop][2]
        if language == "generic-lines" and last - first < 120:
            continue
        signature = digest([token[0] for token in stream[start : stop + 1]])
        yield ("duplicate-block", language, signature), first, last


def duplicate_buckets(parsed, selected, thresholds):
    buckets, sizes = defaultdict(list), {}
    for path in sorted(selected):
        result = parsed[path]
        for name, stream in result["streams"]:
            length = thresholds[
                "duplicate_lines" if name == "generic-lines" else "duplicate_tokens"
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
    start = f"{position:012}" if key[0] == "duplicate-block" else str(position)
    return path, start, key


DUPLICATE_LOCATION_LIMIT = 100


def block_locations(matches, language, covered_ends, data, source_map):
    if all(covered_ends[(path, language)] > start for path, start, _ in matches):
        return []
    locations = []
    for path, start, end in matches:
        covered_ends[(path, language)] = max(covered_ends[(path, language)], end)
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
    covered_ends, source_map = defaultdict(int), {}
    ordering = sorted(
        (key for key, matches in buckets.items() if len(matches) >= 2),
        key=lambda key: duplicate_order(key, buckets[key][0]),
    )
    for key in ordering:
        rule, language, signature = key
        matches = buckets[key]
        locations = (
            block_locations(matches, language, covered_ends, data, source_map)
            if rule == "duplicate-block"
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


def parse_snapshot(entries, sources, parser_profile, core_only, cache_read, full):
    parsed, fresh, work = {}, {}, {}
    cache_keys = {
        p: digest([entries[p]["hash"], entries[p]["language"], parser_profile])
        for p in sources
    }
    cached = {} if full else cache_read(set(cache_keys.values()))
    for path, data in sources.items():
        key = cache_keys[path]
        result = cached.get(key)
        if result is None:
            result = fresh.get(key) or analyze(
                data, entries[path]["language"], core_only
            )
            if not result["gaps"]:
                fresh[key] = result
            work[path] = {
                "status": "investigated" if not result["gaps"] else "pending",
                "reason": "forced refresh"
                if full
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
            "dependency-cycle",
            affected[0],
            "resolved-edges",
            {"members": members, "edges": cycle_edges},
            related=[{"path": path} for path in members if path != affected[0]],
        )


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


def scan_sources(
    inventory, sources, thresholds, parser_profile, core_only, cache_read, full
):
    entries = inventory["entries"]
    selected = {path for path in sources if entries[path]["disposition"] == "source"}
    parsed, fresh, work = parse_snapshot(
        entries, sources, parser_profile, core_only, cache_read, full
    )
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
        "detector_work": work,
    }, fresh
