import re
from bisect import bisect_right
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from xml.etree import ElementTree

from .inventory import content_hash

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
CALLABLES = {
    "python": {"function_definition", "lambda"},
    "csharp": {
        "method_declaration",
        "constructor_declaration",
        "destructor_declaration",
        "operator_declaration",
        "conversion_operator_declaration",
        "local_function_statement",
        "lambda_expression",
        "anonymous_method_expression",
    },
    "javascript": {
        "function_declaration",
        "function_expression",
        "generator_function",
        "generator_function_declaration",
        "arrow_function",
        "method_definition",
    },
}
CALLABLES["typescript"] = CALLABLES["tsx"] = CALLABLES["javascript"]
CLASSES = {
    "class_definition",
    "class_declaration",
    "class",
    "struct_declaration",
    "interface_declaration",
    "record_declaration",
}
BRANCHES = {
    "python": {
        "if_statement",
        "elif_clause",
        "for_statement",
        "while_statement",
        "except_clause",
        "case_clause",
        "conditional_expression",
        "for_in_clause",
        "if_clause",
        "boolean_operator",
    },
    "csharp": {
        "if_statement",
        "for_statement",
        "for_each_statement",
        "while_statement",
        "do_statement",
        "catch_clause",
        "switch_section",
        "switch_expression_arm",
        "conditional_expression",
        "when_clause",
    },
    "javascript": {
        "if_statement",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "catch_clause",
        "switch_case",
        "ternary_expression",
    },
}
BRANCHES["typescript"] = BRANCHES["tsx"] = BRANCHES["javascript"]
HTML_ELEMENTS = {"element", "script_element", "style_element"}
HTML_ATTRIBUTES = re.compile(
    rb"([^\s=/>]+)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+)))?"
)
SELECTOR_TERMS = re.compile(rb"#[\w-]+|\.[\w-]+|\[[^\]]+\]|::?[\w-]+|[>+~]|\b[\w-]+\b")
PLACEHOLDER = re.compile(r"[$*{}<>]")


@lru_cache
def parser_for(language):
    try:
        from tree_sitter_language_pack import get_parser

        return get_parser(language), None
    except (ImportError, LookupError, ValueError, OSError, RuntimeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


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
        parser, limitation = (
            (None, "core-only requested") if core_only else parser_for(name)
        )
        grammars[name] = {
            "status": "supported" if parser else "unavailable",
            "reason": limitation,
        }
    return {"versions": versions, "grammars": grammars}


class Source:
    def __init__(self, data):
        self.data = data
        self.line_starts = [0, *(match.end() for match in re.finditer(b"\n", data))]

    def location(self, start, end):
        def point(offset):
            line = bisect_right(self.line_starts, offset)
            column = (
                len(
                    self.data[self.line_starts[line - 1] : offset].decode(
                        "utf-8", "replace"
                    )
                )
                + 1
            )
            if line == 1 and self.data.startswith(b"\xef\xbb\xbf") and offset >= 3:
                column -= 1
            return line, column

        line, column = point(start)
        end_line, end_column = point(end)
        return {
            "line": line,
            "column": column,
            "end_line": end_line,
            "end_column": end_column,
        }


def text(data, node):
    return data[node.start_byte : node.end_byte]


def attribute_values(data, node):
    values = {}
    for child in node.named_children:
        if child.type == "attribute" and (
            match := HTML_ATTRIBUTES.fullmatch(text(data, child))
        ):
            attr, *parts = match.groups()
            values[attr.decode("utf-8").lower()] = next(
                (p.decode("utf-8") for p in parts if p is not None), ""
            )
    return values


def literal(data, node):
    if node is None:
        return ""
    return text(data, node).decode("utf-8").strip().strip("\"'")


def local_web_path(value):
    if (
        not value
        or value.startswith(("#", "//"))
        or re.match(r"^[a-z][a-z0-9+.-]*:", value, re.I)
    ):
        return None
    return re.split(r"[?#]", value, maxsplit=1)[0]


def python_imports(data, node):
    module = node.child_by_field_name("module_name")
    names = node.children_by_field_name("name")
    if not module:
        return [
            literal(data, name.child_by_field_name("name") or name) for name in names
        ]
    module_name = literal(data, module)
    member_names = []
    if node.type == "import_from_statement":
        for name in names:
            member = literal(data, name.child_by_field_name("name") or name)
            if member and member != "*":
                member_names.append(
                    module_name + ("" if module_name.endswith(".") else ".") + member
                )
    return [module_name, *member_names]


def call_name(data, node):
    name = node.child_by_field_name("name")
    if (
        name is None
        and node.parent
        and node.parent.type in {"variable_declarator", "assignment", "pair"}
    ):
        name = (
            node.parent.child_by_field_name("name")
            or node.parent.child_by_field_name("left")
            or node.parent.child_by_field_name("key")
        )
    return literal(data, name) or node.type


def syntax(source, data, language, offset, label, result, core_only):
    parser, unavailable = (
        (None, "core-only requested") if core_only else parser_for(language)
    )
    if parser is None:
        result["gaps"].append(
            {"kind": "unavailable", "surface": label, "reason": unavailable}
        )
        return
    tree = parser.parse(data)
    if tree is None:
        result["gaps"].append(
            {
                "kind": "failed",
                "surface": label,
                "reason": "parser did not return a tree",
            }
        )
        return
    root = tree.root_node
    if root.has_error:
        result["gaps"].append(
            {
                "kind": "failed",
                "surface": label,
                "reason": "syntax tree contains error or missing nodes",
            }
        )
    if language == "vue":
        embedded_vue(source, data, root, result, core_only)
        return
    tokens, containers = [], []
    stack = [(root, (), None, 0, 0)]
    while stack:
        node, ancestry, enclosing, depth, markup_depth = stack.pop()
        kind = node.type
        if "comment" in kind:
            continue
        loc = None
        if node.is_error or node.is_missing:
            if (
                sum(
                    gap["kind"] == "syntax-error" and gap["surface"] == label
                    for gap in result["gaps"]
                )
                < 5
            ):
                result["gaps"].append(
                    {
                        "kind": "syntax-error",
                        "surface": label,
                        **source.location(
                            node.start_byte + offset, node.end_byte + offset
                        ),
                    }
                )
        if kind in CALLABLES.get(language, set()) or kind in CLASSES:
            name = call_name(data, node)
            anchor = f"{label}:" + ".".join((*ancestry, name))
            loc = source.location(node.start_byte + offset, node.end_byte + offset)
            params = node.child_by_field_name("parameters") or node.child_by_field_name(
                "parameter"
            )
            parameters = 0
            if params is not None:
                parameters = (
                    sum(
                        child.type
                        not in {"comment", "positional_separator", "keyword_separator"}
                        for child in params.named_children
                    )
                    if params.type.endswith(("parameters", "list"))
                    else 1
                )
            metric = {
                "anchor": anchor,
                "kind": "type" if kind in CLASSES else "callable",
                "language": language,
                **loc,
                "lines": loc["end_line"] - loc["line"] + 1,
                "evidence": content_hash(text(data, node)),
                "parameter_evidence": content_hash(text(data, params))
                if params
                else None,
                "parameters": parameters,
                "nesting": 0,
                "complexity": 1,
            }
            result["metrics"].append(metric)
            if metric["kind"] == "callable":
                enclosing, depth = metric, 0
            ancestry = (*ancestry, name)
        elif enclosing is not None:
            if kind in BRANCHES.get(language, set()):
                enclosing["complexity"] += 1
                if kind not in {
                    "boolean_operator",
                    "elif_clause",
                    "switch_section",
                    "switch_case",
                }:
                    depth += 1
                enclosing["nesting"] = max(enclosing["nesting"], depth)
            elif kind == "binary_expression" and any(
                c.type in {"&&", "||", "??"} for c in node.children
            ):
                enclosing["complexity"] += 1
        if language == "html" and kind in HTML_ELEMENTS:
            markup_depth += 1
            tag_node = next(
                (
                    child
                    for child in node.named_children
                    if child.type in {"start_tag", "self_closing_tag"}
                ),
                None,
            )
            if tag_node and tag_node.named_child_count:
                tag = literal(data, tag_node.named_children[0]).lower()
                attrs = attribute_values(data, tag_node)
                for key in (
                    {"src"}
                    if tag == "script"
                    else {"href"}
                    if tag == "link"
                    and "stylesheet" in attrs.get("rel", "").lower().split()
                    else set()
                ):
                    if ref := local_web_path(attrs.get(key)):
                        result["imports"].append(["web", ref])
                loc = source.location(node.start_byte + offset, node.end_byte + offset)
                metric = {
                    "anchor": f"{label}:<{tag}>",
                    "kind": "element",
                    "language": language,
                    **loc,
                    "lines": loc["end_line"] - loc["line"] + 1,
                    "nesting": markup_depth,
                    "size": node.descendant_count,
                    "evidence": content_hash(text(data, tag_node)),
                }
                result["metrics"].append(metric)
                if node.descendant_count >= 25:
                    # Use the already-tokenized stream for larger trees; bounded snippets also catch short exact subtrees.
                    if node.end_byte - node.start_byte <= 4096:
                        containers.append(
                            [
                                "html-subtree",
                                content_hash(text(data, node)),
                                metric,
                                node.descendant_count,
                            ]
                        )
        if language in {"css", "scss"} and kind == "rule_set":
            markup_depth += 1
            selectors = next(
                (c for c in node.named_children if c.type == "selectors"), None
            )
            block = next((c for c in node.named_children if c.type == "block"), None)
            declarations = (
                [text(data, c) for c in block.named_children if c.type == "declaration"]
                if block
                else []
            )
            selector = text(data, selectors) if selectors else b""
            terms = SELECTOR_TERMS.findall(selector)
            loc = source.location(node.start_byte + offset, node.end_byte + offset)
            metric = {
                "anchor": f"{label}:{selector.decode('utf-8')[:160]}",
                "kind": "rule",
                "language": language,
                **loc,
                "lines": loc["end_line"] - loc["line"] + 1,
                "size": len(declarations),
                "nesting": markup_depth,
                "selector_terms": len(terms),
                "evidence": content_hash(selector + b"\0" + b"\0".join(declarations)),
                "selector_ids": sum(term.startswith(b"#") for term in terms),
            }
            result["metrics"].append(metric)
            if len(declarations) >= 4:
                containers.append(
                    [
                        "css-declarations",
                        content_hash(b"\0".join(declarations)),
                        metric,
                        len(declarations),
                    ]
                )
        if language == "python" and kind in {
            "import_statement",
            "import_from_statement",
        }:
            result["imports"].extend(
                ["python", imp] for imp in python_imports(data, node) if imp
            )
        if language in {"typescript", "tsx", "javascript"}:
            if kind in {"import_statement", "export_statement"} and (
                ref := literal(data, node.child_by_field_name("source"))
            ):
                result["imports"].append(["js", ref])
            elif kind == "call_expression":
                func = literal(data, node.child_by_field_name("function"))
                if func in {"import", "require"}:
                    args = node.child_by_field_name("arguments")
                    if (
                        args
                        and args.named_child_count == 1
                        and args.named_children[0].type == "string"
                    ):
                        result["imports"].append(
                            ["js", literal(data, args.named_children[0])]
                        )
                    else:
                        result["limits"].append(f"{label}: dynamic {func} target")
        if language in {"css", "scss"} and kind in {
            "import_statement",
            "use_statement",
            "forward_statement",
        }:
            reference = re.search(
                rb"(?:url\(\s*['\"]?([^\s)'\"]+)|['\"]([^'\"]+)['\"])", text(data, node)
            )
            if reference and (
                ref := local_web_path((reference[1] or reference[2]).decode("utf-8"))
            ):
                result["imports"].append(["style", ref])
        if not node.child_count or kind in {
            "string",
            "string_literal",
            "interpolated_string_expression",
            "template_string",
            "raw_text",
            "text",
            "attribute_value",
            "quoted_attribute_value",
            "string_value",
        }:
            if node.end_byte > node.start_byte:
                tokens.append(
                    [
                        content_hash(text(data, node))[:24],
                        node.start_byte + offset,
                        node.end_byte + offset,
                    ]
                )
            continue  # Preserve complete literal values, including interpolations.
        stack.extend(
            (child, ancestry, enclosing, depth, markup_depth)
            for child in reversed(node.children)
        )
    if tokens:
        result["streams"].append([language, tokens])
    result["groups"].extend(containers)


def embedded_vue(source, data, root, result, core_only):
    for block in root.named_children:
        if block.type not in {"script_element", "style_element", "template_element"}:
            if block.type not in {"comment", "text"}:
                result["limits"].append(f"Vue custom block: {block.type}")
            elif block.type == "text" and text(data, block).strip():
                result["gaps"].append(
                    {
                        "kind": "unsupported",
                        "surface": "vue",
                        "reason": "unexpected top-level text",
                    }
                )
            continue
        opening = next(
            (
                c
                for c in block.named_children
                if c.type in {"start_tag", "self_closing_tag"}
            ),
            None,
        )
        closing = next((c for c in block.named_children if c.type == "end_tag"), None)
        if opening is None:
            continue
        attrs = attribute_values(data, opening)
        surface = block.type.removesuffix("_element")
        label = "script-setup" if surface == "script" and "setup" in attrs else surface
        start = opening.end_byte
        end = closing.start_byte if closing else block.end_byte
        if src := attrs.get("src"):
            if ref := local_web_path(src):
                result["imports"].append(["vue-external", ref])
            else:
                result["gaps"].append(
                    {
                        "kind": "unsupported",
                        "surface": label,
                        "reason": "nonlocal external Vue block",
                    }
                )
            continue
        langs = {
            "script": {
                "js": "javascript",
                "jsx": "javascript",
                "ts": "typescript",
                "tsx": "tsx",
            },
            "template": {"html": "html"},
            "style": {"css": "css", "scss": "scss"},
        }[surface]
        lang = langs.get(attrs.get("lang", next(iter(langs))).lower())
        if not lang:
            result["gaps"].append(
                {
                    "kind": "unsupported",
                    "surface": label,
                    "reason": f"unsupported Vue block language: {attrs['lang']}",
                }
            )
            continue
        if end > start:
            syntax(source, data[start:end], lang, start, label, result, core_only)


def project_references(data, result):
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", data, re.I):
        result["gaps"].append(
            {
                "kind": "unsupported",
                "surface": "msbuild",
                "reason": "DTD and entity declarations are not loaded",
            }
        )
        return
    try:
        tree = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        result["gaps"].append(
            {"kind": "failed", "surface": "msbuild", "reason": str(exc)}
        )
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


def analyze(data, language, core_only):
    result = {
        "metrics": [],
        "streams": [],
        "groups": [],
        "imports": [],
        "gaps": [],
        "limits": [],
    }
    source = Source(data)
    if language in GRAMMARS:
        syntax(source, data, language, 0, language, result, core_only)
    elif language == "msbuild":
        project_references(data, result)
    else:
        result["limits"].append("generic text only; semantic review required")
    if not result["streams"] and language != "msbuild":
        rows = []
        offset = 0
        for line in data.splitlines(keepends=True):
            value = line.rstrip(b"\r\n")
            if value.strip():
                rows.append([content_hash(value)[:24], offset, offset + len(value)])
            offset += len(line)
        if rows:
            result["streams"].append(["generic-lines", rows])
    result["limits"] = sorted(set(result["limits"]))
    result["imports"] = sorted({tuple(pair) for pair in result["imports"]})
    return result
