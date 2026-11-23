# Gotchas while Arete runs a project

Read when a run asks, fails, holds its PR, or you want to push to its branch.

- **Answers carry the whole scope.** A run resumed by `arete answer` reads the answer, not the ticket body again. Put the full scope in the answer, and edit the ticket body to match so the reviewer sees it.
- **Hands off the worktree.** A commit made by hand in a run's worktree trips the kept work guard. Answer the run and resume it instead; the resume merges a base that moved.
- **Pushing to a PR branch.** Read the PR comments and check for a live run first (`arete status`). A push during a run makes the run push nothing; recover with `git merge -s ours`.
- **Blocker in a shared file.** A ticket that leaves a shared module as on `main` can only work around a flaw rooted there. Let the run patch its own files, fix the root in the shared module on a branch yourself, and ask the owner to merge it.
- **Held PR.** The PR body leaves out the reviewer's reasoning. Read the review `step_end` in `arete lines RUN_ID` before calling a blocker handled.
- **Config edits.** A change to the config or a layer fails every live run with PolicyChanged. Count live runs by the "runs live" line of `arete status` (its serve line counts loop runs only), switch poll off, edit, switch it on.
- **Sleep.** A Mac that sleeps stalls runs; on AC power it stays awake.
