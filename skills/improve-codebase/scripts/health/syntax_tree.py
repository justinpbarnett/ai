import re
from bisect import bisect_right
from dataclasses import dataclass

from .inventory import content_hash

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
FLAT_BRANCHES = {"boolean_operator", "elif_clause", "switch_section", "switch_case"}
HTML_ELEMENTS = {"element", "script_element", "style_element"}
HTML_ATTRIBUTES = re.compile(
    rb"([^\s=/>]+)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+)))?"
)
SELECTOR_TERMS = re.compile(rb"#[\w-]+|\.[\w-]+|\[[^\]]+\]|::?[\w-]+|[>+~]|\b[\w-]+")
STYLE_IMPORT = re.compile(rb"(?:url\(\s*['\"]?([^\s)'\"]+)|['\"]([^'\"]+)['\"])")
OPAQUE_TOKENS = {
    "string",
    "string_literal",
    "interpolated_string_expression",
    "template_string",
    "raw_text",
    "text",
    "attribute_value",
    "quoted_attribute_value",
    "string_value",
}


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


@dataclass(frozen=True)
class Surface:
    source: Source
    data: bytes
    language: str
    label: str
    offset: int = 0

    def location(self, node):
        return self.source.location(
            node.start_byte + self.offset, node.end_byte + self.offset
        )


def text(data, node):
    return data[node.start_byte : node.end_byte]


def opening_tag(node):
    return next(
        (
            child
            for child in node.named_children
            if child.type in {"start_tag", "self_closing_tag"}
        ),
        None,
    )


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


def parameter_count(params):
    if params is None:
        return 0
    if not params.type.endswith(("parameters", "list")):
        return 1
    return sum(
        child.type not in {"comment", "positional_separator", "keyword_separator"}
        for child in params.named_children
    )


def declaration_metric(surface, node, ancestry):
    loc = surface.location(node)
    params = node.child_by_field_name("parameters") or node.child_by_field_name(
        "parameter"
    )
    return {
        "anchor": f"{surface.label}:" + ".".join(ancestry),
        "kind": "type" if node.type in CLASSES else "callable",
        "language": surface.language,
        **loc,
        "lines": loc["end_line"] - loc["line"] + 1,
        "evidence": content_hash(text(surface.data, node)),
        "parameter_evidence": content_hash(text(surface.data, params))
        if params
        else None,
        "parameters": parameter_count(params),
        "nesting": 0,
        "complexity": 1,
    }


def count_branch(node, branches, enclosing, depth):
    if enclosing is None:
        return depth
    kind = node.type
    if kind in branches:
        enclosing["complexity"] += 1
        if kind not in FLAT_BRANCHES:
            depth += 1
        enclosing["nesting"] = max(enclosing["nesting"], depth)
    elif kind == "binary_expression" and any(
        child.type in {"&&", "||", "??"} for child in node.children
    ):
        enclosing["complexity"] += 1
    return depth


def html_resource(tag, attrs):
    if tag == "script":
        return local_web_path(attrs.get("src"))
    if tag == "link" and "stylesheet" in attrs.get("rel", "").lower().split():
        return local_web_path(attrs.get("href"))


def collect_html(surface, node, depth, result):
    tag_node = opening_tag(node)
    if tag_node is None or not tag_node.named_child_count:
        return
    data = surface.data
    tag = literal(data, tag_node.named_children[0]).lower()
    if ref := html_resource(tag, attribute_values(data, tag_node)):
        result["imports"].append(["web", ref])
    loc = surface.location(node)
    descendants = node.descendant_count
    metric = {
        "anchor": f"{surface.label}:<{tag}>",
        "kind": "element",
        "language": surface.language,
        **loc,
        "lines": loc["end_line"] - loc["line"] + 1,
        "nesting": depth,
        "size": descendants,
        "evidence": content_hash(text(data, tag_node)),
    }
    result["metrics"].append(metric)
    # Larger trees are already covered by the token stream.
    if descendants >= 25 and node.end_byte - node.start_byte <= 4096:
        result["groups"].append(
            ["html-subtree", content_hash(text(data, node)), metric, descendants]
        )


def collect_style(surface, node, depth, result):
    data = surface.data
    selectors = next((c for c in node.named_children if c.type == "selectors"), None)
    block = next((c for c in node.named_children if c.type == "block"), None)
    declarations = (
        [text(data, c) for c in block.named_children if c.type == "declaration"]
        if block
        else []
    )
    selector = text(data, selectors) if selectors else b""
    terms = SELECTOR_TERMS.findall(selector)
    joined = b"\0".join(declarations)
    loc = surface.location(node)
    metric = {
        "anchor": f"{surface.label}:{selector.decode('utf-8')[:160]}",
        "kind": "rule",
        "language": surface.language,
        **loc,
        "lines": loc["end_line"] - loc["line"] + 1,
        "size": len(declarations),
        "nesting": depth,
        "selector_terms": len(terms),
        "evidence": content_hash(selector + b"\0" + joined),
        "selector_ids": sum(term.startswith(b"#") for term in terms),
    }
    result["metrics"].append(metric)
    if len(declarations) >= 4:
        result["groups"].append(
            ["css-declarations", content_hash(joined), metric, len(declarations)]
        )


def collect_js_import(surface, node, result):
    data = surface.data
    if node.type in {"import_statement", "export_statement"}:
        if ref := literal(data, node.child_by_field_name("source")):
            result["imports"].append(["js", ref])
        return
    if node.type != "call_expression":
        return
    func = literal(data, node.child_by_field_name("function"))
    if func not in {"import", "require"}:
        return
    args = node.child_by_field_name("arguments")
    if args and args.named_child_count == 1 and args.named_children[0].type == "string":
        result["imports"].append(["js", literal(data, args.named_children[0])])
    else:
        result["limits"].append(f"{surface.label}: dynamic {func} target")


def collect_style_import(surface, node, result):
    reference = STYLE_IMPORT.search(text(surface.data, node))
    if reference and (
        ref := local_web_path((reference[1] or reference[2]).decode("utf-8"))
    ):
        result["imports"].append(["style", ref])


def collect_import(surface, node, result):
    language, kind = surface.language, node.type
    if language == "python" and kind in {"import_statement", "import_from_statement"}:
        result["imports"].extend(
            ["python", ref] for ref in python_imports(surface.data, node) if ref
        )
    elif language in {"typescript", "tsx", "javascript"}:
        collect_js_import(surface, node, result)
    elif language in {"css", "scss"} and kind in {
        "import_statement",
        "use_statement",
        "forward_statement",
    }:
        collect_style_import(surface, node, result)


def collect_markup(surface, node, depth, result):
    if surface.language == "html" and node.type in HTML_ELEMENTS:
        collect_html(surface, node, depth + 1, result)
        return depth + 1
    if surface.language in {"css", "scss"} and node.type == "rule_set":
        collect_style(surface, node, depth + 1, result)
        return depth + 1
    return depth


def tokenize_terminal(surface, node, tokens):
    if node.child_count and node.type not in OPAQUE_TOKENS:
        return False
    if node.end_byte > node.start_byte:
        tokens.append(
            [
                content_hash(text(surface.data, node))[:24],
                node.start_byte + surface.offset,
                node.end_byte + surface.offset,
            ]
        )
    return True


def collect_tree(surface, root, result):
    label, language = surface.label, surface.language
    callables = CALLABLES.get(language, ())
    branches = BRANCHES.get(language, ())
    errors = sum(
        gap["kind"] == "syntax-error" and gap["surface"] == label
        for gap in result["gaps"]
    )
    tokens = []
    stack = [(root, (), None, 0, 0)]
    while stack:
        node, ancestry, enclosing, depth, markup_depth = stack.pop()
        kind = node.type
        if "comment" in kind:
            continue
        if errors < 5 and (node.is_error or node.is_missing):
            result["gaps"].append(
                {"kind": "syntax-error", "surface": label, **surface.location(node)}
            )
            errors += 1
        if kind in callables or kind in CLASSES:
            ancestry = (*ancestry, call_name(surface.data, node))
            metric = declaration_metric(surface, node, ancestry)
            result["metrics"].append(metric)
            if metric["kind"] == "callable":
                enclosing, depth = metric, 0
        else:
            depth = count_branch(node, branches, enclosing, depth)
        markup_depth = collect_markup(surface, node, markup_depth, result)
        collect_import(surface, node, result)
        if tokenize_terminal(surface, node, tokens):
            continue  # Preserve complete literal values, including interpolations.
        stack.extend(
            (child, ancestry, enclosing, depth, markup_depth)
            for child in reversed(node.children)
        )
    if tokens:
        result["streams"].append([language, tokens])
