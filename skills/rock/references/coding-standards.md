# Coding Standards – Rock Customizations

**The one rule everything else serves: the next person that opens this cold can understand it in ~10 seconds.**

Assume they're technical. Assume they've never seen this file, they're reading it inside Rock's editor, and something is broken right now. They should understand what it does and know exactly where to change it – without asking anyone and without pasting it into an AI.

Four priorities, in this order:

1. **Brevity** – the shortest code that does the job. Less code is less to read, less to break, and a shorter file is a more navigable one.
2. **Readable format** – consistent indentation, one statement per line, whitespace that shows the shape of the logic.
3. **Optimized** – do the work once, in the right place. A query that scans less and a template that loops less is also shorter to read.
4. **Self-documenting** – names and structure say what the code does, and a comment earns its place only by warning of a bug the code cannot show (§3).

**Brevity means doing less, not packing more onto a line.** Cutting a redundant join is brevity. Collapsing an if/else into one 278-character line is not – that trades a real cost (nobody can read it) for a fake saving (§6).

Applies to everything that lands in Rock: HtmlContent blocks, block Pre/PostHtml, Dynamic Data queries, workflow action SQL and Lava, form headers, Lava shortcodes, and the scripts you deploy them with.

**On code that predates this:** it binds anything you write or edit from here on.
Older files aren't a backlog: no renaming sweeps, no comment-stripping sweeps.
When you're already inside one for another reason, bring the part you touched up to standard and leave the rest.
A file half-converted is fine; a file nobody dared open isn't.

> Every ID, page number, and figure below is an invented placeholder. Substitute your own instance's values; never paste real ones into this file.

---

## 1. The code says what it does

Names and structure carry the explanation.
The markup shows what a person sees, the class names say what each rule styles (§7), and the variable and column names say what each value holds (§5).
When you reach for a comment, rename or restructure until it has nothing left to say.
§3 has the two kinds of comment that survive that.

What the customization does, and what it needs to run, go in its registry row (§10).

---

## 2. Keep each kind of code in one place

The queries together, then the markup, then one `<style>` block, then one `<script>` block.
The queries come first because Lava runs top to bottom and the markup reads their results.
The file's own tags mark each part, so "change the colors in the `<style>` block" is all the direction anyone needs over chat.

---

## 3. Comments – only two kinds

A comment says what the code cannot, and only two kinds of comment do.
Assume the reader knows the language, and knows nothing about this file, this data, or why you chose this over the obvious thing.
When an edit makes a comment wrong, fix it or delete it in the same edit.
Use the file's own comment syntax: Lava `{# #}`, HTML `<!-- -->`, SQL and JS `/* */`, Python `#`.

Brevity applies here too: the shortest comment that prevents the bug. Length is earned by consequence, not by thoroughness.

Voice: lowercase, terse, plain. No numbering, no hedging, no explaining why you wrote it that way unless the reason prevents a bug.

CAPS are for the one word carrying the warning – `DON'T`, `NOT`, `ALSO`, `DO NOT DELETE`. Everything around it stays lowercase. Proper nouns keep their capitals.

### 3.1 The "looks wrong, is right" comment

The highest-value comment there is: it stops someone from "simplifying" working code into a bug.
Put it on the exact line someone would "fix", and say **what breaks**.
When you measured the reason, give the number from your own instance, because numbers are what keep a comment trustworthy in two years.

```sql
/* DO NOT DELETE. only reason this query is fast: the audit table has tens of
   millions of rows and SQL Server can't see @WindowStart at compile time, so it
   plans as if there were no date window at all. measure it both ways before
   touching this – the difference was an order of magnitude. */
OPTION (RECOMPILE)
```

```lava
{# this column is plain text, NOT a person column, on purpose.
   Rock's Dynamic Data block does one DB lookup PER ROW per person column,
   and on a grid this size that was most of the page load.

   the first column IS still a person column and must stay one – the block only
   offers Communicate / Merge / Bulk Update when at least one column is type
   person. #}
```

Rule of thumb worth its own line: **if a Dynamic Data grid feels slow, count rows × person columns before touching the joins.**

### 3.2 The paired-edit comment

Duplication you can't remove still has to be flagged – on **both** sides.

```css
/* these numbers are ALSO in HtmlContent 999 (#directory-brand-label, the inline
   style.cssText in the brand-injection script). change one, change both, or the
   label visibly jumps when you click through from the directory. */
```

---

## 4. Anti-patterns – strip these on sight

| Don't write | Why |
|---|---|
| `/* set bg */`, `/* green button */` | Restates the code. The class name says what the rule styles (§7). |
| `/* loop through the groups */` | The `for` already said that. |
| `/* TODO: clean up */` | No owner, no date, never true. Delete it or file a ticket. |
| Commented-out dead code | Delete it. If the master copies aren't in version control, a dead copy lives forever – if it might come back, it belongs in a ticket. |
| `/* IMPORTANT!! */` | Says nothing. Name the consequence. |
| A comment that repeats the variable name | `/* the person id */` above `@PersonId` |
| A comment that names a bare ID | Name the ID with a variable instead (§5). |
| A support header: `WHAT`, `NEEDS`, `LAST MODIFIED` | The registry row says what it does and what it needs (§10). Rock and version control record who changed it and when. |
| A `SECTION` banner | The file's own tags mark its parts (§2). |
| The story of a change, or the steps to undo it | The ticket holds it, and so does the commit message when the master copy is in version control. |

---

## 5. Naming

**Full words. No abbreviations. No single-letter suffixes.**

| Context | Convention | Yes | No |
|---|---|---|---|
| Lava variables | `camelCase` | `yearsOnTeam`, `isAnniversary` | `anniv_n`, `celebrate_anniv_year` |
| SQL columns, aliases, variables | `PascalCase` | `@PersonId`, `LatestStatusChange`, `TeamName` | `@NL`, `gm`, `p`, `srn` |
| CSS classes | `kebab-case` | `.person-card`, `.person-modal`, `.person-image` | `.pcs`, `.dt2` |
| Python / deploy scripts | `snake_case` | `group_member_count` | `gmc`, `b64`, `repls` |

SQL stays PascalCase so it reads as native alongside Rock's own table and column names. CSS classes are also named for the item on the page they affect – see §7.

A name should say what the value *holds*, not what type it is:

```
yearsOnTeam        not   annivN, yearsInt, n
anniversaryDate    not   aDate, dt
isAnniversary      not   aFlag, chk
```

**Give every ID and magic number a name.**
A bare `11` says nothing about what it selects.
Assign it to a variable named for what it is, and use the variable wherever the number would go.

```lava
{%- assign birthdayThemeId = 1 -%}
{%- assign anniversaryThemeId = 7 -%}
{%- assign bothEventsThemeId = 29 -%}
```

```sql
DECLARE @DeclinedStatusId int = 11;
DECLARE @NoResponseStatusId int = 14;

SELECT
    ConnectionRequest.Id
FROM ConnectionRequest
WHERE ConnectionRequest.ConnectionStatusId NOT IN (@DeclinedStatusId, @NoResponseStatusId)
```

**This applies to throwaway scripts too.** Every "temporary" script you ever wrote is still there.

---

## 6. Formatting

**Never condense multiple statements onto one line.** This is the one place brevity doesn't apply: cut statements, don't stack them. Write the shortest version that does the job, then give it room to breathe.

Wrong – a whole if/else at 278 characters:

```lava
{%- if yearsOnTeam == 0 -%}{%- assign celebrationHeadline = 'Welcome to the team' -%}{%- else -%}{%- capture celebrationHeadline -%}Happy {{ yearsOnTeam | AsString | NumberToOrdinal }} anniversary{%- endcapture -%}{%- endif -%}
```

Right – same output, `{%-` still trims the whitespace, and you can see there are two cases:

```lava
{%- if yearsOnTeam == 0 -%}
  {%- assign celebrationHeadline = 'Welcome to the team' -%}
{%- else -%}
  {%- capture celebrationHeadline -%}
    Happy {{ yearsOnTeam | AsString | NumberToOrdinal }} anniversary
  {%- endcapture -%}
{%- endif -%}
```

**SQL gets one clause per line, indented.** Keywords start the line; everything they own is indented under them.

```sql
SELECT
    Person.NickName,
    Person.LastName,
    Campus.Name AS CampusName
FROM GroupMember
    INNER JOIN Person ON Person.Id = GroupMember.PersonId
    INNER JOIN [Group] ON [Group].Id = GroupMember.GroupId
    LEFT JOIN Campus ON Campus.Id = [Group].CampusId
WHERE [Group].GroupTypeId = 34
    AND [Group].IsActive = 1
    AND GroupMember.GroupMemberStatus = 1
ORDER BY Person.LastName
```

- `SELECT` columns one per line, comma trailing.
- Each `JOIN` indented under `FROM`, its `ON` on the same line.
- Each `AND` on its own line under `WHERE` – so you can delete or comment out one condition without touching its neighbours.
- **Table names in full, never one-letter aliases** (§5). `GroupMember.PersonId` reads on sight; `gm.PersonId` sends you hunting for the `FROM`. Alias only when a table joins to itself, and name it for the role it plays – `ParentGroup`, `ChildGroup`, never `g1`/`g2`.
- **Comments are `/* */`, never `--`.** The Lava sql channel collapses the query onto fewer lines, and a `--` then swallows everything after it.

**Soft cap of ~120 characters.** The exception is inline-styled HTML email templates, where long lines are how email clients need it – leave those alone.

**Collapsing code onto one line is a transport step, never an authoring step.** If a deploy channel needs it flattened or base64'd, the script does that on the way out. The master copy and the live block both stay formatted.

---

## 7. CSS

CSS is where these files get fat – it routinely runs longer than the code it styles. Two rules cut the volume; the third stops the guessing.

**Write the case you have, not every case you might have.** No variants nothing uses, no breakpoints nothing hits, no `:hover` on something that isn't clickable. Add the variant the day a real one shows up.

**Never write a rule to undo your own rule.** If a new rule exists to beat an earlier one, go delete the earlier one instead. Every override is two rules doing one rule's job, and the reader has to hold both in their head to know what actually renders. Reaching for `!important` against your own selector always means this.

**A class name says what it affects, out loud.** Nobody should have to guess, or read the CSS to find out – never `.dt2`, `.card2`, `.wrap-inner`.

**Name it after the item on the page it affects** – the card, the modal, the header, the button – then extend that name for its parts:

```
.directory-card                 the card itself
.directory-card-title           the name on it
.directory-modal                the popup
.directory-modal-header         the bar across its top
.directory-modal-close-button   the X in that bar
```

Read left to right, every name is a thing you could point at on screen.

Spell the words out (§5): `directory-`, never `dir-`; `department`, never `dept`.

**Generic words never stand alone.** `.button`, `.header`, and `.card` are already taken – Rock's theme and every other block on the page share one namespace, so a bare `.header` will style something you've never seen. Keep the item it belongs to in front of it. That's also what makes one grep for `directory-` return every class the block owns.

Then:

- **Never style bare elements or Rock's own classes.** `div`, `td`, `h3`, `.panel`, `.btn` reach outside your block and break pages you'll never think to check. Your prefix is the scope.
- **Use Bootstrap 3 before writing anything.** It's already loaded on every Rock page. A `panel`, a `col-md-6`, a `text-muted` you didn't write is a rule you never maintain.
- **Prefix your own CSS variables.** A theme stylesheet sets generic tokens on `:root`; an unprefixed `--bg` or `--accent` collides with it.
- **One home per property.**
  Colors and sizing live in the `<style>` block (§2), not in inline styles through the markup.
- **Keep each item's rules together.**
  Their shared prefix marks where the group starts and ends.
- **Delete dead classes.** If it isn't in the markup, it isn't doing anything.

**The check before you ship:** every class in the CSS appears in the markup, and every class in the markup appears once in the CSS. When the CSS outruns the markup it styles, the excess is almost always unused variants and overrides – that's where to look.

---

## 8. Data shape

**Never pack records into a delimited string read back by index.** Use named fields.

```
Wrong:  "Smith|John|2026-01-04|Active"   then  | Split:'|' | Index:2
Right:  a row or object with FirstName, LastName, StartDate, Status
```

Position-indexed data breaks silently the moment anyone adds a field, and nothing in the code says what index 2 was supposed to be.

**Never store single-line clumped HTML in the database.** HtmlContent written as one giant line is unreadable in Rock's editor, which is exactly where the next person will open it. Write it formatted (base64 through the deploy script so newlines survive).

---

## 9. Rendering and copy

- **Font Awesome only, never emoji.** Check which Font Awesome version the target page actually loads first – a page on an older theme may still be on FA 5, where FA6-only glyphs render blank.
- **Fixing logic is not permission to reword user-facing copy.** If copy should change, that's a separate, deliberate decision.
- **Use relative asset URLs.** When one Rock instance serves several domains, cross-origin asset URLs fail silently on the others.
- **Dark mode is a build step, not a follow-up.** Check both modes before you call it done.

---

## 10. Register it

Every deployed customization gets a row in your team's customization registry – the map of where each hidden edit lives. Create or move one, update the registry in the same change.

The registry holds what version control can't: *which live block this is injected into*, what it does in one plain sentence, and what it needs to run, such as Enabled Lava Commands, a security grant, a cache flush, or an app-pool recycle.
**A warning that prevents a bug belongs in the code, at the line where someone would break it** (§3), because a teammate editing a block in Rock never sees the registry.

---

## Checklist before deploying

- [ ] Every comment is one of the two kinds in §3, and every line that looks wrong and is right has one
- [ ] Each kind of code sits in one place, queries first (§2)
- [ ] Every ID and magic number is a named variable (§5)
- [ ] Names are full words, correct case for the language
- [ ] No line packs multiple statements; SQL is one clause per line
- [ ] Nothing in the file is longer than it needs to be – no dead branches, no options nobody asked for, no comment that only restates the code
- [ ] No commented-out dead code, no bare `TODO`
- [ ] Every CSS class is named for the item it affects, spelled out, never generic on its own; none are unused
- [ ] No CSS rule exists only to override another rule in the same file
- [ ] No delimited string read back by index; no single-line HTML written to the database
- [ ] Font Awesome only (right version for the target page), asset URLs relative, both light and dark mode checked
- [ ] Master copy updated wherever it lives
- [ ] Row added or updated in the customization registry, with what it does and what it needs to run
- [ ] Cache invalidated for just the block/page you touched – **NEVER** a full Rock cache clear
