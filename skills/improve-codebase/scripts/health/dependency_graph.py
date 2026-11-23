import json
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath

from .parsers import GRAMMARS

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
ALIAS_CONFIG_FILES = ("tsconfig.json", "jsconfig.json")
ALIAS_LANGUAGES = {"javascript", "typescript", "tsx", "vue"}
PLACEHOLDER = re.compile(r"[$*{}<>]")
PYTHON_KINDS = {"python", "python-member"}


@dataclass(frozen=True)
class LocalAliases:
    root: str
    paths: dict[str, list[str]]
    has_base_url: bool
    limitation: str | None = None


def relative_option(value):
    return isinstance(value, str) and not value.startswith("/")


def valid_alias(pattern, replacements):
    return (
        pattern.count("*") <= 1
        and isinstance(replacements, list)
        and all(relative_option(item) and item.count("*") <= 1 for item in replacements)
    )


def read_alias_config(path, data):
    directory = posixpath.dirname(path)
    try:
        config = json.loads(data)
        options = config.get("compilerOptions", {})
        if config.get("extends") or config.get("references"):
            raise ValueError("extends or workspace references")
        has_base_url = "baseUrl" in options
        base = options.get("baseUrl", ".")
        if not relative_option(base):
            raise ValueError("nonlocal baseUrl")
        paths = options.get("paths", {})
        if not isinstance(paths, dict) or not all(
            valid_alias(pattern, replacements)
            for pattern, replacements in paths.items()
        ):
            raise ValueError("unsupported paths mapping")
    except (ValueError, TypeError, AttributeError):
        return LocalAliases(
            directory,
            {},
            False,
            "unsupported tsconfig/jsconfig (expected local JSON without extends or project references)",
        )
    return LocalAliases(posixpath.join(directory, base), paths, has_base_url)


def parse_local_aliases(sources):
    return {
        path: read_alias_config(path, data)
        for path, data in sources.items()
        if PurePosixPath(path).name in ALIAS_CONFIG_FILES
    }


def nearest_aliases(ancestors, profiles):
    candidates = (
        str(parent / name) for parent in ancestors for name in ALIAS_CONFIG_FILES
    )
    return next((profiles[path] for path in candidates if path in profiles), None)


def local_targets(paths, base, ref, extensions):
    resolved = posixpath.normpath(posixpath.join(base, ref))
    if resolved == ".." or resolved.startswith(("../", "/")):
        return []
    candidates = dict.fromkeys(
        [
            resolved,
            *(resolved + e for e in extensions),
            *(resolved + "/index" + e for e in extensions),
        ]
    )
    return [path for path in candidates if path in paths]


def alias_replacements(aliases, ref):
    for pattern, replacements in aliases.paths.items():
        prefix, star, suffix = pattern.partition("*")
        if pattern == ref or (
            star
            and ref.startswith(prefix)
            and ref.endswith(suffix)
            and len(ref) >= len(prefix) + len(suffix)
        ):
            capture = ref[len(prefix) : len(ref) - len(suffix)] if star else ""
            yield from (item.replace("*", capture) for item in replacements)


def javascript_targets(paths, parent, ref, aliases):
    if ref.startswith("."):
        matches = local_targets(paths, parent, ref, JS_EXT)
        if not matches and ref.endswith((".js", ".mjs", ".cjs", ".jsx")):
            return local_targets(
                paths, parent, ref.rsplit(".", 1)[0], (".ts", ".mts", ".cts", ".tsx")
            )
        return matches
    if aliases is None or aliases.limitation:
        return []
    matches = [
        path
        for replacement in alias_replacements(aliases, ref)
        for path in local_targets(paths, aliases.root, replacement, JS_EXT)
    ]
    if not matches and aliases.has_base_url:
        return local_targets(paths, aliases.root, ref, JS_EXT)
    return matches


def python_bases(ancestors, project, dots):
    if dots:
        return [str(ancestors[dots - 1])]
    return dict.fromkeys(
        (project, posixpath.join(project, "src"), ".", "src", str(ancestors[0]))
    )


def python_targets(paths, ancestors, project, ref):
    dots = len(ref) - len(ref.lstrip("."))
    if dots > len(ancestors):
        return []
    bases = python_bases(ancestors, project, dots)
    tail = ref[dots:].replace(".", "/")
    matches = []
    for base in bases:
        resolved = posixpath.normpath(posixpath.join(base, tail))
        matches.extend(
            path
            for path in (
                resolved + ".py",
                resolved + ".pyi",
                posixpath.join(resolved, "__init__.py"),
            )
            if path in paths
        )
    return matches


def style_targets(paths, parent, ref):
    base = "." if ref.startswith("/") else parent
    matches = local_targets(paths, base, ref.removeprefix("/"), (".css", ".scss"))
    if not matches and not PLACEHOLDER.search(ref):
        directory, name = posixpath.split(ref)
        return local_targets(
            paths, parent, posixpath.join(directory, "_" + name), (".scss",)
        )
    return matches


def reference_targets(paths, ancestors, project, aliases, kind, ref):
    parent = str(ancestors[0])
    if kind == "js":
        return javascript_targets(paths, parent, ref, aliases)
    if kind in PYTHON_KINDS:
        return python_targets(paths, ancestors, project, ref)
    if kind == "style":
        return style_targets(paths, parent, ref)
    if PLACEHOLDER.search(ref):
        return []
    base = "." if ref.startswith("/") else parent
    return local_targets(
        paths, base, ref.lstrip("/"), JS_EXT if kind == "vue-external" else ()
    )


def member_module(ref):
    prefix = ref[: ref.rfind(".") + 1]
    return prefix if not prefix.strip(".") else prefix[:-1]


def is_symbol_of_resolved_module(paths, ancestors, project, import_kind, ref):
    return import_kind == "python-member" and bool(
        python_targets(paths, ancestors, project, member_module(ref))
    )


def vue_external_gap(entries, path, ref, matches):
    if len(matches) != 1:
        kind, reason = "unavailable", f"cannot resolve {ref}"
    elif entries[matches[0]]["language"] not in GRAMMARS:
        kind, reason = (
            "unsupported",
            f"external source uses an unsupported grammar: {matches[0]}",
        )
    else:
        return None
    return {
        "path": path,
        "kind": kind,
        "surface": "Vue external block",
        "reason": reason,
    }


def source_limitations(result, aliases, language):
    limits = set(result["limits"])
    if aliases and aliases.limitation and language in ALIAS_LANGUAGES:
        limits.add(aliases.limitation)
    return limits


def unresolved_problem(paths, ancestors, project, import_kind, ref, targets):
    if targets:
        return "ambiguous"
    if not is_symbol_of_resolved_module(paths, ancestors, project, import_kind, ref):
        return "unresolved or external"
    return None


def resolve_edges(entries, parsed, sources):
    paths = {
        path
        for path, entry in entries.items()
        if entry["disposition"] in {"source", "context"}
    }
    profiles = parse_local_aliases(sources)
    edges, limitations = set(), defaultdict(set)
    gaps = []
    for path, result in parsed.items():
        parent = PurePosixPath(path).parent
        ancestors = (parent, *parent.parents)
        aliases = nearest_aliases(ancestors, profiles)
        entry = entries[path]
        limits = source_limitations(result, aliases, entry["language"])
        if limits:
            limitations[path].update(limits)
        for import_kind, ref in result["imports"]:
            kind = "python" if import_kind in PYTHON_KINDS else import_kind
            matches = set(
                reference_targets(
                    paths, ancestors, entry["project"], aliases, import_kind, ref
                )
            )
            if kind == "python":
                matches.discard(path)
            targets = sorted(matches)
            if len(targets) == 1:
                edges.add((path, targets[0], kind))
            else:
                problem = unresolved_problem(
                    paths, ancestors, entry["project"], import_kind, ref, targets
                )
                if problem:
                    limitations[path].add(f"{problem} {kind} target: {ref}")
            if kind == "vue-external":
                gap = vue_external_gap(entries, path, ref, targets)
                if gap:
                    gaps.append(gap)
    return (
        sorted(edges),
        {k: sorted(v) for k, v in sorted(limitations.items())},
        gaps,
        sorted({entries[path]["project"] for path in paths}),
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
