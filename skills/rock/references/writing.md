# Changing Rock

Read this before writing anything. The four rules in `SKILL.md` are not repeated
here; they still apply to every operation below.

Most writes use a plan file. Run the example from the Rock skill directory (the one containing `SKILL.md`).

```bash
R="$PWD/runtime/rock.sh"
cat > /tmp/rock-plan.json <<'PLAN'
{ "operation": "update_action", "modification": { ... } }
PLAN
"$R" build /tmp/rock-plan.json
```

One operation per plan file, under `/tmp` – the build script rejects any other
path, so a plan cannot land in a repository. Or a `query` subcommand, for the
four small writes at the end of this file.

## Audit first

Run the audit before repairing anything, including when someone has already
described the fault – the described fault is usually a symptom of a different
one.

```bash
"$R" query audit "Volunteer Signup"
```

`--skip-settings` drops the per-action settings checks: far fewer API calls, at
the cost of the most common real fault. Use it for a first pass over a large
workflow, then run the full audit on the activity that looks wrong.

What it checks:

- Activities with no actions
- The first activity not activated with the workflow
- Duplicate activity or action order values
- Action types pointing at entity types that no longer exist – deleted plugins
- `SendEmail` / `SendSms` actions missing a recipient, subject, or body
- Actions that complete their activity mid-chain, orphaning everything after
- Activities nothing ever activates

Then drill in. The audit names the activity; these say why:

```bash
"$R" query actions <activity_id>            # every action's settings
"$R" query attributes "Volunteer Signup"    # attribute keys and field types
"$R" query workflow "Volunteer Signup" --json
```

Attribute keys are the usual culprit. An email action referencing
`{{ Workflow | Attribute:'Email' }}` where the key is actually `EmailAddress`
renders empty, sends to nobody, and reports success.

Label every finding BROKEN or SMELL – failing, versus untidy:

```
"Volunteer Signup" (workflow type 234) – 2 faults, 1 smell

  BROKEN  Activity "Process Signup" (891), action "Send Confirmation" (1234)
          To is empty. Nobody has received a confirmation from this workflow.

  BROKEN  Activity "Notify Staff" (892) is activated by nothing.
          Its two actions have never run.

  SMELL   Activities 891 and 893 both have order 2.
          Execution order between them is undefined.
```

Done when every finding carries the activity and action IDs a repair plan needs,
and says what did or did not happen to the people the workflow touches – that is
what decides whether it gets fixed today or next quarter. A clean audit is a real
result: say so plainly and list what you checked.

## Show the plan, then stop

A structural diff, with the exact before and after:

```
Fix plan for "Volunteer Signup" (workflow type 234)

  Activity "Process Signup" (891)
    [update] Action "Send Confirmation" (1234)
               To:  ""  ->  "{{ Workflow | Attribute:'EmailAddress' }}"
    [delete] Action "Broken Step" (1235)
               entity type 4471 no longer exists
    [reorder] 1234, 1236, 1237
               resolves duplicate order 2

Apply? [y/n]
```

Deleting an activity deletes every action inside it, so spell that out with the
count. There is no rollback – a partly applied plan stays partly applied, which
is what the yes is for.

### The script checks the plan before it logs in

Every operation declares the keys it cannot work without, which keys hold an object or a list, and which hold a name.
The script checks the whole plan against that before it logs in, and it reports every problem it finds on a line of its own.
A plan that names an unknown operation, leaves out a required key, gives a list where an object belongs or a number where a name belongs, or carries an empty `updates` object sends nothing to Rock:

```
Build results:
  ✗ Plan: create_workflow -- needs "workflow.attributes[1].key"
  ✗ Plan: create_workflow -- needs "workflow.activities[0].actions[0].action_type"
  ✗ Plan: create_workflow -- "workflow.activities[1].actions[0].settings" must be an object, got a list
  ✗ Plan: create_workflow -- "workflow.category" must be a name, got 9

Nothing was applied.
```

Each path names a place in the plan, and list items count from 0.
These lines are complaints about the plan, not reports from Rock.
Nothing was written, so there is nothing to verify and nothing to clean up: fix every line and run the plan again.

A `null` reads as the key left out.
So `"description": null` builds with no description, and `"name": null` is refused as missing.
The exceptions are the values inside `settings`, `updates` and an `api_request` body, which go to Rock as written.
A `null` there clears that field.
A `null` in a field that holds a name, such as `role` or `category` in `updates`, is refused instead, because it gives nothing to look up.

Field names are checked too, before anything is written.
Each operation accepts a fixed set, and an unrecognised one is refused with the accepted list rather than sent to Rock as a column name it does not have.

## Repair

| Operation | `modification` |
| --- | --- |
| `update_action` | `action_type_id` + `settings` (component settings) or `updates` (`name`, `order`, `action_type`, `complete_on_success`, `complete_activity_on_success`) |
| `delete_action` | `action_type_id` |
| `move_action` | `action_type_id`, `target_activity_type_id` |
| `reorder_actions` | `action_order`: the full list of action IDs, in order |
| `update_activity` | `activity_type_id` + `updates` (`name`, `description`, `is_activated_with_workflow`, `is_active`, `order`) |
| `delete_activity` | `activity_type_id` – **removes its actions too** |
| `update_workflow` | `workflow_type_id` + `updates` (`name`, `description`, `is_active`, `is_persisted`, `processing_interval` in seconds, `category` or `category_id`) |

The audit supplies the IDs. An `action_type` name resolves through
`"$R" catalog show`, but `settings` keys go to Rock verbatim – take each key
exactly as `"$R" query actions <activity_id>` reports it. Rock rejects a key it
does not recognise, and the operation fails on it rather than skipping that one
setting, so a wrong key costs you the whole apply and not a line of it.

`reorder_actions` takes every action in the activity, not just the moved ones – a
partial list reorders to a state nobody asked for.

## Create

Get all four of these before touching anything, asking the requester for any you
do not have:

- **Purpose.** What happens, and who it happens to.
- **Data collected.** Each field and its type. Text, Email, Phone, Single Select.
- **Actions taken.** Emails, SMS, assignments, delays, attribute setting.
- **Branching.** Any conditional path, and what decides it.

Then look up each name the plan uses in the catalog.
Every action component, block type, field type and layout in the plan resolves through it rather than a remembered ID.
Give `catalog show` a text, and it lists only the entries that contain that text, ignoring case:

```bash
"$R" catalog show "entry form"
"$R" catalog show "full width"
```

`"$R" catalog show` lists each layout with its site, and does not list categories.
The build looks up a page's layout among the layouts of its parent page's site only, so a "Full Width" from another site never matches.
In Rock a page belongs to its layout's site, and Rock's own page editor starts a new page in its parent's site.
The build looks up a workflow's category among Rock's workflow categories only, so a data view category with the same name never matches.
`"$R" query workflows` shows each workflow with its category.

If the request needs an action type the catalog does not have, say so and stop.
It usually means a Rock plugin is not installed, or the component is named something else.
When `catalog show` says the catalog holds only the action types in use, it can also mean that no workflow uses that type yet.

```
Plan: create workflow "Volunteer Signup"

  Category:   Volunteers
  Attributes: FirstName (Text), EmailAddress (Email), Ministry (Single Select)

  ├─ Fill Out Form            (activated with workflow)
  │    └─ UserEntryForm – FirstName, EmailAddress, Ministry
  └─ Process Signup
       ├─ SendEmail  → {{ Workflow | Attribute:'EmailAddress' }}
       └─ SendEmail  → volunteers team

Create? [y/n]
```

Show the attribute **keys** you will create, not the labels – every Lava template
written against this workflow depends on them, and renaming a key later breaks
templates silently.

| Operation | Creates |
| --- | --- |
| `create_workflow` | a workflow type, its attributes, activities and actions |
| `create_page` | a page and its blocks |
| `create_checkin_area` | a check-in group in an existing check-in area, with its rooms |
| `add_action` | an action on an existing activity |
| `add_block` | a block on an existing page |

### A workflow plan

```json
{
  "operation": "create_workflow",
  "workflow": {
    "name": "Volunteer Signup",
    "category": "Volunteers",
    "attributes": [
      { "key": "EmailAddress", "name": "Email Address", "field_type": "Email", "is_required": true },
      { "key": "Notes", "field_type": "Text" }
    ],
    "activities": [
      {
        "name": "Fill Out Form",
        "actions": [
          {
            "name": "Signup Form",
            "action_type": "User Entry Form",
            "form": { "header": "Sign up to serve", "attributes": ["EmailAddress", "Notes"] }
          }
        ]
      }
    ]
  }
}
```

A form lists attribute keys in the order it shows them.
`is_required` makes the attribute required, and every form that shows it will not submit until it has a value.
An attribute without it is optional, on its forms too.

Each form gets one button, Submit, the one Rock's own workflow editor starts a form with.
It completes the form, and the activity goes on to its next action.
The build makes no other button, so buttons that choose between activities, such as Approve and Deny, are added afterwards in Rock's workflow editor.
Say so in the plan when the request needs them.

### A new page stays out of the menus

`display_in_nav` on the `page` decides who sees it in navigation menus:

- `never`, the default, lists it for nobody.
- `when_allowed` lists it for people with permission to view it, which is Rock's own default.
- `always` lists it for everyone, including people who are not allowed to open it.

The default is `never` because a page lands one request at a time, and a plan that stops partway should not put a half-built page in every menu.
Say in the plan which one the page gets.
To change it on an existing page, send an `api_request` PATCH to `Pages/<id>` with `DisplayInNavWhen` set to Rock's number for it: 0 for when allowed, 1 for always, 2 for never.

### A check-in group plan

`create_checkin_area` makes a check-in group, not an area.
In Rock a check-in area is a group type, and the build makes no group types, so the area must exist already.
The operation is listed here rather than under **Groups** because it builds check-in, not a roster.

```json
{
  "operation": "create_checkin_area",
  "checkin_area": {
    "name": "Preschool",
    "group_type": "Nursery/Preschool Area",
    "locations": [77, "Room 102"]
  }
}
```

`group_type` is the area's name, and `group_type_id` takes its id instead.
`"$R" query checkin` lists each check-in template's areas with their ids.
Each entry in `locations` is a room, given as its id or its name, and the group gets the rooms in that order.
`parent_group_id`, `campus_id`, `description` and `is_public` are optional.

The area and the rooms are matched by their exact names.
A name that matches nothing stops the build with the names that contain it, and a name that matches more than one stops it with their ids.
Rooms at different campuses often share a name, so give the id.
`"$R" query checkin --group <group id>` lists the rooms of a check-in group with their ids, and a group that already uses the room shows its id.

The build cannot give the group its schedules.
In Rock each of the group's rooms has its own schedules, and check-in reads only those.
Rock's API cannot set them, so a plan with `schedules` stops before it logs in.
Add them afterwards with the Schedule button on Rock's Check-in Configuration page, under Admin Tools > Settings, and say so in the plan.

## Groups

Group membership is not a quiet field. It decides who receives the group's
communications, who appears on its schedule, and – for a security role – who can
see and do things in Rock.

Look the group up first, then the person:

```bash
"$R" query group "Guest Services"        # the group, its type, its roster
"$R" query person "someone@example.com"  # the person ID to add
```

Role names belong to the **group type**, not the group: "Leader" in a serving
team and "Leader" in a small group are different roles with different IDs. Giving
`role` a name resolves it inside that group's own type, which is why the group ID
has to be right before the role name matters. Pass `group_role_id` when the ID is
already in hand.

```
Roster change: "Guest Services" (group 312, type Serving Team)

  [add]    someone@example.com as Leader, active
             gains: group email, Sunday schedule, group leader toolbox
  [status] someone-else@example.com Leader -> inactive
             keeps the membership row and its history

Apply? [y/n]
```

| Operation | Key | Fields |
| --- | --- | --- |
| `create_group` | `group` | `name`, `group_type` or `group_type_id`, and optionally `parent_group_id`, `campus_id`, `description`, `is_active`, `is_public`, `is_security_role`, `schedule_id`, `group_capacity`, `order`, `settings` |
| `update_group` | `modification` | `group_id` + `updates` (any of the same field names except `group_type` and `group_type_id`, since this operation does not change a group's type) and optionally `settings` |
| `add_group_member` | `modification` | `group_id`, `person_id`, `role` or `group_role_id`, and optionally `status`, `note`, `is_notified`, `order` |
| `update_group_member` | `modification` | `group_member_id` + `updates` (`role` or `group_role_id`, `status`, `note`, `is_notified`, `is_archived` as `false` only, `guest_count`, `order`) |
| `remove_group_member` | `modification` | `group_member_id`, and Rock archives the membership or deletes it, as **Removing a member** below describes |
| `create_group_sync` | `modification` | `group_id`, `role` or `group_type_role_id`, `data_view` or `sync_data_view_id`, and optionally `add_user_accounts`, `schedule_interval_minutes`, `welcome_email_id`, `exit_email_id` |

A `role` given as a name resolves inside the group's own type, which for
`update_group_member` means reading the membership's group back first.

`status` is `active`, `inactive`, or `pending`, and it defaults to `active`, as it does in Rock.
An inactive member keeps the membership, and Rock records the date the member became inactive.

`settings` are the group type's attributes, keyed exactly as
`"$R" query group <id>` reports them.

Rock validates a membership when it saves: a duplicate member, a group over
capacity, an unmet group requirement all come back as errors rather than silent
successes. Report what came back.

### Removing a member

`remove_group_member` asks Rock to remove the membership, and Rock chooses how.
If the group's type has Enable Group History Tracking turned on and the membership has history, Rock archives it.
The row stays with the date it was archived, and the person leaves the roster.
Otherwise Rock deletes the row, and the person's history still records that they left the group.
Attendance is not part of a membership, so it stays either way.

To bring an archived membership back, set `is_archived` to `false`:

```json
{"operation": "update_group_member",
 "modification": {"group_member_id": 4471, "updates": {"is_archived": false}}}
```

This clears the archive date along with the flag, as Rock's own restore does, and the person is back on the roster.
Archived memberships do not show in `"$R" query group`, so take the id from the build that removed the member, or ask the requester for it.
`"is_archived": true` is refused, because the flag alone archives with no date.
Use `remove_group_member` and let Rock choose.
For someone who steps back but stays in the group, set `status` to `inactive` instead.

### Group sync takes the roster over

`create_group_sync` hands the roster for one role to a data view. On its
schedule, Rock adds everyone the data view returns and **removes everyone it does
not** – including members added by hand, and including the person who set it up.

So check the current roster for that role first. If anyone in it would not come
back from the data view, say so and stop:

```
Sync plan: "Guest Services" (312), role Member <- data view "Active Adults" (71)

  Roster now: 14 Members
  Not returned by the data view: 3
             group sync will remove these three on its first run

Apply? [y/n]
```

Move those people to a role the sync does not own, or widen the data view, before
applying. A sync is also the wrong tool for a roster people maintain by hand; say
that rather than building one.

### Security roles

`is_security_role: true` makes the group grant permissions in Rock. Set it only
when the request is explicitly about access, and name it in the plan when you do.

## Small writes

Four writes are `query` subcommands rather than plan files. They still need the
plan and the yes:

```bash
"$R" query block 4821                            # see current values first
"$R" query block-set 4821 EnableDebug false

"$R" query person-create --first Jane --last Doe --email jane@example.org \
     [--connection-status <id>] [--record-status <id>] [--campus <id>]
"$R" query person-update 8842 Email=jane@example.org NickName=Janie
"$R" query exception-clear [--before YYYY-MM-DD] [--type "NullReference"] [--limit 500]
```

`person-create` makes a real person record, and a duplicate person is harder to
undo than almost anything else here – search for them first. `exception-clear`
deletes rows permanently; say how many it will delete and which type, and prefer
`--type` and `--before` over clearing the log wholesale.

## When no operation fits

Rock has hundreds of entities and these operations name a couple of dozen, so a
request eventually lands outside them – a group requirement, a page context, a
scheduled job. Guessing at an operation that does not exist is one wrong answer
and giving up is the other. `api_request` sends exactly one request, which you
write:

```bash
cat > /tmp/rock-plan.json <<'PLAN'
{
  "operation": "api_request",
  "request": {
    "method": "PATCH",
    "endpoint": "GroupRequirements/12",
    "body": {"MustMeetRequirementToAddMember": true}
  }
}
PLAN
"$R" build /tmp/rock-plan.json
```

Read the entity before you change it. `GET` is available here for that reason,
and it is how you learn the field names Rock actually uses:

```json
{"operation": "api_request",
 "request": {"method": "GET", "endpoint": "GroupRequirements/12"}}
```

Then:

- **`PATCH` changes some fields.** It sets what you send and leaves everything
  else alone. This is the verb for almost every edit.
- **`PUT` replaces the entity.** Rock copies every column out of your body, so a
  field you omitted becomes null, the created-by audit is gone, and the row gets a
  new Guid. `api_request` refuses a `PUT` without `"full_replace": true`, and that
  acknowledgement is only honest when the body is the entity you just read back
  whole – `Id`, `Guid`, `CreatedDateTime` and all. If you are reaching for it to
  change two fields, reach for `PATCH` instead.
- **A `PUT` writes the old row to disk first**, under the runtime's `snapshots/`
  directory, and does not go at all if that read fails. Report the path it
  prints – it is the only way back.
- **`PATCH` and `PUT` both need a non-empty body.** An empty `PATCH` changes
  nothing and would report success; an empty `PUT` nulls every column.
- **Show the request in the plan** – method, URL, body – before sending it. Every
  other operation has a shape a reader can check against a table. This one has
  none, so the requester is the only check there is.

`params` is an object that goes to Rock as the query string, with any method.
Some of Rock's routes read their input only from there.
Clearing one attribute value on a person is one of them, and the attribute's key goes in `params`:

```json
{"operation": "api_request",
 "request": {"method": "DELETE", "endpoint": "People/AttributeValue/8842",
             "params": {"attributeKey": "Allergy"}}}
```

A `GET` takes Rock's OData options the same way, such as `{"$filter": "GroupId eq 312"}`.

## Verify, and report partial failure honestly

Re-query, or re-run the audit, and quote what came back rather than restating the
plan:

```bash
"$R" query audit "Volunteer Signup"
"$R" query group 312
```

The build script reports one line per step and stops at the first write that fails.
Nothing rolls back, so every ✓ above the ✗ stays in Rock:

```
Build results:
  ✓ WorkflowType: Volunteer Signup (id: 4001)
  ✓ Attribute: Email (id: 4101)
  ✗ Attribute: Notes -- Rock API HTTP 400 on POST Attributes: {
      "Message": "The request is invalid."
    }

Stopped at the failure. The steps marked ✓ are in Rock, and nothing after the failure was attempted.
```

A partial create leaves a half-built workflow in Rock under a real name. Name it
and say what it is missing, so someone finishes or deletes it rather than finding
it later and assuming it works. Then stop and hand it back – an inconsistent
workflow someone knows about beats a "clean" one rebuilt from guesses.

`create_workflow`, `create_page` and `create_checkin_area` look up every name in the plan before their first write: the category, each field type, action type and block type, the layout, the parent page's route, and a check-in group's area and rooms.
They also check that no two attributes share a key, that each attribute a form shows is one the workflow defines, and that no room is listed twice.
A name Rock does not have fails the build rather than warning about it, and the report lists every problem with nothing written:

```
Build results:
  ✗ Attribute: Notes -- no 'field_type' matches 'Txet'
  ✗ ActionType: Confirm -- no 'action_type' matches 'Send Emial'

Nothing was applied.
```

There is no `Warning:` line to read: each step in the report is a ✓ or a ✗, and a ✗ means that part of the plan is not in Rock.

The one exception is a ✗ from a dropped connection or a timeout, because the request may have reached Rock before its answer was lost.
Re-query for that step as well before you say what the build is missing.

Newly created workflows commonly audit dirty on the first pass: an activity
nothing activates, an email with no body yet. Better to find that now.

Done when what you hand back accounts for every part of the plan, built, failed or never attempted, and quotes the re-query.
The build report leaves out the parts it never attempted, so those come from the plan itself.
