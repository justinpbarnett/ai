import json
import posixpath
from collections import Counter, defaultdict, deque
from pathlib import PurePosixPath

from .inventory import digest, within
from .parsers import GRAMMARS, PLACEHOLDER, Source, analyze

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
JS_EXT = (
    ".ts",
    ".tsx",
    ".mts",
    ".cts",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".vue",
    ".json",
    ".css",
    ".scss",
)


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


def parse_local_aliases(sources):
    profiles = {}
    for path, data in sources.items():
        if PurePosixPath(path).name not in {"tsconfig.json", "jsconfig.json"}:
            continue
        try:
            config = json.loads(data)
            options = config.get("compilerOptions", {})
            if config.get("extends") or config.get("references"):
                raise ValueError("extends or workspace references")
            base = options.get("baseUrl", ".")
            if not isinstance(base, str) or base.startswith("/"):
                raise ValueError("nonlocal baseUrl")
            paths = options.get("paths", {})
            if not isinstance(paths, dict):
                raise ValueError("unsupported paths mapping")
            for key, targets in paths.items():
                if (
                    key.count("*") > 1
                    or not isinstance(targets, list)
                    or any(
                        not isinstance(item, str)
                        or item.startswith("/")
                        or item.count("*") > 1
                        for item in targets
                    )
                ):
                    raise ValueError("unsupported paths mapping")
            profiles[path] = (base, paths, None)
        except (ValueError, TypeError, AttributeError):
            profiles[path] = (
                None,
                {},
                "unsupported tsconfig/jsconfig (expected local JSON without extends or project references)",
            )
    return profiles


def resolve_edges(entries, parsed, sources):
    paths = {
        path
        for path, entry in entries.items()
        if entry["disposition"] in {"source", "context"}
    }
    profiles = parse_local_aliases(sources)
    project_roots = {entries[path]["project"] for path in paths}
    edges, limitations = set(), defaultdict(set)
    gaps = []

    def targets(base, ref, extensions):
        resolved = posixpath.normpath(posixpath.join(base, ref))
        if resolved == ".." or resolved.startswith(("../", "/")):
            return []
        return [
            p
            for p in dict.fromkeys(
                [
                    resolved,
                    *(resolved + e for e in extensions),
                    *(resolved + "/index" + e for e in extensions),
                ]
            )
            if p in paths
        ]

    for path, result in parsed.items():
        if result["limits"]:
            limitations[path].update(result["limits"])
        parent = PurePosixPath(path).parent
        ancestors = (parent, *parent.parents)
        project = entries[path]["project"]
        configs = (
            str(p / name)
            for p in ancestors
            for name in ("tsconfig.json", "jsconfig.json")
        )
        config_path = next((p for p in configs if p in profiles), None)
        if (
            config_path
            and profiles[config_path][2]
            and entries[path]["language"] in {"javascript", "typescript", "tsx", "vue"}
        ):
            limitations[path].add(profiles[config_path][2])
        for kind, ref in result["imports"]:
            matches = []
            if kind == "js":
                if ref.startswith("."):
                    matches = targets(str(parent), ref, JS_EXT)
                    if not matches and ref.endswith((".js", ".mjs", ".cjs", ".jsx")):
                        matches = targets(
                            str(parent),
                            ref.rsplit(".", 1)[0],
                            (".ts", ".mts", ".cts", ".tsx"),
                        )
                elif config_path:
                    base, aliases, _ = profiles[config_path]
                    if base is not None:
                        for key, values in aliases.items():
                            pre, star, post = key.partition("*")
                            if (
                                star
                                and ref.startswith(pre)
                                and ref.endswith(post)
                                and len(ref) >= len(pre) + len(post)
                            ) or key == ref:
                                capture = (
                                    ref[len(pre) : len(ref) - len(post)] if star else ""
                                )
                                for item in values:
                                    matches.extend(
                                        targets(
                                            posixpath.join(
                                                posixpath.dirname(config_path), base
                                            ),
                                            item.replace("*", capture),
                                            JS_EXT,
                                        )
                                    )
                        if not matches:
                            matches = targets(
                                posixpath.join(posixpath.dirname(config_path), base),
                                ref,
                                JS_EXT,
                            )
            elif kind == "python":
                dots = len(ref) - len(ref.lstrip("."))
                tail = ref[dots:].replace(".", "/")
                if dots and dots <= len(ancestors):
                    bases = [str(ancestors[dots - 1])]
                elif dots:
                    bases = []
                else:
                    bases = list(
                        dict.fromkeys(
                            (project, posixpath.join(project, "src"), ".", "src")
                        )
                    )
                for base in bases:
                    resolved = posixpath.normpath(posixpath.join(base, tail))
                    matches.extend(
                        p
                        for p in (
                            resolved + ".py",
                            resolved + ".pyi",
                            posixpath.join(resolved, "__init__.py"),
                        )
                        if p in paths
                    )
            elif kind == "style":
                matches = (
                    targets(str(parent), ref.removeprefix("/"), (".css", ".scss"))
                    if not ref.startswith("/")
                    else targets(".", ref[1:], (".css", ".scss"))
                )
                if not matches and not PLACEHOLDER.search(ref):
                    directory, name = posixpath.split(ref)
                    matches = targets(
                        str(parent), posixpath.join(directory, "_" + name), (".scss",)
                    )
            elif not PLACEHOLDER.search(ref):
                matches = targets(
                    "." if ref.startswith("/") else str(parent),
                    ref.lstrip("/"),
                    JS_EXT if kind == "vue-external" else (),
                )
            matches = sorted(set(matches) - ({path} if kind == "python" else set()))
            if len(matches) == 1:
                other = matches[0]
                edges.add((path, other, kind))
                if (
                    kind == "vue-external"
                    and entries[other]["language"] not in GRAMMARS
                ):
                    gaps.append(
                        {
                            "path": path,
                            "kind": "unsupported",
                            "surface": "Vue external block",
                            "reason": f"external source uses an unsupported grammar: {other}",
                        }
                    )
            elif len(matches) > 1:
                limitations[path].add(f"ambiguous {kind} target: {ref}")
            else:
                limitations[path].add(f"unresolved or external {kind} target: {ref}")
            if kind == "vue-external" and len(matches) != 1:
                gaps.append(
                    {
                        "path": path,
                        "kind": "unavailable",
                        "surface": "Vue external block",
                        "reason": f"cannot resolve {ref}",
                    }
                )
    graph_projects = sorted(project_roots)
    return (
        sorted(edges),
        {k: sorted(v) for k, v in sorted(limitations.items())},
        gaps,
        graph_projects,
    )


def components(edges):
    outgoing, incoming = defaultdict(set), defaultdict(set)
    for source, target, _ in edges:
        outgoing[source].add(target)
        incoming[target].add(source)
    vertices = sorted(outgoing.keys() | incoming.keys())
    visited, order = set(), []
    for start in vertices:
        stack = [(start, False)]
        while stack:
            node, exiting = stack.pop()
            if exiting:
                order.append(node)
            elif node not in visited:
                visited.add(node)
                stack.append((node, True))
                stack.extend(
                    (child, False)
                    for child in sorted(outgoing[node], reverse=True)
                    if child not in visited
                )
    visited.clear()
    for start in reversed(order):
        group, stack = [], [start]
        while stack:
            node = stack.pop()
            if node not in visited:
                visited.add(node)
                group.append(node)
                stack.extend(incoming[node] - visited)
        if len(group) > 1 or (group and group[0] in outgoing[group[0]]):
            yield sorted(group)


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


def duplicates(parsed, data, selected, thresholds):
    buckets, sizes = defaultdict(list), {}
    for path in sorted(selected):
        result = parsed[path]
        for name, token_stream in result["streams"]:
            length = (
                thresholds["duplicate_lines"]
                if name == "generic-lines"
                else thresholds["duplicate_tokens"]
            )
            for start in window_starts(token_stream, length):
                stop = start + length - 1
                first, last = token_stream[start][1], token_stream[stop][2]
                if name == "generic-lines" and last - first < 120:
                    continue
                key = (
                    "duplicate-block",
                    name,
                    digest([entry[0] for entry in token_stream[start : stop + 1]]),
                )
                if (
                    not buckets[key]
                    or buckets[key][-1][0] != path
                    or buckets[key][-1][2] <= first
                ):
                    buckets[key].append((path, first, last))
                    sizes[key] = length
        for kind, hashed, loc, size in result["groups"]:
            source = data[path]
            key = (kind, loc["language"], hashed)
            buckets[key].append((path, loc, source))
            sizes[key] = size
    covered_ends, source_map = defaultdict(int), {}
    ordering = sorted(
        (key for key, values in buckets.items() if len(values) >= 2),
        key=lambda key: (
            buckets[key][0][0],
            str(buckets[key][0][1])
            if key[0] != "duplicate-block"
            else f"{buckets[key][0][1]:012}",
            key,
        ),
    )
    for key in ordering:
        rule, language, signature = key
        values = buckets[key]
        if rule == "duplicate-block":
            if all(covered_ends[(path, language)] > start for path, start, _ in values):
                continue
            locations = []
            for path, start, end in values:
                covered_ends[(path, language)] = max(
                    covered_ends[(path, language)], end
                )
                if len(locations) < 100:
                    if path not in source_map:
                        source_map[path] = Source(data[path])
                    locations.append(
                        {"path": path, **source_map[path].location(start, end)}
                    )
        else:
            locations = [
                {
                    "path": path,
                    **{
                        k: metric[k]
                        for k in ("line", "column", "end_line", "end_column")
                    },
                }
                for path, metric, _ in values[:100]
            ]
        yield candidate(
            rule,
            locations[0]["path"],
            signature,
            {
                "language": language,
                "matched_units": sizes[key],
                "occurrences": len(values),
                "locations_shown": len(locations),
            },
            loc=locations[0],
            related=locations[1:],
        )


def scan_sources(
    inventory, sources, thresholds, parser_profile, core_only, cache_read, full
):
    entries = inventory["entries"]
    selected = {p for p in sources if entries[p]["disposition"] == "source"}
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
    edges, limits, graph_gaps, projects = resolve_edges(entries, parsed, sources)
    adjacency = defaultdict(set)
    for source, target, _ in edges:
        adjacency[source].add(target)
        adjacency[target].add(source)
    findings, metrics, gaps = [], {}, []
    for path in sorted(selected):
        result = parsed[path]
        metrics[path] = result["metrics"]
        gaps.extend({"path": path, **gap} for gap in result["gaps"])
        loc = entries[path]["loc"]
        if loc > thresholds["file_lines"]:
            findings.append(
                candidate(
                    "large-file",
                    path,
                    "file",
                    {"nonblank_lines": loc, "threshold": thresholds["file_lines"]},
                )
            )
        anchors = Counter()
        for metric in result["metrics"]:
            kind = metric["kind"]
            anchor = metric["anchor"]
            anchors[anchor] += 1
            if anchors[anchor] != 1:
                anchor += f"#{anchors[anchor]}"
            rules = {
                "callable": [
                    ("callable_lines", "lines"),
                    ("parameters", "parameters"),
                    ("nesting", "nesting"),
                    ("complexity", "complexity"),
                ],
                "type": [("type_lines", "lines")],
                "element": [("html_nodes", "size"), ("html_nesting", "nesting")],
                "rule": [
                    ("css_declarations", "size"),
                    ("selector_terms", "selector_terms"),
                    ("selector_ids", "selector_ids"),
                    ("nesting", "nesting"),
                ],
            }[kind]
            for rule, field in rules:
                if metric[field] > thresholds[rule]:
                    findings.append(
                        candidate(
                            rule,
                            path,
                            anchor,
                            {
                                "metric": field,
                                "value": metric[field],
                                "threshold": thresholds[rule],
                                "language": metric["language"],
                                "structural_evidence": metric.get(
                                    "parameter_evidence"
                                    if rule == "parameters"
                                    else "evidence"
                                ),
                            },
                            loc=metric,
                        )
                    )
    relevant = selected | {other for path in selected for other in adjacency[path]}
    for path in sorted(relevant - selected):
        if entries[path]["language"] in GRAMMARS:
            gaps.extend({"path": path, **gap} for gap in parsed[path]["gaps"])
    gaps.extend(gap for gap in graph_gaps if gap["path"] in relevant)
    findings.extend(duplicates(parsed, sources, selected, thresholds))
    by_source = defaultdict(list)
    for edge in edges:
        by_source[edge[0]].append(edge)
    for members in components(edges):
        affected = sorted(set(members) & selected)
        if affected:
            member_set = set(members)
            cycle_edges = [
                edge
                for source in members
                for edge in by_source[source]
                if edge[1] in member_set
            ]
            findings.append(
                candidate(
                    "dependency-cycle",
                    affected[0],
                    "resolved-edges",
                    {"members": members, "edges": cycle_edges},
                    related=[{"path": path} for path in members if path != affected[0]],
                )
            )
    partition_sizes = defaultdict(lambda: {"files": 0, "nonblank_lines": 0})
    for path in selected:
        partition = partition_sizes[entries[path]["project"]]
        partition["files"] += 1
        partition["nonblank_lines"] += entries[path]["loc"]
    sizes = sorted(
        ((p, entries[p]["loc"]) for p in selected), key=lambda pair: (-pair[1], pair[0])
    )
    return {
        "candidates": findings,
        "edges": edges,
        "limitations": limits,
        "gaps": gaps,
        "projects": projects,
        "partitions": dict(partition_sizes),
        "file_rankings": sizes,
        "metrics": metrics,
        "detector_work": work,
    }, fresh


def project_context(project, entries):
    return {
        path
        for path, entry in entries.items()
        if entry.get("hash")
        and (entry.get("project") == project or within(path, project))
    }
