import re

NAME_LIMIT = 120
SKIP_DECORATOR = re.compile(r"@\s*(?:[\w.]+\.)?(?:skip|xfail)\b(?!\w)")
PYTHON_INTERACTION = re.compile(
    r"assert_(?:not_)?(?:called|awaited|any_call|any_await|has_calls|has_awaits)\w*"
)
PYTHON_SKIP_CALLS = {"skip", "xfail", "pytest.skip", "pytest.xfail", "self.skipTest"}
PYTHON_SNAPSHOT_FIXTURE = "snapshot"
PYTHON_SNAPSHOT_CALL = re.compile(r"assert_?match_?snapshot", re.I)
JS_SUITES = {"describe", "xdescribe", "fdescribe", "suite"}
JS_CASES = {"it", "xit", "fit", "test", "xtest", "specify", "xspecify"} | JS_SUITES
JS_SKIP_MODIFIERS = {"skip", "todo", "fixme"}
JS_SNAPSHOT_MATCHER = re.compile(
    r"^(?:to(?:Match|ThrowErrorMatching)(?:Inline|File|Image)?Snapshot|matchSnapshot)$"
)
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
CSHARP_SKIP_ATTRIBUTES = {"Ignore", "Skip"}
CSHARP_ROW_ATTRIBUTES = {"TestCase", "InlineData", "DataRow", "TestFixture"}
CSHARP_SKIP_ARGUMENTS = {"Skip", "Ignore", "IgnoreReason"}
CSHARP_SKIPPABLE_DECLARATIONS = {
    "method_declaration",
    "class_declaration",
    "record_declaration",
    "struct_declaration",
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


def count_python_call(data, call, case, unconditional):
    function = call.child_by_field_name("function")
    name = node_text(data, function) if function is not None else ""
    last = name.rsplit(".", 1)[-1]
    if last.lower().startswith("assert") or last in {"raises", "warns"}:
        case["assertions"] += 1
    if PYTHON_INTERACTION.fullmatch(last):
        case["interactions"] += 1
    if unconditional and name in PYTHON_SKIP_CALLS:
        case["skipped"] = True
    if PYTHON_SNAPSHOT_CALL.fullmatch(last):
        case["snapshots"] += 1


def parameter_name(data, parameter):
    if parameter.type == "identifier":
        return node_text(data, parameter)
    first = parameter.named_children[0] if parameter.named_child_count else None
    return node_text(data, first) if first is not None else None


def takes_snapshot_fixture(data, function):
    parameters = function.child_by_field_name("parameters")
    return parameters is not None and any(
        parameter_name(data, parameter) == PYTHON_SNAPSHOT_FIXTURE
        for parameter in parameters.named_children
    )


def unconditional_calls(body):
    return {
        statement.id for statement in body.named_children if statement.type == "call"
    }


def python_count(data, node, case):
    body = node.child_by_field_name("body")
    unconditional = unconditional_calls(body)
    fixture = takes_snapshot_fixture(data, node)
    for item in descendants(node):
        kind = item.type
        if kind == "assert_statement":
            case["assertions"] += 1
        elif (
            fixture
            and kind == "identifier"
            and item.start_byte >= body.start_byte
            and node_text(data, item) == PYTHON_SNAPSHOT_FIXTURE
        ):
            case["snapshots"] += 1
        elif kind == "call":
            count_python_call(data, item, case, item.id in unconditional)


def definition_decorators(data, node):
    parent = node.parent
    if parent is None or parent.type != "decorated_definition":
        return []
    return [
        node_text(data, child) for child in parent.children if child.type == "decorator"
    ]


def is_test_class(data, node, name):
    bases = node.child_by_field_name("superclasses")
    return name.startswith("Test") or (
        bases is not None and "TestCase" in node_text(data, bases)
    )


def base_names(data, node):
    bases = node.child_by_field_name("superclasses")
    if bases is None:
        return []
    names = []
    for base in bases.named_children:
        if base.type in {"keyword_argument", "dictionary_splat"}:
            continue
        if base.type == "subscript":
            base = base.child_by_field_name("value")
        names.append(node_text(data, base))
    return names


def inherits_suite(data, node, module_suites):
    return any(
        module_suites.get(base, base != "object") for base in base_names(data, node)
    )


def is_test_function(name, in_class):
    return name.startswith("test_") or (in_class and name.startswith("test"))


IMPORT_NODES = {"import_statement", "import_from_statement"}


def imported_names(data, node):
    names = []
    for item in node.children_by_field_name("name"):
        if item.type == "aliased_import":
            names.append(node_text(data, item.child_by_field_name("alias")))
        else:
            names.append(node_text(data, item).split(".")[0])
    return names


def class_body_entry(data, node, name, marked, scope, module_suites):
    collected = scope != "other" and (
        is_test_class(data, node, name) or inherits_suite(data, node, module_suites)
    )
    if scope == "module":
        module_suites[name] = module_suites.get(name, False) or collected
    return (
        node.child_by_field_name("body"),
        marked,
        "suite" if collected else "other",
    )


def python_cases(surface, root):
    data, cases, module_suites = surface.data, [], {}
    stack = [(root, False, "module")]
    while stack:
        node, skipped, scope = stack.pop()
        kind = node.type
        if kind in {"class_definition", "function_definition"}:
            name = node_text(data, node.child_by_field_name("name"))
            decorators = definition_decorators(data, node)
            marked = skipped or any(SKIP_DECORATOR.match(d) for d in decorators)
            if kind == "class_definition":
                stack.append(
                    class_body_entry(data, node, name, marked, scope, module_suites)
                )
            elif scope != "other" and is_test_function(name, scope == "suite"):
                case = new_case(surface, node, name)
                case["skipped"] = marked
                python_count(data, node, case)
                cases.append(case)
            continue
        if scope == "module" and kind in IMPORT_NODES:
            module_suites.update(dict.fromkeys(imported_names(data, node), True))
            continue
        stack.extend((child, skipped, scope) for child in reversed(node.children))
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


def count_js_member(data, member, case):
    prop = node_text(data, member.child_by_field_name("property"))
    if prop == "should":
        case["assertions"] += 1
    if JS_INTERACTION.match(prop):
        case["interactions"] += 1
    if JS_SNAPSHOT_MATCHER.match(prop):
        case["snapshots"] += 1


def is_js_assertion_call(data, function):
    if function.type == "identifier":
        return node_text(data, function) in {"expect", "assert"}
    if function.type != "member_expression":
        return False
    owner = function.child_by_field_name("object")
    prop = node_text(data, function.child_by_field_name("property"))
    if owner is not None and owner.type == "identifier":
        owner_name = node_text(data, owner)
        if owner_name == "assert" or (
            owner_name == "expect" and prop in {"soft", "poll"}
        ):
            return True
    return prop == "expect"


def js_count(data, node, case):
    for item in descendants(node):
        kind = item.type
        if kind == "member_expression":
            count_js_member(data, item, case)
        elif kind == "call_expression":
            function = item.child_by_field_name("function")
            if function is not None and is_js_assertion_call(data, function):
                case["assertions"] += 1


def js_case_name(data, call):
    arguments = call.child_by_field_name("arguments")
    if arguments is None or arguments.type != "arguments":
        return None, None
    first = arguments.named_children[0] if arguments.named_child_count else None
    if first is None or first.type not in {"string", "template_string"}:
        return None, None
    return node_text(data, first).strip("`\"'"), arguments


def is_skipped_js_case(base, modifiers, skipped):
    return skipped or base.startswith("x") or bool(JS_SKIP_MODIFIERS & set(modifiers))


def classify_js_call(data, call, skipped):
    base, modifiers = callee(data, call)
    name, arguments = js_case_name(data, call)
    if base not in JS_CASES or name is None:
        return None
    marked = is_skipped_js_case(base, modifiers, skipped)
    return name, arguments, marked, base in JS_SUITES or "describe" in modifiers


def javascript_cases(surface, root):
    data, cases = surface.data, []
    stack = [(root, False)]
    while stack:
        node, skipped = stack.pop()
        found = (
            classify_js_call(data, node, skipped)
            if node.type == "call_expression"
            else None
        )
        if found is None:
            stack.extend((child, skipped) for child in reversed(node.children))
            continue
        name, arguments, marked, is_suite = found
        if is_suite:
            stack.extend((child, marked) for child in reversed(arguments.children))
            continue
        case = new_case(surface, node, name)
        case["skipped"] = marked
        js_count(data, arguments, case)
        cases.append(case)
    return cases


def attribute_names(data, method):
    for child in method.children:
        if child.type == "attribute_list":
            for attribute in child.named_children:
                name = attribute.child_by_field_name("name")
                if name is not None:
                    label = node_text(data, name).rsplit(".", 1)[-1]
                    yield label.removesuffix("Attribute"), attribute


def skip_argument(data, attribute):
    return any(
        argument.type == "attribute_argument"
        and argument.named_children
        and argument.named_children[0].type == "identifier"
        and node_text(data, argument.named_children[0]) in CSHARP_SKIP_ARGUMENTS
        and argument.named_child_count > 1
        for argument in descendants(attribute)
    )


def last_segment(owner):
    return owner.rsplit(".", 1)[-1]


def is_csharp_snapshot_call(owner, name):
    owner = last_segment(owner)
    return (
        (owner == "Verifier" and name == "Verify")
        or (owner == "Snapshot" and name.startswith("Match"))
        or name == "MatchSnapshot"
    )


def csharp_count(data, node, case):
    for item in descendants(node):
        kind = item.type
        if kind == "invocation_expression":
            function = item.child_by_field_name("function")
            if function is None:
                continue
            if function.type == "member_access_expression":
                owner = node_text(data, function.child_by_field_name("expression"))
                name = node_text(data, function.child_by_field_name("name"))
                if owner.endswith("Assert") or name.startswith("Should"):
                    case["assertions"] += 1
                elif name in CSHARP_INTERACTIONS and last_segment(owner) != "Verifier":
                    case["interactions"] += 1
                    case["assertions"] += 1
                if is_csharp_snapshot_call(owner, name):
                    case["snapshots"] += 1
            elif (
                function.type == "identifier" and node_text(data, function) == "Verify"
            ):
                case["snapshots"] += 1


def has_skip(data, node):
    rows, others = [], []
    for name, attribute in attribute_names(data, node):
        if name in CSHARP_SKIP_ATTRIBUTES:
            return True
        (rows if name in CSHARP_ROW_ATTRIBUTES else others).append(attribute)
    return any(skip_argument(data, attribute) for attribute in others) or (
        bool(rows) and all(skip_argument(data, attribute) for attribute in rows)
    )


def csharp_skipped(data, node):
    while node is not None:
        if node.type in CSHARP_SKIPPABLE_DECLARATIONS and has_skip(data, node):
            return True
        node = node.parent
    return False


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
        case["skipped"] = csharp_skipped(data, node)
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
TEST_LANGUAGES = frozenset(EXTRACTORS) | {"vue"}


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
