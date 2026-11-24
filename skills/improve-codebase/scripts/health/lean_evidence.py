from collections import Counter

from .case_inventory import TEST_LANGUAGES

CASE_LIMIT = 100
KEPT_CLASSES = ("directive", "legal")
LOCATION_LIMIT = 50


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


def test_evidence(rows, language, parse_gapped):
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
        "support": not rows and language in TEST_LANGUAGES and not parse_gapped,
    }
    if len(cases) < len(rows):
        evidence["cases_shown"] = len(cases)
    if language not in TEST_LANGUAGES or (not rows and parse_gapped):
        evidence["unparsed"] = True
    return evidence


def test_signature(rows, language, parse_gapped):
    return [
        language in TEST_LANGUAGES and (bool(rows) or not parse_gapped),
        sorted([row[0], case_flags(row)] for row in rows),
    ]


def comment_evidence(rows):
    removable = [row for row in rows if row[1] not in KEPT_CLASSES]
    locations = []
    for line, label, lines, _ in removable[:LOCATION_LIMIT]:
        entry = {"line": line, "class": label}
        if lines > 1:
            entry["lines"] = lines
        locations.append(entry)
    evidence = {
        "removable": len(removable),
        "by_class": dict(sorted(Counter(row[1] for row in removable).items())),
        "kept": dict(
            sorted(Counter(row[1] for row in rows if row[1] in KEPT_CLASSES).items())
        ),
        "locations": locations,
    }
    if len(locations) < len(removable):
        evidence["locations_shown"] = len(locations)
    return evidence


def comment_signature(rows):
    return sorted([row[1], row[3]] for row in rows if row[1] not in KEPT_CLASSES)
