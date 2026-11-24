import ast
import sys
from pathlib import Path

from .hashing import content_hash, digest

PARSER_ENTRIES = ("parsers", "syntax_tree", "comments", "case_inventory")
DETECTOR_ENTRIES = ("detectors", "rules", "dependency_graph", "layout", "history")


def current_parser_profile(caps):
    return digest(
        [
            caps,
            sys.version_info[:3],
            *(module_hash(name) for name in sorted(import_closure(PARSER_ENTRIES))),
        ]
    )


def analyzer_profiles(thresholds, caps):
    parser = current_parser_profile(caps)
    detector_modules = import_closure(DETECTOR_ENTRIES) - import_closure(PARSER_ENTRIES)
    detector = digest(
        [
            parser,
            thresholds,
            *(module_hash(name) for name in sorted(detector_modules)),
        ]
    )
    return parser, detector


def import_closure(entries):
    seen = set()
    pending = list(entries)
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            pending.extend(relative_imports(name))
    return seen


def relative_imports(name):
    tree = ast.parse(module_path(name).read_bytes())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                imported.add(node.module)
            else:
                imported.update(alias.name for alias in node.names)
    return imported


def module_path(name):
    return Path(__file__).with_name(f"{name}.py")


def module_hash(name):
    return content_hash(module_path(name).read_bytes())
