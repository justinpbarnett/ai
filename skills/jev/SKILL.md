---
name: jev
description: "JEV, a classifier that answers in about a second for a fraction of a cent, through `arete ask`. Use to sort or filter many files, lines or items before reading them; to sort a test failure, log or error before digging in; to check a diff or draft against its task; to judge whether two items are the same; or to put a yes or no, choice or rating step in a script."
---

# JEV

`arete ask` puts one question to JEV over piped text, or over each file you name, and prints an answer with a confidence. Spend a call wherever the alternative is reading: sort 40 files with JEV, then read the five it picks.

## Ask

Three shapes of question:

```sh
arete ask "Does this file check permissions?" src -r --only yes
<test command> 2>&1 | tail -200 | arete ask "Why does this run fail?" --choice \
  "code=the code under test is wrong" "test=the test itself is wrong" "setup=the environment or setup is wrong"
git diff | arete ask "How far does this diff reach past the task: fix the date parser?" --score none some far
```

- Paths go before `--choice` or `--score`. Both take a list, so a path after them reads as a label.
- Each file gets its own answer, sixteen at a time, up to 2000 files. `-r` walks folders, and `--only ANSWER` keeps every row with that answer, however unsure.
- `--score` levels run lowest first.
- `--json` gives `answer`, `confidence` and `probabilities` for each label. Read the probabilities when a line between two outcomes matters.
- Exit 2 is no answer: JEV is off for the repo in the arete config, the key is missing, or the question is malformed. Read the items yourself.

## Where it pays

- **Sort before reading**: which files touch a concern, which log lines are failures that matter, which messages or tickets ask for action.
- **Sort a failure**: the tail of a failing run with the code, test, setup choice above.
- **Check work**: pipe a diff or a draft and name the task in the question.
- **Same or different**: pipe two items together and ask whether they describe the same thing, with a `none` label when neither fits.
- **Scripts**: run `arete ask QUESTION --choice ... --json` with the text on stdin, read `probabilities`, and set the line on real examples of each outcome. On a nonzero exit, fall back to what the script did before.

## Limits

JEV cannot count, compare dates or follow negation, and it leans toward the first choice. Word each question as a positive check, give a `none` label when no label may fit, and read a confidence under 0.8 as unsure (on a yes or no question, a chance of yes between 0.1 and 0.9). An answer is a sort, not a verdict: read the code yourself before you change it or rest a decision on an answer.

The text goes to OpenRouter and TypeSafe, cut at 90000 characters. `arete ask` refuses secret files (`.env`, keys, `~/.ssh`, cloud credentials); keep credentials out of piped text the same way.
