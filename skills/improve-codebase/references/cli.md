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
PY="$SKILL/.venv/bin/python"
"$PY" "$CLI" doctor
"$PY" "$CLI" scan --root "$PWD" --format json
"$PY" "$CLI" next --root "$PWD" --format json
"$PY" "$CLI" report --root "$PWD" --format json
"$PY" "$CLI" complete --root "$PWD" --format json
```

Pass common options after the leaf subcommand.
Use `--summary --format json` on `scan`, `status`, `next`, or `complete` for counts and gates without the full queues and inventory.
`--thresholds FILE` takes a JSON object of numeric overrides to the defaults printed by `doctor`; this selects a separate profile, not a way to resolve current debt.
Use `--target N` on status commands to report an interim target without changing the clean predicate.
Standard output is parseable JSON with `--format json`, including on runtime errors; argument parsing prints usage on stderr.
Exit 0 means successful execution, not necessarily low debt; `complete` alone uses exit 1 for valid incomplete work.
Exit 2 means invalid or stale input/state, and 3 means operational failure.

## Named runs, fallout, and slices

From the target root, save the scope and thresholds once; use `--run NAME` on later commands.
Repeat `--root` and any alternate `--state-dir` if running outside the target root or default ledger.
`run list` shows saved names and their exact configurations.
A plain named run reuses the unnamed ledger for the same scope and thresholds.
Existing unnamed commands still work with repeated `--scope` options.

```bash
"$PY" "$CLI" run start repo
"$PY" "$CLI" scan --run repo --summary
"$PY" "$CLI" run slice editor --run repo --path client/src/components
"$PY" "$CLI" next --run editor --summary --format json
"$PY" "$CLI" review prepare --run editor --axis contracts --format json --receipt-template
"$PY" "$CLI" complete --run repo
```

A slice selects review work and shows its own coverage, unresolved findings, and verification status against the full parent ledger.
Even with a verified slice, `complete --run SLICE` still applies the parent gate.

```bash
"$PY" "$CLI" run start fallout --base BASE_COMMIT \
    --scope client --include client/src/affected-runtime-caller.ts
"$PY" "$CLI" scan --run fallout --summary
```

Fallout pins the supplied commit, includes staged, unstaged, and visible untracked first-party changes, and proposes direct callers from current and base static wiring.
`--scope` limits which files can be proposed, not which changed dependencies are considered when finding callers.
`--include` adds confirmed manual paths inside that fence.
`absent_paths` lists in-fence Git deletions and type changes with no live source or reference in the inventory, even when another object occupies the path.
`outside_fence` reports changed or retired paths and affected callers that are not part of the proposed scope.
Check `absent_paths`, `outside_fence`, `graph_limits`, and `requires_wiring_review` before acting; imports cannot prove coverage of dynamic wiring or consumers outside the repository.
Inspect the base and current entry points and add affected paths at setup when the graph cannot find them.
The saved scope is fixed; if investigation changes the authorized area materially, name the expanded run explicitly rather than silently replacing the original.
For each promoted or semantic finding in a fallout run, add `change_relation: regression|pre_existing|unclassified` and `relation_evidence` grounded in comparison with the pinned base or explaining why that comparison is unavailable.
Paths seen only as context can be recorded as observations, but never count as findings for this scope.

## State and refresh

The default worktree-local database is `.improve-codebase/state.sqlite3`.
The first write protects the directory through Git's local exclude file, with no tracked `.gitignore` edit.
When upgrading a ledger, rescan before importing; the wiring rubric upgrade needs new review evidence, but does not reset findings or recorded baselines.
For non-Git projects it is still local, but no Git ignore protection is available.
Keep receipt inputs, logs, and screenshots in that directory; use `umask 077` for new local artifacts and redact credentials or sensitive outputs.
`--state-dir` selects an alternate location; an in-worktree override must already be ignored and untracked.
Use `status` or `next` to see the saved revision, baseline/current fingerprints, exact changed inputs for due units, and unmet verification.
Review receipts follow the unit's source, relationships, governing rules, and declared reads.
Full checks and final diff still belong to the current run snapshot.
`report` includes inventory dispositions, source hashes, graph limits, metric ranks, review/finding history, and verification records; filter with a JSON query to keep output small.
The scan checks the whole inventory for cross-scope relationships and reuses compatible parser results.
An unrelated out-of-scope edit does not expire scoped evidence.
A new or changed relationship, governing file, or required project partition input can still require a scan.
A changed supporting file declared in a review receipt invalidates that receipt even if the scoped snapshot stays the same.
`scan --full` bypasses the parser cache and preserves the ledger.
The detector cache keeps only rows for the current parser profiles, core only and full.
Only use `scan --checkpoint` once per completed investigation or fix cycle, not for repeated status checks.
Do not edit the database directly; on a stale revision reload `status` and reconcile the change.
If state is corrupt or incompatible, stop, preserve it for recovery, and ask before archiving it or starting over.

## Reviews

`review prepare --axis smells|architecture|contracts --pass discovery|confirmation --format json` emits one bounded `packet` with `id`, `snapshot`, `sweep_id`, `axis`, `pass`, `governing_paths`, and `units`.
`remaining` counts units still due on the packet's axis, so call prepare again until `packet` is null.
Omit the pass or axis to select pending work.
Use `--path` to target files or directories, `--unit` for exact IDs on the same axis and pass, `--partition` to focus a project, or `--exclude-unit` to skip assignments already delegated.
`--full` makes previously covered units eligible for the selected pass.
A `wiring_partition` unit covers the dynamic or unresolved relationships in that partition and may be much larger than other units; delegate it separately.
Ordinary file and relationship reviews are due only when their own inputs change.
Read each unit's `files` and its `context` mapping of all required paths to hashes, and read the relevant rules and any additional callers needed to substantiate the claim.
Parent `README`, `CONTRIBUTING`, and `CONTRACTS` documents are included as review context, not scanned as source code.
Other inventoried documentation can be cited by path and hash when it supports a review.
For relationship units the assigned `files` include both ends; for partition fallback consult relevant project wiring beyond static imports.

Prepare with `--format json --receipt-template` and use `.receipt_template` as the response for `review import --input RECEIPT`.
Fill the reviewer and each unit's source-linked evidence; the template deliberately leaves them blank.
Record each relevant inspected source or document outside the supplied context in `reads` with its observed hash.
For an outside-scope observation, add a unit's optional `observations` array of `{ "location": { "path": "…", "line": 12 }, "evidence": "…" }` entries pointing to a declared `reads` path outside the run scope.
A rescan can leave a packet importable when its exact inputs and declared reads are unchanged and no newer receipt superseded it.
Reprepare a rejected packet; do not stamp it with a new snapshot or replace observed hashes.
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
For multiple finding events, pass `{ "revision": N, "snapshot": "…", "updates": [ … ] }` with one event per finding ID and no per-event revision or snapshot.
A batch advances the revision once or rolls back entirely; refresh `status --summary` before reconciling any stale batch.
A candidate promoted to `open` requires `severity` (`critical`, `high`, `medium`, `low`), `confidence` (`high`, `medium`, `low`), `evidence`, `impact`, `transformation`, `contracts` (nonempty array of strings), and `verification` (planned checks or flows).
An `open` update may set `dependencies` to other confirmed finding IDs; a dependent is ready once each dependency is `resolved` or `false_positive` (needs no work) or `superseded` with fulfilled replacements.
`false_positive` and `blocked` require concrete `evidence`; `accepted_risk` requires the actual `human_authorization` and remains debt.
An `open` finding moves to `false_positive` when review refutes it or its remaining observation holds only keep cases; the evidence names them, and a changed observation returns it to `candidate`.
`superseded` requires confirmed or verified `replacements` for the same concrete issue; cite the overlap and keep independent findings separate.

Mark `pending_verification` with `evidence` before editing, then rescan with the same detector profile and run relevant checks and current source/caller review.
Use a bounded `review prepare --full` if a cached review cannot demonstrate that a fix was independently rechecked after going pending.
For `resolved`, include `evidence`, current passing focused `verification_ids`, and fresh `review_units` covering each affected source path.
Diagnostic findings require a fresh import of the same tool profile on the affected scope.
Scanner findings require current detector coverage of their affected paths; dependency cycles also require graph-wide coverage.
An unrelated scanner gap does not block that individual resolution, but still blocks whole-scope completion.
A disappearing detector observation, a skipped file, or a move across the scope boundary is not a resolution.
For a deliberate in-scope deletion such as removing a forwarding module, include `removal` with exactly the deleted `paths`, reviewed `surviving_paths`, and `evidence` for the deletion and ownership transfer.
A `wide-folder` finding resolves when the members recorded at pending left the folder as in-scope moves (each matched by hash one to one to a path that newly appeared) or as a declared `removal`, a rename inside the folder counts as a kept member, and a member still on disk, moved into tests or moved out of scope is not a resolution.

## Verification and diagnostics

Use `verification record --input FILE` with `revision`, `snapshot`, `kind: manifest`, and `requirements` covering `baseline`, `check`, `flow`, and `final_diff`.
Each requirement has `id`, `kind`, `description`, and `discovered_from` (the instruction, configuration, or observed entry point).
List every applicable check or flow separately.
Use `{ "revision": N, "snapshot": "…", "records": [ … ] }` to record a manifest followed by baseline observations or to record related current checks together.
A batch accepts at most one manifest and one event per requirement ID; each non-baseline observation still needs its recorded `baseline_snapshot`.
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
