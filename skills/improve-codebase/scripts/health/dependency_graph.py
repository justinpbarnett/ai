import json
import posixpath
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath

from .parsers import GRAMMARS

JS_CODE_EXT = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
JS_DATA_EXT = (".json", ".vue")
JS_STYLE_EXT = (".css", ".scss")
ALIAS_CONFIG_FILES = ("tsconfig.json", "jsconfig.json")
ALIAS_LANGUAGES = {"javascript", "typescript", "tsx", "vue"}
PLACEHOLDER = re.compile(r"[$*{}<>]")
PYTHON_KINDS = {"python", "python-member"}
EXTERNAL_PROBLEM = "external"


@dataclass(frozen=True)
class LocalAliases:
    root: str
    paths: dict[str, list[str]]
    has_base_url: bool
    limitation: str | None = None


@dataclass(frozen=True)
class ImportSite:
    paths: set[str]
    ancestors: tuple[PurePosixPath, ...]
    project: str
    aliases: LocalAliases | None


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


def contained_path(base, ref):
    resolved = posixpath.normpath(posixpath.join(base, ref))
    if resolved == ".." or resolved.startswith(("../", "/")):
        return None
    return resolved


def names_directory(ref):
    return ref.endswith("/") or posixpath.basename(ref) in {".", ".."}


def with_extensions(stem, extensions):
    return tuple(stem + e for e in extensions)


def index_files(directory, extensions):
    return tuple(
        posixpath.normpath(posixpath.join(directory, "index" + e)) for e in extensions
    )


def local_targets(paths, base, ref, extensions):
    resolved = contained_path(base, ref)
    if resolved is None:
        return []
    candidates = dict.fromkeys(
        [
            resolved,
            *with_extensions(resolved, extensions),
            *index_files(resolved, extensions),
        ]
    )
    return [path for path in candidates if path in paths]


def tiered_targets(paths, base, ref):
    resolved = contained_path(base, ref)
    if resolved is None:
        return []
    index_tiers = (
        index_files(resolved, JS_CODE_EXT),
        index_files(resolved, JS_DATA_EXT),
    )
    if names_directory(ref):
        tiers = index_tiers
    else:
        tiers = (
            (resolved,),
            with_extensions(resolved, JS_CODE_EXT),
            with_extensions(resolved, JS_DATA_EXT),
            *index_tiers,
            with_extensions(resolved, JS_STYLE_EXT),
            index_files(resolved, JS_STYLE_EXT),
        )
    return next(
        (
            matches
            for tier in tiers
            if (matches := [path for path in tier if path in paths])
        ),
        [],
    )


SUFFIX_SWAPS = {
    ".js": ((".ts",), (".tsx",)),
    ".jsx": ((".tsx",),),
    ".mjs": ((".mts",),),
    ".cjs": ((".cts",),),
}


def swapped_targets(paths, base, ref):
    resolved = contained_path(base, ref)
    suffix = posixpath.splitext(ref)[1]
    if resolved is None or suffix not in SUFFIX_SWAPS:
        return []
    stem = resolved[: -len(suffix)]
    return next(
        (
            matches
            for tier in SUFFIX_SWAPS[suffix]
            if (
                matches := [
                    path for path in with_extensions(stem, tier) if path in paths
                ]
            )
        ),
        [],
    )


def resolved_targets(paths, base, ref):
    return tiered_targets(paths, base, ref) or swapped_targets(paths, base, ref)


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
        return resolved_targets(paths, parent, ref)
    if aliases is None or aliases.limitation:
        return []
    matches = [
        path
        for replacement in alias_replacements(aliases, ref)
        for path in resolved_targets(paths, aliases.root, replacement)
    ]
    if not matches and aliases.has_base_url:
        return resolved_targets(paths, aliases.root, ref)
    return matches


def python_bases(ancestors, project, dots):
    if dots:
        return [str(ancestors[dots - 1])]
    return dict.fromkeys(
        (project, posixpath.join(project, "src"), ".", "src", str(ancestors[0]))
    )


def python_targets(site, ref):
    dots = len(ref) - len(ref.lstrip("."))
    if dots > len(site.ancestors):
        return []
    bases = python_bases(site.ancestors, site.project, dots)
    tail = ref[dots:].replace(".", "/")
    matches = []
    for base in bases:
        resolved = posixpath.normpath(posixpath.join(base, tail))
        candidates = [posixpath.normpath(posixpath.join(resolved, "__init__.py"))]
        if tail:
            module = (
                resolved + ".py"
                if resolved + ".py" in site.paths
                else resolved + ".pyi"
            )
            candidates = [module, *candidates]
        matches.extend(path for path in candidates if path in site.paths)
    return matches


def style_targets(paths, parent, ref):
    base = "." if ref.startswith("/") else parent
    stripped = ref.removeprefix("/")
    matches = local_targets(paths, base, stripped, (".css", ".scss"))
    if not matches and not PLACEHOLDER.search(ref):
        directory, name = posixpath.split(stripped)
        return local_targets(
            paths, base, posixpath.join(directory, "_" + name), (".scss",)
        )
    return matches


def reference_targets(site, kind, ref):
    parent = str(site.ancestors[0])
    if kind == "js":
        return javascript_targets(site.paths, parent, ref, site.aliases)
    if kind in PYTHON_KINDS:
        return python_targets(site, ref)
    if kind == "style":
        return style_targets(site.paths, parent, ref)
    if PLACEHOLDER.search(ref):
        return []
    base = "." if ref.startswith("/") else parent
    if kind == "vue-external":
        return tiered_targets(site.paths, base, ref.lstrip("/"))
    return local_targets(site.paths, base, ref.lstrip("/"), ())


def member_module(ref):
    prefix = ref[: ref.rfind(".") + 1]
    return prefix if not prefix.strip(".") else prefix[:-1]


def is_symbol_of_resolved_module(site, import_kind, ref):
    return import_kind == "python-member" and bool(
        python_targets(site, member_module(ref))
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


def is_external_import(aliases, import_kind, ref):
    if import_kind in PYTHON_KINDS:
        return ref.split(".")[0] in sys.stdlib_module_names
    if import_kind != "js" or ref.startswith((".", "/")) or PLACEHOLDER.search(ref):
        return False
    if ref.startswith("node:") or aliases is None:
        return True
    return (
        not aliases.limitation
        and not aliases.has_base_url
        and not any(alias_replacements(aliases, ref))
    )


def unresolved_problem(site, import_kind, ref, targets):
    if targets:
        return "ambiguous"
    if is_symbol_of_resolved_module(site, import_kind, ref):
        return None
    if is_external_import(site.aliases, import_kind, ref):
        return EXTERNAL_PROBLEM
    return "unresolved or external"


def blocks_wiring(limits):
    return any(not limit.startswith(f"{EXTERNAL_PROBLEM} ") for limit in limits)


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
        entry = entries[path]
        site = ImportSite(
            paths, ancestors, entry["project"], nearest_aliases(ancestors, profiles)
        )
        limits = source_limitations(result, site.aliases, entry["language"])
        if limits:
            limitations[path].update(limits)
        for import_kind, ref in result["imports"]:
            kind = "python" if import_kind in PYTHON_KINDS else import_kind
            matches = set(reference_targets(site, import_kind, ref))
            if kind == "python":
                matches.discard(path)
            targets = sorted(matches)
            if len(targets) == 1:
                edges.add((path, targets[0], kind))
            else:
                problem = unresolved_problem(site, import_kind, ref, targets)
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
