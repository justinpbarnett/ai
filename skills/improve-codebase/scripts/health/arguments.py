import argparse
from pathlib import Path

from .diagnostics import FORMATS
from .review_units import AXES, STAGES


def options(parser):
    parser.add_argument(
        "--root", default=".", help="project directory (Git uses its worktree root)"
    )
    parser.add_argument(
        "--scope",
        action="append",
        help="repeatable worktree-relative path, defaults to all authored files",
    )
    parser.add_argument(
        "--state-dir",
        help="explicit state directory; default is <root>/.improve-codebase",
    )
    parser.add_argument("--run", help="resume a named run or slice in this worktree")
    parser.add_argument(
        "--thresholds",
        type=Path,
        help="local JSON overriding individual detector sensitivity thresholds",
    )
    parser.add_argument(
        "--format", choices=("text", "json"), default="text", help="output format"
    )


def register_scan_commands(sub):
    for cmd, description in {
        "doctor": "inspect capabilities and optional tool locations",
        "scan": "refresh inventory, use valid detector history, and queue new candidates",
        "status": "show debt, coverage, fresh evidence, and unmet gates",
        "next": "show the next safe phase and dependency-ready findings",
        "report": "show the inventory, findings, and history",
        "complete": "return 0 only if clean completion is currently evidenced",
    }.items():
        command = sub.add_parser(cmd, help=description)
        options(command)
        if cmd in {"doctor", "scan"}:
            command.add_argument(
                "--core-only", action="store_true", help="run without optional parsers"
            )
        if cmd != "doctor" and cmd != "report":
            command.add_argument(
                "--summary",
                action="store_true",
                help="omit detailed inventories and queues",
            )
        if cmd == "scan":
            command.add_argument(
                "--full", action="store_true", help="recompute every mechanical result"
            )
            command.add_argument(
                "--checkpoint",
                action="store_true",
                help="mark the end of one real investigation/fix cycle for stall detection",
            )
        if cmd in {"status", "next", "report", "complete"}:
            command.add_argument(
                "--target",
                type=int,
                default=0,
                help="report a debt target without changing clean completion",
            )


def register_run_commands(sub):
    runs = sub.add_parser(
        "run", help="save or list resumable worktree runs and slices"
    ).add_subparsers(dest="action", required=True)
    start = runs.add_parser(
        "start", help="name a scope and optionally derive it from a Git diff"
    )
    options(start)
    start.add_argument("name")
    start.add_argument("--base", help="Git base commit for fallout mode")
    start.add_argument(
        "--include",
        action="append",
        default=[],
        help="additional affected path for fallout mode",
    )
    view = runs.add_parser("slice", help="name a view of a parent run's backlog")
    options(view)
    view.add_argument("name")
    view.add_argument(
        "--path",
        action="append",
        required=True,
        help="path inside the parent scope; repeat as needed",
    )
    options(runs.add_parser("list", help="list the runs in this state directory"))


def register_review_commands(sub):
    review = sub.add_parser(
        "review", help="prepare score-blind packets or import review receipts"
    ).add_subparsers(dest="action", required=True)
    packet = review.add_parser(
        "prepare", help="create one bounded packet from the current scan"
    )
    options(packet)
    packet.add_argument("--axis", choices=AXES)
    packet.add_argument("--pass", dest="stage", choices=STAGES)
    packet.add_argument(
        "--unit",
        action="append",
        default=[],
        help="select this exact unit ID; repeat as needed",
    )
    packet.add_argument(
        "--path", action="append", help="select units touching a path; repeat as needed"
    )
    packet.add_argument(
        "--receipt-template",
        action="store_true",
        help="include an unfilled receipt in JSON output",
    )
    packet.add_argument(
        "--partition", help="filter to a project partition named in the report"
    )
    packet.add_argument(
        "--exclude-unit",
        action="append",
        default=[],
        help="skip an already delegated unit ID; repeat as needed",
    )
    packet.add_argument(
        "--limit", type=int, default=12, help="maximum assigned units (1–50)"
    )
    packet.add_argument(
        "--full",
        action="store_true",
        help="include already investigated units; use --exclude-unit to paginate",
    )
    receipt = review.add_parser(
        "import", help="record review coverage and findings atomically"
    )
    options(receipt)
    receipt.add_argument(
        "--input", type=Path, required=True, help="JSON response to a prepared packet"
    )


def register_evidence_commands(sub):
    for name, action, description in (
        ("finding", "update", "triage or transition a finding with evidence"),
        (
            "verification",
            "record",
            "record required checks and before/after observations",
        ),
    ):
        command = (
            sub.add_parser(name, help=description)
            .add_subparsers(dest="action", required=True)
            .add_parser(action)
        )
        options(command)
        command.add_argument(
            "--input",
            type=Path,
            required=True,
            help="JSON with revision and snapshot plus a single event or an atomic updates/records array",
        )
    importer = sub.add_parser(
        "import-diagnostics", help="import a local machine-readable diagnostic report"
    )
    options(importer)
    importer.add_argument("--tool", choices=FORMATS, required=True)
    importer.add_argument(
        "--input", type=Path, required=True, help="local tool JSON/SARIF output"
    )
    importer.add_argument(
        "--metadata",
        type=Path,
        required=True,
        help="JSON recording provenance, coverage, and tool exit status",
    )


def arguments(argv):
    parser = argparse.ArgumentParser(
        description="Investigate, track, and verify codebase improvements without rewriting source."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    register_scan_commands(sub)
    register_run_commands(sub)
    register_review_commands(sub)
    register_evidence_commands(sub)
    return parser.parse_args(argv)
