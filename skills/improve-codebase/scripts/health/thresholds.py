LEDGER_NEUTRAL_DEFAULTS = {
    "comments": 1,
    "folder_files": 30,
    "coupling_revisions": 5,
    "coupling_degree": 50,
}
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
DEFAULTS |= LEDGER_NEUTRAL_DEFAULTS
MINIMUMS = {"duplicate_tokens": 50, "duplicate_lines": 8}
MAXIMUMS = {"coupling_degree": 100}


def ledger_thresholds(thresholds):
    return {
        name: value
        for name, value in thresholds.items()
        if LEDGER_NEUTRAL_DEFAULTS.get(name) != value
    }


def settings(document):
    if not isinstance(document, dict) or document.keys() - DEFAULTS.keys():
        raise ValueError(
            "thresholds must be an object containing only supported detector names"
        )
    for name, value in document.items():
        minimum, maximum = MINIMUMS.get(name, 1), MAXIMUMS.get(name, 10000)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(
                f"{name} requires an integer between {minimum} and {maximum}"
            )
    return DEFAULTS | document
