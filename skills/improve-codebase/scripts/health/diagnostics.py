import re
from collections import Counter
from functools import partial
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .hashing import digest
from .inventory import read_source, safe_file
from .ledger import observe
from .rules import EXIT_CODES
from .validation import array, object_value, read_json, require, string

SOURCE_NEWLINE = re.compile(r"\r\n|\n|\r")


def coordinates(line, column, end_line=None, end_column=None):
    parts = {
        "line": line,
        "column": column,
        "end_line": end_line,
        "end_column": end_column,
    }
    result = {name: value for name, value in parts.items() if value is not None}
    require(
        all(type(value) is int and value > 0 for value in result.values()),
        "invalid diagnostic source range",
    )
    require(
        "line" in result
        and "column" in result
        and result.get("end_line", line) >= line,
        "diagnostic needs a valid source location",
    )
    return result


def ruff_rows(report):
    require(isinstance(report, list), "Ruff report must be an array")
    for item in report:
        obj = object_value(item, "Ruff diagnostic")
        code = string(obj, "code")
        require(
            code not in {"invalid-syntax", "E999", "E902"},
            f"Ruff could not check a declared file ({code})",
        )
        location = object_value(obj.get("location"), "Ruff location")
        end = object_value(obj.get("end_location", {}), "Ruff end_location")
        yield (
            string(obj, "filename"),
            code,
            string(obj, "message"),
            "unspecified",
            coordinates(
                location.get("row"),
                location.get("column"),
                end.get("row"),
                end.get("column"),
            ),
        )


ESLINT_UNATTRIBUTED_RULE = "eslint:unattributed"


def located_without_rule(message):
    return message.get("ruleId") is None and type(message.get("line")) is int


def diagnostic_rule(obj, tool):
    if tool == "eslint" and located_without_rule(obj):
        return ESLINT_UNATTRIBUTED_RULE
    return string(obj, "ruleId" if tool == "eslint" else "rule")


def js_rows(report, tool):
    require(isinstance(report, list), f"{tool} report must be an array")
    for item in report:
        entry = object_value(item, "report file")
        path = string(entry, "filePath" if tool == "eslint" else "source")
        if tool == "stylelint":
            require(
                not entry.get("invalidOptionWarnings")
                and not entry.get("parseErrors")
                and not entry.get("ignored"),
                "Stylelint skipped a file or reported invalid options or parse errors",
            )
        else:
            require(not entry.get("fatalErrorCount"), "ESLint reported a fatal error")
        for raw in array(entry, "messages" if tool == "eslint" else "warnings"):
            obj = object_value(raw, "diagnostic")
            require(not obj.get("fatal"), f"{tool} reported a fatal diagnostic")
            rule = diagnostic_rule(obj, tool)
            severity = obj.get("severity")
            require(
                (tool == "eslint" and type(severity) is int and severity in {1, 2})
                or (tool == "stylelint" and severity in ("warning", "error")),
                "unknown diagnostic severity",
            )
            message = string(obj, "message" if tool == "eslint" else "text")
            yield (
                path,
                rule,
                message,
                {1: "warning", 2: "error"}.get(severity, severity),
                coordinates(
                    obj.get("line"),
                    obj.get("column"),
                    obj.get("endLine"),
                    obj.get("endColumn"),
                ),
            )


def sarif_rows(report):
    require(
        isinstance(report, dict) and report.get("version") == "2.1.0",
        "expected SARIF 2.1.0",
    )
    runs = array(report, "runs")
    require(runs, "SARIF report needs at least one run")
    for value in runs:
        run = object_value(value, "SARIF run")
        string(
            object_value(
                object_value(run.get("tool"), "SARIF tool").get("driver"),
                "SARIF driver",
            ),
            "name",
        )
        for invocation in run.get("invocations", []):
            require(
                object_value(invocation, "SARIF invocation").get("executionSuccessful")
                is True,
                "SARIF tool execution was not successful",
            )
        for value in array(run, "results"):
            item = object_value(value, "SARIF result")
            locations = array(item, "locations")
            require(locations, "SARIF result has no physical location")
            physical = object_value(
                object_value(locations[0], "SARIF location").get("physicalLocation"),
                "SARIF physicalLocation",
            )
            artifact = object_value(
                physical.get("artifactLocation"), "SARIF artifactLocation"
            )
            require(
                not artifact.get("uriBaseId"),
                "SARIF uriBaseId indirection is not supported; export explicit local paths",
            )
            uri = urlsplit(string(artifact, "uri"))
            require(
                uri.scheme in {"", "file"}
                and uri.netloc in {"", "localhost"}
                and not uri.query
                and not uri.fragment,
                "SARIF locations must use local file paths",
            )
            region = object_value(physical.get("region"), "SARIF region")
            yield (
                unquote(uri.path),
                string(item, "ruleId"),
                string(object_value(item.get("message"), "SARIF message"), "text"),
                item.get("level", "warning"),
                coordinates(
                    region.get("startLine"),
                    region.get("startColumn", 1),
                    region.get("endLine"),
                    region.get("endColumn"),
                ),
            )


def relative_path(value, cwd, root, entries):
    candidate = Path(value)
    path = (cwd / candidate).absolute()
    require(
        path.resolve() == path and path.is_relative_to(root),
        f"diagnostic path is not a direct local source: {value!r}",
    )
    relative = path.relative_to(root).as_posix()
    require(
        entries.get(relative, {}).get("disposition") == "source",
        f"diagnostic path is outside inventoried scope: {relative!r}",
    )
    return relative


def ingest(store, state, root, tool, report_file, metadata):
    require(
        metadata.get("snapshot") and metadata["snapshot"] == state.get("snapshot"),
        "diagnostics were not produced for the current snapshot",
    )
    require(
        metadata.get("complete") is True,
        "incomplete tool output is not a valid diagnostic report",
    )
    exit_status = metadata.get("exit_status")
    require(
        type(exit_status) is int and exit_status in EXIT_CODES[tool],
        "tool exit status indicates failure or is unsupported",
    )
    invocation = string(metadata, "command")
    tool_version = string(metadata, "tool_version")
    cwd = Path(string(metadata, "cwd"))
    require(
        cwd.is_absolute()
        and cwd.resolve() == cwd
        and cwd.is_relative_to(root)
        and cwd.is_dir(),
        "diagnostic cwd must be inside the worktree",
    )
    coverage = array(metadata, "coverage")
    require(
        coverage and all(isinstance(p, str) for p in coverage),
        "declare concrete source paths checked by the tool",
    )
    entries = state["inventory"]["entries"]
    path_for = partial(relative_path, cwd=cwd, root=root, entries=entries)
    covered = {path_for(path) for path in coverage}
    report = read_json(report_file)
    rows = rows_for_report(report, tool, path_for, covered)
    require(exit_status == 0 or rows, "nonzero tool exit has no diagnostics")
    profile = digest(
        [tool, tool_version, invocation, str(cwd), state["inventory"]["rules"]]
    )
    findings = list(diagnostic_findings(rows, tool, path_for, root, covered, profile))
    run = {
        "tool": tool,
        "command": invocation,
        "tool_version": tool_version,
        "exit_status": exit_status,
        "cwd": str(cwd),
        "snapshot": state["snapshot"],
        "coverage": sorted(covered),
        "profile": profile,
        "revision": state["revision"] + 1,
        "report_digest": digest(report),
        "findings": [observe(state, finding) for finding in findings],
    }
    state.setdefault("diagnostic_runs", {})[tool] = run
    state["diagnostic_run_index"] = {
        **{
            key: kept
            for key, kept in state.get("diagnostic_run_index", {}).items()
            if kept["snapshot"] == state["snapshot"]
        },
        digest([profile, run["coverage"]]): run,
    }
    store.save(state, "diagnostics", run)
    return run


def rows_for_report(report, tool, path_for, covered):
    if tool == "ruff":
        rows = list(ruff_rows(report))
    elif tool == "sarif":
        rows = list(sarif_rows(report))
    else:
        rows = list(js_rows(report, tool))
        reported = {
            path_for(entry["filePath" if tool == "eslint" else "source"])
            for entry in report
        }
        require(
            reported == covered,
            "reported files do not match declared diagnostic coverage",
        )
    return rows


def diagnostic_findings(rows, tool, path_for, root, covered, profile):
    lines = {}
    occurrences = Counter()
    for file, rule, message, severity, coordinates_ in rows:
        path = path_for(file)
        require(path in covered, f"diagnostic path was not declared covered: {path!r}")
        if path not in lines:
            lines[path] = SOURCE_NEWLINE.split(
                read_source(safe_file(root, path)).decode("utf-8-sig")
            )
        index = coordinates_["line"] - 1
        require(index < len(lines[path]), f"diagnostic line is out of range: {path!r}")
        anchor = digest([lines[path][index].strip(), re.sub(r"\s+", " ", message)])[:24]
        group = (path, rule, anchor)
        occurrences[group] += 1
        yield {
            "origin": "diagnostic",
            "tool": tool,
            "rule": f"{tool}:{rule}",
            "anchor": anchor,
            "identity": occurrences[group],
            "location": {"path": path, **coordinates_},
            "related": [],
            "signature": digest([rule, anchor, severity]),
            "observation": {"message": message, "tool_severity": severity},
            "diagnostic_profile": profile,
        }
