---
name: arete-project
description: "Hand a project to Arete so its pipeline builds it from tickets. Use to put a new repo under Arete (GitHub repo, config entry, layer, labels) or to split a spec into agent tickets for a repo Arete already runs."
---

# Hand a project to Arete

Arete's poll takes every open issue labeled `agent` that the repo owner opened, in a `pipeline = true` repo, and runs plan, build, checks, verify in use and review on it, then opens a PR. The hand off is done when every ticket is filed and `arete status` or the dashboard queue shows them. The owner reviews and merges the PRs.

Facts live in Arete's README (`~/dev/arete/README.md`); read the sections named below rather than trusting a summary. Gotchas no config shows are in [GOTCHAS.md](GOTCHAS.md).

## Gates

Stop for the owner's word before each of these, and batch them into one question with the exact commands:

- creating the GitHub repo (public or private) and pushing to it
- filing issues in a public repo
- merging Arete's PRs

Everything else in this skill is reversible: do it, then report.

## Steps

1. **Read.** The spec or plan, the target repo, and the README sections "Global config" (the `[[repo]]` fields), "Per repo layer", "GitHub tickets" and "Local tasks". Done when you can name the repo's language toolchain, how to run it, and how a person would check each spec requirement by hand.

2. **Starting commit.** Arete branches from `origin/main`, so the repo needs a GitHub remote and one commit on `main`. Pick what that commit holds:
   - the **contracts** the tickets share (data format, CLI entry, shared modules), so tickets run in parallel against fixed seams; or
   - docs only, with ticket 1 building the skeleton and every other ticket waiting on it.
   Recommend contracts when more than two tickets would otherwise wait on one. In a public repo, commit with the identity of the repo owner's other public repos (match `git log -1 --format='%an <%ae>'` in `~/dev/arete`). The repo's own `.gitignore` keeps tool folders and caches out.

3. **Layer.** Write `~/.config/arete/layers/<name>/config.toml`; a layer outside the repo keeps machine paths and private repo names out of a public repo. Fill `[setup]`, `[checks]`, `[limits]`, `[agent]`, `[trust]` (`level = "pr"`), `[verify]` and `[git]` per the README. Done when:
   - every check command passes on `main` today; run each one
   - `max_diff_lines` fits the largest ticket
   - `verify.start` serves the app on `{port}` for a UI, or is `""` for a CLI that verify drives through `verify.allow_bash`
   - `verify.notes` names the local fixtures and repos verify may use, and what it must leave alone
   Seed `expertise.md` in the layer with the owner's code rules that the spec carries (style, no tests, naming); the learn step rewrites it later.

4. **Tickets.** Split the spec into tickets in the shape of recent ones (`gh issue list -R justinpbarnett/arete --label agent --state closed --limit 3`, then `gh issue view N`): a title that states the outcome, then **Problem.**, **Change.**, **Done when:** and **Notes.**, and a last line `Waits on #N.` for each ticket it needs merged first. Write drafts as files in the initiative folder, one per ticket, with placeholders such as `#{python}` in place of numbers. Each ticket must:
   - fit under `max_diff_lines`, and run in parallel with its siblings wherever the seams allow
   - name every file it may touch in Notes, and every shared file it must leave as on `main`
   - carry the full scope in its body; a resumed run does not reread anything else
   - have Done lines that Arete's own steps can check: a check command, or a person's action in verify (run a CLI, click, drag, type, read the screen) on the one port Arete starts, plus Node scripts for numbers such as frame times
   - bound time with the checks step's default class deadline, so every timing runs inside Arete's sandbox
   - allow, in its scope lines, every write that `main` already makes (a launcher marker, a cache, a generated file)
   A public ticket names no private repo, machine path or person; point at "the fixtures in the layer's verify notes" instead.

5. **Register.** Run `arete status` and read the "runs live" line. With runs live, switch poll off first (`arete loop disable poll`), since a config or layer edit fails live runs. Add the `[[repo]]` block (`name`, `path`, `github`, `public`, `pipeline = true`, `layer`) to `~/.config/arete/config.toml`, then run `arete status` again: the repo shows with no config error. Switch poll back on (`arete loop enable poll`) if you turned it off.

6. **Labels and filing.** Create the labels once: `gh label create agent -R OWNER/REPO --color 0e8a16 --description "Arete builds this" --force`, and the same for `agent:running`, `agent:pr`, `agent:failed` and `agent:needs-info`. File the drafts in dependency order with `gh issue create -R OWNER/REPO --title ... --body-file ... --label agent`, replacing each placeholder with the real number before filing the tickets that wait on it.

7. **Watch.** Poll runs every 5 minutes. Done when `arete status` or the dashboard queue lists every ticket as running or waiting on its `Waits on` line. Tell the owner:
   - `agent:needs-info` means a question: reply in an issue comment, or run `arete answer RUN_ID`
   - `agent:pr` means a PR to review and merge; tickets that wait on it start after the merge
   - `agent:failed` means read `arete lines RUN_ID`, fix the ticket body, then remove the label to queue it again
