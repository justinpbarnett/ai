---
name: to-ste
description: Convert a target document or pasted prose into ASD-STE100 Simplified Technical English, then lint to prove the AI-slop score dropped.
disable-model-invocation: true
---

# To STE

Convert prose into **ASD-STE100 Simplified Technical English** to strip **AI slop**. Applies to documentation, READMEs, PR descriptions, error messages, release notes, and comments. Does not apply to code, identifiers, or command syntax. Not for marketing copy or an essay that needs a voice — STE strips voice on purpose.

Slop is a problem of **form**: 30-word sentences, passive voice, marketing adjectives, hedges, phrasal verbs, one thing named three ways. This skill fixes the form. It cannot make a hollow paragraph true, and it is not a certified STE checker — it covers the mechanical subset of ASD-STE100, which is where the slop lives.

## Process

### 1. Get the target

The target is a file path or issue reference passed as an argument, text pasted into the conversation, or the draft already in context. Read the whole source. Convert only prose — leave fenced code, inline code, identifiers, and command syntax exactly as written.

### 2. Pick a mode

- **strict** — procedures, runbooks, safety text, error messages. Apply every rule and both length caps.
- **flavored** — general prose (READMEs, PR descriptions, docs). Apply the sentence, paragraph, active-voice, and phrasal-verb discipline. Keep richer vocabulary so the text still reads naturally. The banned slop words still go.

Infer the mode from the document type and state which you picked. The user can override.

### 3. Rewrite against the rules

WORDS
- One name for one thing. Do not call the same item by two names.
- The short common word: **start** (not begin/commence/initiate), **use** (not utilize/leverage), **help** (not facilitate), **make sure** (not ensure), **before** (not prior to), **after** (not subsequent to), **about** (not regarding/concerning), **get** (not obtain/acquire), **show** (not demonstrate), **also** (not additionally/furthermore/moreover).
- One meaning per word. "fall" means to move down, not to decrease.
- No marketing adjectives: seamless, robust, powerful, cutting-edge, effortless, world-class, next-generation, revolutionary.
- American spelling.

VERBS
- Active voice. "the parser reads the file", not "the file is read by the parser".
- A verb for an action: "analyze the log", not "perform an analysis of the log".
- No stacked auxiliaries. Replace "it is important to note that this may help to improve X" with "this improves X".
- No "-ing" main verb where a simple tense works.

SENTENCES
- One instruction per sentence. Max 20 words for an instruction, max 25 for a descriptive sentence.
- No contractions. Use the articles a, an, the, this, these.

PUNCTUATION
- No semicolons — write two sentences.
- Remove em dashes and en dashes. STE bans only the semicolon, but the em dash is the top slop marker, so a de-slop pass takes it out too.

STRUCTURE
- One topic per paragraph, max six sentences. For steps, use a numbered vertical list, one action per item, imperative form. Put a condition before its command.

### 4. Lint to prove it — the signal

Run the bundled linter (`scripts/ste-lint.py`, in this skill's folder — use its absolute path; it needs only Python 3) on the original and on your rewrite:

```
python3 <skill-dir>/scripts/ste-lint.py < original.md    # full per-category JSON
python3 <skill-dir>/scripts/ste-lint.py < rewrite.md
```

It reads stdin, or takes file paths as arguments. For pasted text, write each version to a temp file in the scratchpad and lint that. The counts are violations per 100 words. Lower is cleaner, and the **delta** between original and rewrite is the signal.

Read the JSON and drive the named counts down:

- **strict** — every violation category at **0**, `em_dash` at 0, `longest_sentence_words` at 20 or less.
- **flavored** — `semicolon`, `contraction`, `passive_voice`, `ing_main_verb`, `nominalization`, `phrasal_verb`, `banned_word`, `marketing_adjective`, `modal_hedge`, `long_paragraph`, and `em_dash` all at 0. A few 21–25 word *descriptive* sentences may stay. No instruction is over 20 words.

When a count is not zero, `sample_banned` and `sample_marketing` name the offenders and the category tells you where to look. Fix it and lint again. The rewrite is done when the target thresholds hold and the rewrite scores below the original.

### 5. Deliver

Show the converted text and the before/after `total_per100w` and `em_dash` scores. Write it back to the source file only when the user asks. Overwriting the document is destructive, so the default is to show the result.

## Self-lint checklist (mirror of the linter)

Run this by eye first, so the tool only confirms:

1. Any sentence over 20 words (instruction) or 25 (descriptive)? Split it.
2. Any semicolon? Replace it with a period.
3. Any contraction? Expand it.
4. Any passive voice with a known actor? Make it active.
5. Any "-ing" main verb or nominalization ("perform an analysis")? Use a plain verb.
6. Any phrasal verb ("spin up", "kick off", "reach out")? Use one plain verb.
7. Any banned word, marketing adjective, or modal hedge ("it is important to note")? Cut it.
8. Any em dash or en dash? Remove it.
9. Same thing named two ways? Pick one name.

## Credits

Distilled from **ASD-STE100 Simplified Technical English** — the free standard at https://asd-ste100.org (copyrighted; do not paste the dictionary in full). Skill and linter adapted from woosal1337's "The cure for AI slop is a 1986 aircraft manual" (`blog/videos/ep01-the-cure-for-ai-slop`). The linter is a heuristic subset, not a certified STE checker.
