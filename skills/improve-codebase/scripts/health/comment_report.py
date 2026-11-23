from collections import Counter

KEPT_CLASSES = ("directive", "legal")
LOCATION_LIMIT = 50


def comment_evidence(rows):
    removable = [row for row in rows if row[1] not in KEPT_CLASSES]
    locations = []
    for line, label, lines, _ in removable[:LOCATION_LIMIT]:
        entry = {"line": line, "class": label}
        if lines > 1:
            entry["lines"] = lines
        locations.append(entry)
    return {
        "removable": len(removable),
        "by_class": dict(sorted(Counter(row[1] for row in removable).items())),
        "kept": dict(
            sorted(Counter(row[1] for row in rows if row[1] in KEPT_CLASSES).items())
        ),
        "locations": locations,
    }


def comment_signature(rows):
    return sorted([row[1], row[3]] for row in rows if row[1] not in KEPT_CLASSES)
