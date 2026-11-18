# CLI and evidence

Use Python 3.11 or newer.
From the skill directory, `uv sync --locked --extra parsers --group dev` installs the verified local grammar bundle and Ruff in the skill environment; it does not touch application dependencies.
Once installed, invoke `SKILL/.venv/bin/python SKILL/scripts/improve_codebase.py` (or the equivalent interpreter on your machine).
Plain `python3` runs the same CLI without tree-sitter; priority-language gaps make completion partial.
To explicitly exercise core-only analysis, add `--core-only` to `doctor` or `scan`.
The scanner never installs packages, fetches grammars, or runs target tooling.

Use the following examples from the target root; substitute the absolute skill path.

```bash
SKILL="$HOME/dev/ai/skills/improve-codebase"
CLI="$SKILL/scripts/improve_codebase.py"
"$SKILL/.venv/bin/python" "$CLI" doctor
"$SKILL/.venv/bin/python" "$CLI" scan --root "$PWD" --format json
python3 "$CLI" next --root "$PWD" --format json
python3 "$CLI" report --root "$PWD" --format json
python3 "$CLI" complete --root "$PWD" --format json
```

Pass common options after the leaf subcommand.
Repeat root-relative `--scope` to select specific paths and use the same arguments throughout the run.
`--thresholds FILE` takes a JSON object of numeric overrides to the defaults printed by `doctor`; this selects a separate profile, not a way to resolve current debt.
Use `--target N` on status commands to report an interim target without changing the clean predicate.
Standard output is parseable JSON with `--format json`, including on runtime errors; argument parsing prints usage on stderr.
Exit 0 means successful execution, not necessarily low debt; `complete` alone uses exit 1 for valid incomplete work.
Exit 2 means invalid or stale input/state, and 3 means operational failure.

## State and refresh

The default worktree-local database is `.improve-codebase/state.sqlite3`.
The first write protects the directory through Git's local exclude file, with no tracked `.gitignore` edit.
For non-Git projects it is still local, but no Git ignore protection is available.
Keep receipt inputs, logs, and screenshots in that directory; use `umask 077` for new local artifacts and redact credentials or sensitive outputs.
`--state-dir` selects an alternate location; an in-worktree override must already be ignored and untracked.
Use `status` or `next` to see the saved revision, baseline/current fingerprints, review work reasons, and unmet verification.
`report` includes inventory dispositions, source hashes, graph limits, metric ranks, review/finding history, and verification records; filter with a JSON query to keep output small.
The scan checks the whole inventory for cross-scope relationships and reuses compatible parser results.
An unrelated out-of-scope edit does not expire scoped evidence.
A new or changed relationship, governing file, or required project partition input can still require a scan.
A changed supporting file declared in a review receipt invalidates that receipt even if the scoped snapshot stays the same.
`scan --full` bypasses the parser cache and preserves the ledger.
Only use `scan --checkpoint` once per completed investigation or fix cycle, not for repeated status checks.
Do not edit the database directly; on a stale revision reload `status` and reconcile the change.
If state is corrupt or incompatible, stop, preserve it for recovery, and ask before archiving it or starting over.

## Reviews

`review prepare --axis smells|architecture|contracts --pass discovery|confirmation --format json` emits one bounded `packet` with `id`, `snapshot`, `sweep_id`, `axis`, `pass`, `governing_paths`, and `units`.
Omit the pass/axis to select pending work, use `--partition` to focus a component, and repeat `--exclude-unit` to avoid assigning units already delegated.
`--full` includes previously covered units for the selected pass; paginate by passing completed unit IDs (not packet IDs) to `--exclude-unit`.
Read each unit's `files` and its `context` mapping of all required paths to hashes, and read the relevant rules and any additional callers needed to substantiate the claim.
Parent `README`, `CONTRIBUTING`, and `CONTRACTS` documents are included as review context, not scanned as source code.
Other inventoried documentation can be cited by path and hash when it supports a review.
For relationship units the assigned `files` include both ends; for partition fallback consult relevant project wiring beyond static imports.

Write an explicit response file and use `review import --input RECEIPT`.
Copy the packet identifiers and unit input fingerprints exactly; every assigned unit needs an entry, including reviews with no findings.
Declare all inspected source and documentation dependencies and their hashes in `reads` (at least the packet's `context`).
Use `independence: independent` for a separate reviewer with a distinct identity; otherwise use `sequential`.

```json
{
  "packet_id": "<packet.id>", "snapshot": "<packet.snapshot>",
  "sweep_id": "<packet.sweep_id>", "axis": "<packet.axis>",
  "reviewer": "reviewer-2", "independence": "independent",
  "units": [
    {
      "id": "<unit.id>", "inputs": "<unit.inputs>",
      "reads": {"src/example.py": "<current content hash>"},
      "evidence": "Checked the callable and its callers against the relevant behavior and standards; no actionable design issue.",
      "findings": []
    }
  ]
}
```

A semantic finding in `findings` takes `rule`, stable `anchor`, `location` (`path`, optionally positive 1-based coordinates), optional `related` locations, and the same confirmation fields as finding triage below.
Keep raw observations and compact evidence local; do not paste source bodies into the receipt.
A complete import is atomic; submit separate packets to checkpoint completed work without depending on the rest of a wave.

## Findings

Use `finding update --input FILE` with `revision`, `snapshot`, finding `id`, destination `status`, and `reason`.
A candidate promoted to `open` requires `severity` (`critical`, `high`, `medium`, `low`), `confidence` (`high`, `medium`, `low`), `evidence`, `impact`, `transformation`, `contracts` (nonempty array of strings), and `verification` (planned checks or flows).
An `open` update may set `dependencies` to other confirmed finding IDs.
`false_positive` and `blocked` require concrete `evidence`; `accepted_risk` requires the actual `human_authorization` and remains debt.
`superseded` requires confirmed or verified `replacements` for the same concrete issue; cite the overlap and keep independent findings separate.

Mark `pending_verification` with `evidence` before editing, then rescan with the same detector profile and run relevant checks and current source/caller review.
Use a bounded `review prepare --full` if a cached review cannot demonstrate that a fix was independently rechecked after going pending.
For `resolved`, include `evidence`, current passing focused `verification_ids`, and fresh `review_units` covering each affected source path.
Diagnostic findings require a fresh import of the same tool profile on the affected scope.
A disappearing detector observation, a skipped file, or a move across the scope boundary is not a resolution.
For a deliberate in-scope deletion such as removing a forwarding module, include `removal` with exactly the deleted `paths`, reviewed `surviving_paths`, and `evidence` for the deletion and ownership transfer.

## Verification and diagnostics

Use `verification record --input FILE` with `revision`, `snapshot`, `kind: manifest`, and `requirements` covering `baseline`, `check`, `flow`, and `final_diff`.
Each requirement has `id`, `kind`, `description`, and `discovered_from` (the instruction, configuration, or observed entry point).
List every applicable check or flow separately.
Updating the manifest requires a `reason`; use justified not-applicable records rather than removing requirements.

Record observations with `revision`, `snapshot`, `id`, `kind`, `result` (`passed`, `failed`, `unavailable`, `not_applicable`), absolute project `cwd`, literal `interaction`, `expected`, `observed`, and `exit_status` when applicable.
Include the reported `baseline_snapshot` for non-baseline records.
For `not_applicable`, provide a `reason`; final diff review is required even on unchanged code.
Optional `artifacts` is an array of `{ "path": "relative/to/state-dir", "sha256": "…" }` objects; hashes are rechecked before completion.
Record each baseline before changes and preserve its evidence artifacts at distinct paths from post-change runs.
The ledger preserves the first passing or justified not-applicable baseline for each requirement.
Failed or unavailable attempts remain in history and can be retried while the original target inputs still match, even after a scanner upgrade.
When upgrading older ledgers, the original inventory must match exactly before a baseline retry can be carried over to a new snapshot.
Changes to the verification contract can require new current checks and flows without resetting the baseline.
A passed error-path check may have a nonzero expected exit status; document the comparison rather than treating exit zero as proof of correctness.

Run project analyzers only after inspecting commands and establishing trust.
Save the producer's JSON output in `.improve-codebase/` and use `import-diagnostics --tool ruff|eslint|stylelint|sarif --input REPORT --metadata METADATA`.
Stylelint 16 writes its `--formatter json` report to stderr by default; capture that stream separately or use its `--output-file` option.
Metadata includes `snapshot`, optional expected `revision`, actual `command`, `tool_version`, integer `exit_status`, `complete: true`, absolute `cwd`, and `coverage` (list of local source paths checked, relative to `cwd` or absolute).
Verify actual tool coverage before claiming it; warnings are not execution failure, but fatal, truncated, skipped, or path-incompatible reports cannot be imported as successful evidence.
SARIF 2.1.0 supports explicit local paths and physical line locations, not URI-base indirection.
Record failed or unavailable analyzer runs as verification evidence instead of uploading an empty report.

## Completion

Strict points are 16/8/3/1 for critical/high/medium/low confirmed unresolved findings, including blocked and accepted risk.
Zero is insufficient when inventory, detectors, review, verification, or candidate triage remains incomplete.
A current whole-scope mechanical scan, clean discovery and confirmation coverage, a preserved baseline, current applicable checks and real flows, and current final diff evidence are all required.
Unchanged receipts can satisfy both passes if their separate evidence matches current inputs; one receipt cannot count twice.
A narrow or alternate-profile clean result does not clear the earlier run's debt.
