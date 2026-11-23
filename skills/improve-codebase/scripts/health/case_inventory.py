import re

TEST_LANGUAGES = {"python", "typescript", "tsx", "javascript", "csharp"}
CASE_LIMIT = 100
NAME_LIMIT = 120
SKIP_DECORATOR = re.compile(r"skip|xfail")
PYTHON_INTERACTION = re.compile(
    r"assert_(?:not_)?(?:called|awaited|any_call|any_await|has_calls|has_awaits)\w*"
)
PYTHON_SKIP_CALLS = {"skip", "xfail", "skipTest"}
JS_SUITES = {"describe", "xdescribe", "fdescribe", "suite"}
JS_CASES = {"it", "xit", "fit", "test", "xtest", "specify", "xspecify"} | JS_SUITES
JS_SKIP_MODIFIERS = {"skip", "todo", "fixme"}
JS_INTERACTION = re.compile(
    r"^(?:toHaveBeen\w*|toBeCalled\w*|toHaveReturned\w*|toHaveLast\w*|toHaveNth\w*)$"
)
CSHARP_TEST_ATTRIBUTES = {
    "Fact",
    "Theory",
    "Test",
    "TestCase",
    "TestMethod",
    "DataTestMethod",
    "TestCaseSource",
}
CSHARP_INTERACTIONS = {
    "Received",
    "DidNotReceive",
    "ReceivedWithAnyArgs",
    "DidNotReceiveWithAnyArgs",
    "Verify",
    "VerifyAll",
    "VerifyNoOtherCalls",
    "VerifyGet",
    "VerifySet",
}


def node_text(data, node):
    return data[node.start_byte : node.end_byte].decode("utf-8", "replace")


def descendants(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.children)


def new_case(surface, node, name):
    return {
        "name": name[:NAME_LIMIT],
        "line": surface.location(node)["line"],
        "assertions": 0,
        "interactions": 0,
        "snapshots": 0,
        "skipped": False,
    }


def python_count(data, node, case):
    for item in descendants(node):
        kind = item.type
        if kind == "assert_statement":
            case["assertions"] += 1
        elif kind == "identifier" and "snapshot" in node_text(data, item).lower():
            case["snapshots"] += 1
        elif kind == "call":
            function = item.child_by_field_name("function")
            name = node_text(data, function) if function is not None else ""
            last = name.rsplit(".", 1)[-1]
            if last.lower().startswith("assert") or last in {"raises", "warns"}:
                case["assertions"] += 1
            if PYTHON_INTERACTION.fullmatch(last):
                case["interactions"] += 1
            if last in PYTHON_SKIP_CALLS:
                case["skipped"] = True


def python_cases(surface, root):
    data, cases = surface.data, []
    stack = [(root, False, False)]
    while stack:
        node, skipped, in_class = stack.pop()
        kind = node.type
        if kind in {"class_definition", "function_definition"}:
            name = node_text(data, node.child_by_field_name("name"))
            parent = node.parent
            decorators = (
                [
                    node_text(data, child)
                    for child in parent.children
                    if child.type == "decorator"
                ]
                if parent is not None and parent.type == "decorated_definition"
                else []
            )
            marked = skipped or any(SKIP_DECORATOR.search(d) for d in decorators)
            if kind == "class_definition":
                bases = node.child_by_field_name("superclasses")
                suite = name.startswith("Test") or (
                    bases is not None and "TestCase" in node_text(data, bases)
                )
                stack.append(
                    (node.child_by_field_name("body"), marked, suite or in_class)
                )
                continue
            if name.startswith("test_") or (in_class and name.startswith("test")):
                case = new_case(surface, node, name)
                case["skipped"] = marked
                python_count(data, node, case)
                cases.append(case)
                continue
        stack.extend((child, skipped, in_class) for child in reversed(node.children))
    return cases


def callee(data, call):
    modifiers, function = [], call.child_by_field_name("function")
    while function is not None:
        if function.type == "member_expression":
            modifiers.append(node_text(data, function.child_by_field_name("property")))
            function = function.child_by_field_name("object")
        elif function.type == "call_expression":
            function = function.child_by_field_name("function")
        elif function.type == "identifier":
            return node_text(data, function), modifiers[::-1]
        else:
            break
    return None, modifiers[::-1]


def js_count(data, node, case):
    for item in descendants(node):
        kind = item.type
        if kind == "member_expression":
            prop = node_text(data, item.child_by_field_name("property"))
            if prop == "should":
                case["assertions"] += 1
            if JS_INTERACTION.match(prop):
                case["interactions"] += 1
            if "Snapshot" in prop:
                case["snapshots"] += 1
        elif kind == "call_expression":
            function = item.child_by_field_name("function")
            if function is None:
                continue
            if function.type == "identifier":
                if node_text(data, function) in {"expect", "assert"}:
                    case["assertions"] += 1
            elif function.type == "member_expression":
                owner = function.child_by_field_name("object")
                prop = node_text(data, function.child_by_field_name("property"))
                if prop == "expect" or (
                    owner is not None
                    and owner.type == "identifier"
                    and node_text(data, owner) == "assert"
                ):
                    case["assertions"] += 1


def js_case_name(data, call):
    arguments = call.child_by_field_name("arguments")
    if arguments is None or arguments.type != "arguments":
        return None, None
    first = arguments.named_children[0] if arguments.named_child_count else None
    if first is None or first.type not in {"string", "template_string"}:
        return None, None
    return node_text(data, first).strip("`\"'"), arguments


def javascript_cases(surface, root):
    data, cases = surface.data, []
    stack = [(root, False)]
    while stack:
        node, skipped = stack.pop()
        if node.type == "call_expression":
            base, modifiers = callee(data, node)
            name, arguments = js_case_name(data, node)
            if base in JS_CASES and name is not None:
                marked = (
                    skipped
                    or base.startswith("x")
                    or bool(JS_SKIP_MODIFIERS & set(modifiers))
                )
                if base in JS_SUITES or "describe" in modifiers:
                    stack.extend(
                        (child, marked) for child in reversed(arguments.children)
                    )
                else:
                    case = new_case(surface, node, name)
                    case["skipped"] = marked
                    js_count(data, arguments, case)
                    cases.append(case)
                continue
        stack.extend((child, skipped) for child in reversed(node.children))
    return cases


def attribute_names(data, method):
    for child in method.children:
        if child.type == "attribute_list":
            for attribute in child.named_children:
                name = attribute.child_by_field_name("name")
                if name is not None:
                    label = node_text(data, name).rsplit(".", 1)[-1]
                    yield label.removesuffix("Attribute"), node_text(data, attribute)


def csharp_count(data, node, case):
    for item in descendants(node):
        kind = item.type
        if kind == "identifier" and "napshot" in node_text(data, item):
            case["snapshots"] += 1
        elif kind == "invocation_expression":
            function = item.child_by_field_name("function")
            if function is None:
                continue
            if function.type == "member_access_expression":
                owner = node_text(data, function.child_by_field_name("expression"))
                name = node_text(data, function.child_by_field_name("name"))
                if owner.endswith("Assert") or name.startswith("Should"):
                    case["assertions"] += 1
                elif name in CSHARP_INTERACTIONS and owner != "Verifier":
                    case["interactions"] += 1
                    case["assertions"] += 1
                if owner == "Verifier" and name == "Verify":
                    case["snapshots"] += 1
            elif (
                function.type == "identifier" and node_text(data, function) == "Verify"
            ):
                case["snapshots"] += 1


def csharp_cases(surface, root):
    data, cases = surface.data, []
    for node in descendants(root):
        if node.type != "method_declaration":
            continue
        attributes = list(attribute_names(data, node))
        if not any(name in CSHARP_TEST_ATTRIBUTES for name, _ in attributes):
            continue
        name = node_text(data, node.child_by_field_name("name"))
        case = new_case(surface, node, name)
        case["skipped"] = any(
            name in {"Ignore", "Skip"} or "Skip" in raw for name, raw in attributes
        )
        csharp_count(data, node, case)
        cases.append(case)
    return sorted(cases, key=lambda case: case["line"])


EXTRACTORS = {
    "python": python_cases,
    "typescript": javascript_cases,
    "tsx": javascript_cases,
    "javascript": javascript_cases,
    "csharp": csharp_cases,
}


def extract_test_cases(surface, root):
    return [
        [
            case["name"],
            case["line"],
            case["assertions"],
            case["interactions"],
            case["snapshots"],
            case["skipped"],
        ]
        for case in EXTRACTORS[surface.language](surface, root)
    ]


def case_flags(row):
    _, _, assertions, interactions, snapshots, skipped = row
    flags = []
    if not assertions:
        flags.append("no_assertion")
    if interactions > assertions - interactions:
        flags.append("interaction_heavy")
    if snapshots:
        flags.append("snapshot")
    if skipped:
        flags.append("skipped")
    return flags


def test_evidence(rows, language):
    counts = {"no_assertion": 0, "interaction_heavy": 0, "snapshot": 0, "skipped": 0}
    cases = []
    for row in rows:
        flags = case_flags(row)
        for flag in flags:
            counts[flag] += 1
        if len(cases) < CASE_LIMIT:
            cases.append({"name": row[0], "line": row[1], "flags": flags})
    evidence = {
        "tests": len(rows),
        "flags": counts,
        "cases": cases,
        "support": not rows and language in TEST_LANGUAGES,
    }
    if language not in TEST_LANGUAGES:
        evidence["unparsed"] = True
    return evidence


def test_signature(rows, language):
    return [
        language in TEST_LANGUAGES,
        sorted([row[0], case_flags(row)] for row in rows),
    ]
