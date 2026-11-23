import re
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from xml.etree import ElementTree

from .case_inventory import TEST_LANGUAGES, extract_test_cases
from .comments import finalize_comments
from .syntax_tree import (
    GENERIC_STREAM,
    Source,
    Surface,
    attribute_values,
    collect_tree,
    local_web_path,
    opening_tag,
    record_comment,
    text,
    token_row,
)

GRAMMARS = sorted(
    {
        "python",
        "csharp",
        "typescript",
        "tsx",
        "javascript",
        "vue",
        "html",
        "css",
        "scss",
    }
)
FONT_URL_TEMPLATE = re.compile(
    rb"(?<![\w-])(url\(data:font/woff2;base64,)(\{\{font:[\w.-]+\.woff2\}\})(?=\))"
)
VUE_LANGUAGES = {
    "script_element": {
        "js": "javascript",
        "jsx": "javascript",
        "ts": "typescript",
        "tsx": "tsx",
    },
    "template_element": {"html": "html"},
    "style_element": {"css": "css", "scss": "scss"},
}


@lru_cache
def parser_for(language):
    try:
        from tree_sitter_language_pack import get_parser

        return get_parser(language), None
    except (ImportError, LookupError, ValueError, OSError, RuntimeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def select_parser(language, core_only):
    return (None, "core-only requested") if core_only else parser_for(language)


def capabilities(core_only):
    versions = {}
    if not core_only:
        for package in (
            "tree-sitter",
            "tree-sitter-language-pack",
            "tree-sitter-c-sharp",
            "tree-sitter-yaml",
            "tree-sitter-embedded-template",
        ):
            try:
                versions[package] = version(package)
            except PackageNotFoundError:
                pass
    grammars = {}
    for name in GRAMMARS:
        parser, limitation = select_parser(name, core_only)
        grammars[name] = {
            "status": "supported" if parser else "unavailable",
            "reason": limitation,
        }
    return {"versions": versions, "grammars": grammars}


def blank_font_url_payloads(data):
    return FONT_URL_TEMPLATE.subn(lambda match: match[1] + b"A" * len(match[2]), data)


def parse_tree(parser, surface, limits):
    tree = parser.parse(surface.data)
    if surface.language != "css" or tree is None or not tree.root_node.has_error:
        return tree
    css, substitutions = blank_font_url_payloads(surface.data)
    if substitutions:
        tree = parser.parse(css)
        limits.append(f"{surface.label}: font URL placeholders parsed as base64")
    return tree


def add_gap(result, kind, label, reason):
    result["gaps"].append({"kind": kind, "surface": label, "reason": reason})


def syntax(surface, result, core_only):
    parser, unavailable = select_parser(surface.language, core_only)
    label = surface.label
    if parser is None:
        add_gap(result, "unavailable", label, unavailable)
        return
    tree = parse_tree(parser, surface, result["limits"])
    if tree is None:
        add_gap(result, "failed", label, "parser did not return a tree")
        return
    root = tree.root_node
    if root.has_error:
        add_gap(result, "failed", label, "syntax tree contains error or missing nodes")
    if surface.language == "vue":
        embedded_vue(surface, root, result, core_only)
    else:
        collect_tree(surface, root, result)
        if result["tests"] is not None and surface.language in TEST_LANGUAGES:
            result["tests"].extend(extract_test_cases(surface, root))


def vue_surface(parent, block, opening, attrs, label):
    langs = VUE_LANGUAGES[block.type]
    language = langs.get(attrs.get("lang", next(iter(langs))).lower())
    if not language:
        return None, f"unsupported Vue block language: {attrs['lang']}"
    closing = next((c for c in block.named_children if c.type == "end_tag"), None)
    start = opening.end_byte
    end = closing.start_byte if closing else block.end_byte
    if end <= start:
        return None, None
    return Surface(
        parent.source, parent.data[start:end], language, label, parent.offset + start
    ), None


def vue_block(parent, block, result):
    opening = opening_tag(block)
    if opening is None:
        return None
    attrs = attribute_values(parent.data, opening)
    surface = block.type.removesuffix("_element")
    label = "script-setup" if surface == "script" and "setup" in attrs else surface
    if src := attrs.get("src"):
        if ref := local_web_path(src):
            result["imports"].append(["vue-external", ref])
        else:
            add_gap(result, "unsupported", label, "nonlocal external Vue block")
        return None
    embedded, reason = vue_surface(parent, block, opening, attrs, label)
    if reason:
        add_gap(result, "unsupported", label, reason)
    return embedded


def embedded_vue(parent, root, result, core_only):
    for block in root.named_children:
        kind = block.type
        if kind in VUE_LANGUAGES:
            if embedded := vue_block(parent, block, result):
                syntax(embedded, result, core_only)
        elif kind == "text":
            if text(parent.data, block).strip():
                add_gap(result, "unsupported", "vue", "unexpected top-level text")
        elif kind == "comment":
            record_comment(parent, block, result)
        else:
            result["limits"].append(f"Vue custom block: {kind}")


def project_references(data, result):
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", data, re.I):
        add_gap(
            result,
            "unsupported",
            "msbuild",
            "DTD and entity declarations are not loaded",
        )
        return
    try:
        tree = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        add_gap(result, "failed", "msbuild", str(exc))
        return
    for node in tree.iter():
        if node.tag.rpartition("}")[-1] == "ProjectReference" and (
            ref := node.get("Include")
        ):
            result["imports"].append(["project", ref.replace("\\", "/")])
            if node.get("Condition"):
                result["limits"].append(
                    "conditional ProjectReference (condition not evaluated)"
                )


def analyze(data, language, core_only, test_file=False):
    result = {
        "metrics": [],
        "streams": [],
        "groups": [],
        "imports": [],
        "gaps": [],
        "limits": [],
        "comments": [],
        "tests": [] if test_file else None,
    }
    source = Source(data)
    if language in GRAMMARS:
        syntax(Surface(source, data, language, language), result, core_only)
    elif language == "msbuild":
        project_references(data, result)
    else:
        result["limits"].append("generic text only; semantic review required")
    result["comments"] = finalize_comments(
        source,
        data,
        result["comments"],
        lambda name: select_parser(name, core_only)[0],
    )
    if not result["streams"] and language != "msbuild":
        rows = []
        offset = 0
        for line in data.splitlines(keepends=True):
            value = line.rstrip(b"\r\n")
            if value.strip():
                rows.append(token_row(value, offset, offset + len(value)))
            offset += len(line)
        if rows:
            result["streams"].append([GENERIC_STREAM, rows])
    result["limits"] = sorted(set(result["limits"]))
    result["imports"] = sorted({tuple(pair) for pair in result["imports"]})
    return result
