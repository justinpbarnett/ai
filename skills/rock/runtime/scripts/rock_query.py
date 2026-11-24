import argparse
import datetime
import json
import sys
import traceback

from rock_client import (RockApiError, RockClient, RockNotFound, api_errors_reported, odata_str,
                         refuse_unless_writes_enabled)
from rock_log import get_logger
from rock_text import plural

log = get_logger("rock.query")

CONNECTION_STATES = {0: "Active", 1: "Inactive", 2: "Future", 3: "Connected"}
CONNECTION_STATE_FILTER = {v.lower(): k for k, v in CONNECTION_STATES.items()}
GENDERS = {1: "Male", 2: "Female"}
GROUP_MEMBER_STATUSES = {0: "Inactive", 1: "Active", 2: "Pending"}
EXPRESSION_TYPES = {0: "Filter", 1: "GroupAll", 2: "GroupAny", 3: "GroupAllFalse", 4: "GroupAnyFalse"}
FAMILY_GROUP_TYPE_ID = 10
KNOWN_RELATIONSHIPS_GROUP_TYPE_ID = 11
SEARCH_LIMIT = 10
CHOOSER_LIMIT = 5
CHILD_LIMIT = 200
CHILD_HINT = "this view has no --limit"
CHOOSER_HINT = "narrow it, or pass the ID"
WIDEN = "narrow the term or list that entity directly"
CHECKIN_TEMPLATE_PURPOSE = "4a406cb0-495b-4795-b788-52bdfde00b01"
CHECKIN_FILTER_PURPOSE = "6bced84c-69ad-4f5a-9197-5c0f9c02dd34"


# Rock 400s a $filter past 100 nodes. Measured: 15 ids beside a substringof pass, 20 fail.
TYPE_CHUNK = 15


def groups_of_types(client, name_filter, type_ids, limit):
    """Types are filtered in the query: filtering after the cap drops real matches."""
    seen, rows = set(), []
    for i in range(0, len(type_ids), TYPE_CHUNK):
        types = " or ".join(f"GroupTypeId eq {t}" for t in type_ids[i:i + TYPE_CHUNK])
        for g in client.get("Groups", params={
            "$filter": f"{name_filter} and ({types})",
            "$select": "Id,Name,IsActive,GroupTypeId",
            "$top": limit + 1,
        }) or []:
            if g["Id"] not in seen:
                seen.add(g["Id"])
                rows.append(g)
    return rows[:limit], len(rows) > limit


def get_capped(client, endpoint, params, limit):
    """Asks for limit + 1 rows: the extra one is what tells a cap from a total."""
    rows = client.get(endpoint, params={**params, "$top": limit + 1}) or []
    return rows[:limit], len(rows) > limit


def first(client, endpoint, params):
    rows = client.get(endpoint, params={**params, "$top": 1}) or []
    return rows[0] if rows else None


def tally(rows, more, hint="raise --limit"):
    return f"first {len(rows)} – more exist, {hint}" if more else str(len(rows))


def only_first(what):
    return f"(only the first {CHILD_LIMIT} {what} are shown)"


def _inactive(entity):
    return "" if entity.get("IsActive") else " [inactive]"


ID_WIDTH = 6
_LABEL_COLUMN = 2 + ID_WIDTH + 2
_DETAIL_INDENT = 2


def row(entity_id, label, indent=2):
    return f"{' ' * indent}{entity_id:{ID_WIDTH}d}  {label}"


class Listing:
    def __init__(self, title, more=False, hint="raise --limit", empty=None,
                 spaced=False):
        self.title = title
        self.more = more
        self.hint = hint
        self.empty = f"No {title.lower()} found." if empty is None else empty
        self.spaced = spaced
        self.rows = []

    def add(self, entity_id, label, *continued):
        self.rows.append((entity_id, label, [c for c in continued if c]))
        return self

    def render(self):
        if not self.rows:
            if self.empty:
                print(self.empty)
            return
        print(f"{self.title} ({tally(self.rows, self.more, self.hint)}):\n")
        for entity_id, label, continued in self.rows:
            print(row(entity_id, label))
            for line in continued:
                print(f"{' ' * _LABEL_COLUMN}{line}")
            if self.spaced:
                print()


class Section:
    def __init__(self, title, rows=None, more=False, hint="raise --limit"):
        self.title = title
        self.count = None if rows is None else tally(rows, more, hint)
        self.lines = []

    def add(self, text, depth=0):
        if text:
            self.lines.append((depth, text))
        return self

    def row(self, entity_id, label, depth=0):
        self.lines.append((depth, row(entity_id, label, indent=0)))
        return self


class Detail:
    def __init__(self, heading):
        self.heading = heading
        self.parts = []

    def field(self, label, value):
        """False and 0 are answers ("Active: False"); only None and "" drop out."""
        if value is None or value == "":
            return self
        return self.line(f"{label}: {value}")

    def line(self, text, depth=0):
        if text:
            self.parts.append((depth, text))
        return self

    def section(self, title, rows=None, more=False, hint="raise --limit"):
        made = Section(title, rows, more, hint)
        self.parts.append((0, made))
        return made

    def render(self):
        print(self.heading)
        for depth, part in self.parts:
            if isinstance(part, str):
                print(f"{' ' * (_DETAIL_INDENT + 2 * depth)}{part}")
                continue
            if not part.lines:
                continue
            title = part.title if part.count is None else f"{part.title} ({part.count})"
            print(f"{' ' * _DETAIL_INDENT}{title}:")
            for line_depth, text in part.lines:
                print(f"{' ' * (_DETAIL_INDENT + 2 + 2 * line_depth)}{text}")


class Raw:
    def __init__(self, entity):
        self.entity = entity

    def render(self):
        print(json.dumps(self.entity, indent=2))


class Text:
    def __init__(self, text):
        self.text = text

    def render(self):
        print(self.text)


def render(report):
    """No None branch: a forgotten return must crash, not print nothing."""
    parts = report if isinstance(report, list) else [report]
    for index, part in enumerate(parts):
        if index:
            print()
        part.render()


class LookupMiss(Exception):
    def __init__(self, report):
        self.report = report
        super().__init__("lookup miss")


def _resolve_name(client, endpoint, entity_id, field="Name"):
    if not entity_id:
        return "?"
    try:
        result = client.get(f"{endpoint}/{entity_id}", params={"$select": field})
        return result.get(field, "?")
    except RockNotFound as _e:
        log.debug("lookup failed: %s", _e)
        return "?"


def _resolve_person_name(client, alias_id, cache=None):
    if not alias_id:
        return "?"
    if cache is not None and alias_id in cache:
        return cache[alias_id]
    try:
        alias = client.get(f"PersonAlias/{alias_id}", params={"$select": "PersonId"})
        p = client.get(f"People/{alias['PersonId']}", params={"$select": "FirstName,LastName"})
        name = f"{p['FirstName']} {p['LastName']}"
    except RockNotFound as _e:
        log.debug("lookup failed: %s", _e)
        name = "?"
    if cache is not None:
        cache[alias_id] = name
    return name


def _find_entity(client, endpoint, identifier, name_field="Name", label=None,
                 search=None):
    label = label or endpoint.rstrip("s").lower()
    if search is None:
        def search(odata_filter, limit):
            return get_capped(client, endpoint, {"$filter": odata_filter}, limit)

    try:
        return client.get(f"{endpoint}/{int(identifier)}")
    except (ValueError, RockNotFound):
        pass

    exact, exact_more = search(f"{name_field} eq '{odata_str(identifier)}'",
                               CHOOSER_LIMIT)
    if len(exact) == 1:
        return exact[0]
    if exact:
        raise LookupMiss(_chooser(f"Multiple {label}s are named '{identifier}'",
                                  exact, exact_more, name_field))

    results, more = search(
        f"substringof('{odata_str(identifier)}', {name_field}) eq true",
        CHOOSER_LIMIT)
    if len(results) == 1:
        return results[0]
    if results:
        raise LookupMiss(_chooser(f"Multiple {label}s match '{identifier}'",
                                  results, more, name_field))
    raise LookupMiss(Text(f"No {label} found matching '{identifier}'"))


def _chooser(title, rows, more, name_field):
    chooser = Listing(title, more, hint=CHOOSER_HINT)
    for r in rows:
        chooser.add(r["Id"], r.get(name_field, "?"))
    return chooser


def _people_filter(identifier):
    if "@" in identifier:
        return f"Email eq '{odata_str(identifier)}'"
    parts = identifier.strip().split()
    if len(parts) >= 2:
        given = odata_str(" ".join(parts[:-1]))
        return (f"(FirstName eq '{given}' or NickName eq '{given}') and "
                f"LastName eq '{odata_str(parts[-1])}'")
    return f"LastName eq '{odata_str(parts[0])}'"


def _enrich_actions_entity_types(actions, client):
    eids = {a.get("EntityTypeId") for a in actions if a.get("EntityTypeId")}
    et_map = {}
    for eid in eids:
        try:
            et = client.get(f"EntityTypes/{eid}", params={"$select": "FriendlyName"})
            et_map[eid] = et
        except Exception as _e:
            log.debug("entity type lookup failed: %s", _e)
            et_map[eid] = {}
    for action in actions:
        action["EntityType"] = et_map.get(action.get("EntityTypeId"), {})


def format_workflow_tree(wf, category):
    lines = [f"{wf['Name']} (ID: {wf['Id']})"]
    desc = wf.get("Description", "")
    if desc:
        lines.append(f"  {desc[:120]}")
    lines.append(f"  Category: {category}")
    lines.append(f"  Active: {wf.get('IsActive', False)}")
    if wf.get("ActivityTypesCapped"):
        lines.append(f"  {only_first('activities')}")

    activities = _by_order(wf.get("ActivityTypes", []))
    for i, act in enumerate(activities):
        is_last_act = i == len(activities) - 1
        prefix = "└─" if is_last_act else "├─"
        branch = "   " if is_last_act else "│  "
        activated = " (activated with workflow)" if act.get("IsActivatedWithWorkflow") else ""
        lines.append(f"  {prefix} Activity: {act['Name']}{activated}")
        if act.get("ActionTypesCapped"):
            lines.append(f"  {branch} {only_first('actions')}")

        actions = _by_order(act.get("ActionTypes", []))
        for j, action in enumerate(actions):
            ap = "└─" if j == len(actions) - 1 else "├─"
            entity_name = action.get("EntityType", {}).get("FriendlyName", "?")
            lines.append(f"  {branch} {ap} Action: {action['Name']} [{entity_name}]")

    return "\n".join(lines)


def _by_order(items):
    return sorted(items, key=lambda a: a.get("Order", 0))


def _load_workflow_tree(wf, client):
    wf_id = wf["Id"]
    activities, activities_capped = get_capped(client, "WorkflowActivityTypes", {
        "$filter": f"WorkflowTypeId eq {wf_id}",
        "$orderby": "Order",
    }, CHILD_LIMIT)
    all_actions = []
    for act in activities:
        actions, actions_capped = get_capped(client, "WorkflowActionTypes", {
            "$filter": f"ActivityTypeId eq {act['Id']}",
            "$orderby": "Order",
        }, CHILD_LIMIT)
        act["ActionTypes"] = actions
        act["ActionTypesCapped"] = actions_capped
        all_actions.extend(actions)
    _enrich_actions_entity_types(all_actions, client)
    wf["ActivityTypes"] = activities
    wf["ActivityTypesCapped"] = activities_capped
    return wf


def _get_action_settings(client, action_id):
    try:
        action = client.get(f"WorkflowActionTypes/{action_id}", params={
            "loadAttributes": "simple",
        })
        attr_values = action.get("AttributeValues", {})
        flat = {}
        for k, v in attr_values.items():
            if isinstance(v, dict):
                flat[k] = v.get("Value", "")
            else:
                flat[k] = str(v) if v else ""
        return flat
    except Exception as e:
        print(f"  Warning: could not load settings for action {action_id}: {e}", file=sys.stderr)
        return None


def cmd_workflows(args, client):
    params = {
        "$select": "Id,Name,Description,IsActive,CategoryId",
        "$orderby": "Name",
    }
    if args.category:
        params["$filter"] = f"Category/Name eq '{odata_str(args.category)}'"

    workflows, more = get_capped(client, "WorkflowTypes", params, args.limit)

    cat_ids = {wf["CategoryId"] for wf in workflows if wf.get("CategoryId")}
    cat_names = {cid: _resolve_name(client, "Categories", cid) for cid in cat_ids}

    listing = Listing("Workflows", more)
    for wf in workflows:
        active = _inactive(wf)
        cat_name = cat_names.get(wf.get("CategoryId"), "")
        cat_str = f" ({cat_name})" if cat_name else ""
        listing.add(wf["Id"], f"{wf['Name']}{cat_str}{active}")
    return listing


def cmd_workflow(args, client):
    wf = _find_entity(client, "WorkflowTypes", args.identifier,
                      label="workflow")
    _load_workflow_tree(wf, client)
    if args.json:
        return Raw(wf)
    category = _resolve_name(client, "Categories", wf["CategoryId"]) if wf.get("CategoryId") else "none"
    return Text(format_workflow_tree(wf, category))


def cmd_pages(args, client):
    params = {
        "$select": "Id,InternalName,PageTitle,ParentPageId,LayoutId,IsSystem",
        "$orderby": "InternalName",
    }
    if args.site:
        params["$filter"] = f"Layout/SiteId eq {args.site}"

    pages, more = get_capped(client, "Pages", params, args.limit)

    listing = Listing("Pages", more)
    for p in pages:
        name = p.get("InternalName") or p.get("PageTitle") or "(untitled)"
        system = " [system]" if p.get("IsSystem") else ""
        listing.add(p["Id"], f"{name}{system}")
    return listing


def cmd_page(args, client):
    identifier = args.identifier

    page = None
    if not identifier.lstrip("-").isdigit():
        route = first(client, "PageRoutes", {
            "$filter": f"Route eq '{odata_str(identifier.lstrip('/'))}'",
        })
        if route and route.get("PageId"):
            page = client.get(f"Pages/{route['PageId']}")
    if not page:
        page = _find_entity(client, "Pages", identifier,
                            name_field="InternalName", label="page")

    blocks, blocks_capped = get_capped(client, "Blocks", {
        "$filter": f"PageId eq {page['Id']}",
        "$orderby": "Zone,Order",
    }, CHILD_LIMIT)
    if blocks:
        bt_ids = {b.get("BlockTypeId") for b in blocks if b.get("BlockTypeId")}
        bt_names = {btid: _resolve_name(client, "BlockTypes", btid) for btid in bt_ids}
        for b in blocks:
            b["BlockType"] = {"Name": bt_names.get(b.get("BlockTypeId"), "?")}

    routes, routes_capped = get_capped(client, "PageRoutes", {
        "$filter": f"PageId eq {page['Id']}",
        "$select": "Route",
    }, CHILD_LIMIT)

    if args.json:
        page["Blocks"] = blocks or []
        page["Routes"] = routes or []
        return Raw(page)

    name = page.get("InternalName") or page.get("PageTitle") or "(untitled)"
    detail = Detail(f"{name} (ID: {page['Id']})")
    if routes:
        shown = ", ".join("/" + r["Route"] for r in routes)
        detail.field("Routes", shown + (", ..." if routes_capped else ""))
    detail.field("Layout ID", page.get("LayoutId"))

    zones = detail.section("Blocks", blocks, blocks_capped, hint=CHILD_HINT)
    current_zone = None
    for b in blocks:
        zone = b.get("Zone", "Main")
        if zone != current_zone:
            current_zone = zone
            zones.add(f"Zone: {zone}")
        bt_name = b.get("BlockType", {}).get("Name", "?")
        zones.add(f"{b['Name'] or bt_name} [{bt_name}]", depth=1)
    return detail


def cmd_search(args, client):
    query = args.query
    print(f"Searching for '{query}'...\n")

    workflows, wf_more = get_capped(client, "WorkflowTypes", {
        "$filter": f"substringof('{odata_str(query)}', Name) eq true or substringof('{odata_str(query)}', Description) eq true",
        "$select": "Id,Name,IsActive",
    }, SEARCH_LIMIT)
    wf_listing = Listing("Workflows", wf_more, WIDEN, empty="")
    for wf in workflows:
        wf_listing.add(wf["Id"], wf["Name"])

    pages, pg_more = get_capped(client, "Pages", {
        "$filter": f"substringof('{odata_str(query)}', InternalName) eq true or substringof('{odata_str(query)}', PageTitle) eq true",
        "$select": "Id,InternalName,PageTitle",
    }, SEARCH_LIMIT)
    pg_listing = Listing("Pages", pg_more, WIDEN, empty="")
    for p in pages:
        name = p.get("InternalName") or p.get("PageTitle") or "(untitled)"
        pg_listing.add(p["Id"], name)

    dvs, dv_more = get_capped(client, "DataViews", {
        "$filter": f"substringof('{odata_str(query)}', Name) eq true",
        "$select": "Id,Name",
    }, SEARCH_LIMIT)
    dv_listing = Listing("Data Views", dv_more, WIDEN, empty="")
    for dv in dvs:
        dv_listing.add(dv["Id"], dv["Name"])

    groups, gp_more = get_capped(client, "Groups", {
        "$filter": f"substringof('{odata_str(query)}', Name) eq true and GroupTypeId ne {FAMILY_GROUP_TYPE_ID} and GroupTypeId ne {KNOWN_RELATIONSHIPS_GROUP_TYPE_ID}",
        "$select": "Id,Name",
    }, SEARCH_LIMIT)
    gp_listing = Listing("Groups", gp_more, WIDEN, empty="")
    for g in groups:
        gp_listing.add(g["Id"], g["Name"])

    found = [part for part in (wf_listing, pg_listing, dv_listing, gp_listing)
             if part.rows]
    return found or Listing("Results", empty="No results found.")


def _check_email(action, activity, settings, issues):
    prefix = f"Action '{action['Name']}' in '{activity['Name']}'"
    if not settings.get("To") and not settings.get("SendToEmailAddresses"):
        issues.append(f"{prefix}: SendEmail has no recipient")
    if not settings.get("Subject"):
        issues.append(f"{prefix}: SendEmail has no Subject")
    if not settings.get("Body"):
        issues.append(f"{prefix}: SendEmail has no Body")


def _check_sms(action, activity, settings, issues):
    prefix = f"Action '{action['Name']}' in '{activity['Name']}'"
    if not settings.get("To") and not settings.get("Recipient"):
        issues.append(f"{prefix}: SendSms has no recipient")
    if not settings.get("Message") and not settings.get("Body"):
        issues.append(f"{prefix}: SendSms has no message body")


def _audit_report(wf, issues, warnings):
    lines = [f"Audit: {wf['Name']} (ID: {wf['Id']})",
             f"Status: {'Active' if wf.get('IsActive') else 'Inactive'}", ""]

    activities = _by_order(wf.get("ActivityTypes", []))
    if activities:
        lines.append("Structure:")
        if wf.get("ActivityTypesCapped"):
            lines.append(f"  {only_first('activities')}")
        for i, act in enumerate(activities):
            is_last = i == len(activities) - 1
            prefix = "  └─" if is_last else "  ├─"
            branch = "     " if is_last else "  │  "
            activated = " (activated)" if act.get("IsActivatedWithWorkflow") else ""
            actions = _by_order(act.get("ActionTypes", []))
            if act.get("ActionTypesCapped"):
                count = f"over {CHILD_LIMIT} actions"
            else:
                count = plural(len(actions), "action")
            lines.append(f"{prefix} {act['Name']}{activated} [{count}]")
            if act.get("ActionTypesCapped"):
                lines.append(f"{branch} {only_first('actions')}")
            for j, action in enumerate(actions):
                ap = "└─" if j == len(actions) - 1 else "├─"
                entity_name = (action.get("EntityType") or {}).get("FriendlyName", "?")
                lines.append(f"{branch} {ap} {action['Name']} [{entity_name}]")
        lines.append("")

    for title, marker, found in (("Issues", "✗", issues),
                                 ("Warnings", "!", warnings)):
        if found:
            lines.append(f"{title} ({len(found)}):")
            lines.extend(f"  {marker} {item}" for item in found)
            lines.append("")

    if not issues and not warnings:
        lines.append("✓ No issues found")
    return Text("\n".join(lines).rstrip("\n"))


def _is_reached(activity, reachable):
    if activity.get("IsActivatedWithWorkflow"):
        return True
    identities = {str(activity["Id"]), str(activity.get("Guid") or "").lower()}
    return bool(identities & reachable)


def cmd_audit(args, client):
    wf = _find_entity(client, "WorkflowTypes", args.identifier,
                      label="workflow")
    _load_workflow_tree(wf, client)

    issues = []
    warnings = []

    if not wf.get("IsActive"):
        warnings.append("Workflow is inactive")

    activities = _by_order(wf.get("ActivityTypes", []))

    if not activities:
        issues.append("Workflow has no activities")
        return _audit_report(wf, issues, warnings)

    if not activities[0].get("IsActivatedWithWorkflow"):
        issues.append(f"First activity '{activities[0]['Name']}' is not activated with workflow")

    act_orders = [a.get("Order", 0) for a in activities]
    if len(act_orders) != len(set(act_orders)):
        issues.append(f"Duplicate activity orders: {act_orders}")

    reachable = set()
    for act in activities:
        if act.get("IsActivatedWithWorkflow"):
            reachable.add(str(act["Id"]))

    for act in activities:
        actions = _by_order(act.get("ActionTypes", []))

        if not actions:
            issues.append(f"Activity '{act['Name']}' (ID: {act['Id']}) has no actions")
            continue

        action_orders = [a.get("Order", 0) for a in actions]
        if len(action_orders) != len(set(action_orders)):
            issues.append(f"Duplicate action orders in '{act['Name']}': {action_orders}")

        for i, action in enumerate(actions):
            entity = action.get("EntityType") or {}
            entity_name = entity.get("FriendlyName", "")

            if not action.get("EntityTypeId") and not entity_name:
                issues.append(
                    f"Action '{action['Name']}' in '{act['Name']}' has no action type (broken reference)"
                )
                continue

            if action.get("IsActivityCompletedOnSuccess") and i < len(actions) - 1:
                warnings.append(
                    f"Action '{action['Name']}' completes activity but isn't last in '{act['Name']}'"
                )

            settings = None

            if entity_name and "activate" in entity_name.lower():
                settings = _get_action_settings(client, action["Id"])
                if settings:
                    for key in ("Activity", "ActivityType", "ActivityTypeGuid"):
                        val = settings.get(key, "")
                        if val:
                            reachable.add(str(val).lower())

            if not args.skip_settings and entity_name:
                name_lower = entity_name.lower().replace(" ", "")
                if "sendemail" in name_lower or "sendsms" in name_lower:
                    if settings is None:
                        settings = _get_action_settings(client, action["Id"])
                    if settings is not None:
                        if "sendemail" in name_lower:
                            _check_email(action, act, settings, issues)
                        else:
                            _check_sms(action, act, settings, issues)

    for act in activities:
        if not _is_reached(act, reachable):
            warnings.append(f"Activity '{act['Name']}' (ID: {act['Id']}) may be unreachable")

    return _audit_report(wf, issues, warnings)


def cmd_actions(args, client):
    act = client.get(f"WorkflowActivityTypes/{args.activity_id}")

    actions, actions_capped = get_capped(client, "WorkflowActionTypes", {
        "$filter": f"ActivityTypeId eq {args.activity_id}",
        "$orderby": "Order",
    }, CHILD_LIMIT)
    _enrich_actions_entity_types(actions, client)

    detail = Detail(f"Activity: {act['Name']} (ID: {act['Id']})")
    detail.field("Activated with workflow",
                 act.get("IsActivatedWithWorkflow", False))
    detail.field("Actions", tally(actions, actions_capped, hint=CHILD_HINT))

    for action in actions:
        entity = action.get("EntityType") or {}
        detail.line(f"[{action.get('Order', '?')}] {action['Name']} "
                    f"(ID: {action['Id']})")
        detail.line(f"Type: {entity.get('FriendlyName', '?')}", depth=1)
        detail.line(f"Completes action: "
                    f"{action.get('IsActionCompletedOnSuccess', False)}", depth=1)
        detail.line(f"Completes activity: "
                    f"{action.get('IsActivityCompletedOnSuccess', False)}", depth=1)
        settings = _get_action_settings(client, action["Id"])
        if settings:
            detail.line("Settings:", depth=1)
            for k, v in settings.items():
                val = str(v)[:120] + ("..." if len(str(v)) > 120 else "")
                detail.line(f"{k}: {val}", depth=2)
    return detail


def cmd_attributes(args, client):
    wf = _find_entity(client, "WorkflowTypes", args.identifier,
                      label="workflow")

    attrs, attrs_capped = get_capped(client, "Attributes", {
        "$filter": f"EntityTypeQualifierColumn eq 'WorkflowTypeId' and EntityTypeQualifierValue eq '{wf['Id']}'",
        "$orderby": "Order",
    }, CHILD_LIMIT)

    if not attrs:
        return Text(f"No attributes on '{wf['Name']}' (ID: {wf['Id']})")

    ft_ids = {a.get("FieldTypeId") for a in attrs if a.get("FieldTypeId")}
    ft_names = {fid: _resolve_name(client, "FieldTypes", fid) for fid in ft_ids}

    detail = Detail(f"Attributes on '{wf['Name']}' (ID: {wf['Id']}, "
                    f"{tally(attrs, attrs_capped, hint=CHILD_HINT)}):")
    for attr in attrs:
        ft = ft_names.get(attr.get("FieldTypeId"), "?")
        req = " [required]" if attr.get("IsRequired") else ""
        grid = " [grid]" if attr.get("IsGridColumn") else ""
        detail.line(f"{attr.get('Order', '?'):3}  {attr['Key']} ({ft}){req}{grid}")
        # Two steps in, so a description cannot be misread as the next attribute.
        detail.line((attr.get("Description") or "")[:100], depth=2)
    return detail


def cmd_dataviews(args, client):
    params = {
        "$select": "Id,Name,Description,EntityTypeId,CategoryId",
        "$orderby": "Name",
    }
    if args.category:
        params["$filter"] = f"substringof('{odata_str(args.category)}', Category/Name) eq true"

    dvs, more = get_capped(client, "DataViews", params, args.limit)

    cat_ids = {dv["CategoryId"] for dv in dvs if dv.get("CategoryId")}
    cat_names = {cid: _resolve_name(client, "Categories", cid) for cid in cat_ids}

    listing = Listing("Data Views", more)
    for dv in dvs:
        cat_name = cat_names.get(dv.get("CategoryId"), "")
        cat_str = f" ({cat_name})" if cat_name else ""
        listing.add(dv["Id"], f"{dv['Name']}{cat_str}")
    return listing


def _load_filter_tree(client, filter_id, depth=0):
    f = client.get(f"DataViewFilters/{filter_id}")

    entity_name = _resolve_name(client, "EntityTypes", f.get("EntityTypeId"),
                                field="FriendlyName")
    prefix = "  " * depth
    expr = EXPRESSION_TYPES.get(f.get("ExpressionType", 0), f"Type:{f.get('ExpressionType')}")

    lines = []
    if f.get("ExpressionType", 0) in (1, 2, 3, 4):
        lines.append(f"{prefix}[{expr}]")
    else:
        selection = f.get("Selection", "") or ""
        sel_short = selection[:120] + ("..." if len(selection) > 120 else "")
        related_dv = f.get("RelatedDataViewId")
        dv_note = f" (references DataView:{related_dv})" if related_dv else ""
        lines.append(f"{prefix}Filter [{entity_name}]: {sel_short}{dv_note}")

    children, children_capped = get_capped(client, "DataViewFilters", {
        "$filter": f"ParentId eq {filter_id}",
        "$select": "Id",
    }, CHILD_LIMIT)
    if children_capped:
        lines.append(f"{prefix}{only_first('child filters')}")
    for child in children:
        lines.extend(_load_filter_tree(client, child["Id"], depth + 1))

    return lines


def cmd_dataview(args, client):
    dv = _find_entity(client, "DataViews", args.identifier, label="data view")
    if args.json:
        return Raw(dv)

    detail = Detail(f"{dv['Name']} (ID: {dv['Id']})")
    detail.line((dv.get("Description") or "")[:200])
    detail.field("Entity", _resolve_name(client, "EntityTypes",
                                        dv.get("EntityTypeId"),
                                        field="FriendlyName"))
    if dv.get("TransformEntityTypeId"):
        detail.field("Transform", _resolve_name(
            client, "EntityTypes", dv["TransformEntityTypeId"],
            field="FriendlyName"))
    if dv.get("CategoryId"):
        cat_name = _resolve_name(client, "Categories", dv["CategoryId"])
        if cat_name != "?":
            detail.field("Category", cat_name)

    persisted = dv.get("PersistedScheduleIntervalMinutes")
    if persisted:
        detail.field("Persisted", f"every {persisted} min (last: "
                                  f"{dv.get('PersistedLastRefreshDateTime', 'never')})")
    detail.field("Last run", f"{dv.get('LastRunDateTime', 'never')} "
                             f"({dv.get('TimeToRunDurationMilliseconds', 0)}ms)")

    filter_id = dv.get("DataViewFilterId")
    if filter_id:
        filters = detail.section("Filters")
        for line in _load_filter_tree(client, filter_id):
            filters.add(line)
    return detail


def cmd_person(args, client):
    return _person_detail(_find_person(client, args.identifier), client)


def _find_person(client, identifier):
    try:
        return client.get(f"People/{int(identifier)}")
    except (ValueError, RockNotFound):
        pass

    results, more = get_capped(client, "People",
                               {"$filter": _people_filter(identifier)},
                               SEARCH_LIMIT)

    if not results:
        raise LookupMiss(Text(f"No person found matching '{identifier}'"))

    if len(results) == 1:
        return results[0]

    listing = Listing(f"People matching '{identifier}'", more,
                      hint=CHOOSER_HINT)
    campus_cache = {}
    for p in results:
        email = f" ({p.get('Email', '')})" if p.get("Email") else ""
        campus = ""
        if p.get("PrimaryCampusId"):
            cid = p["PrimaryCampusId"]
            if cid not in campus_cache:
                campus_cache[cid] = _resolve_name(client, "Campuses", cid)
            if campus_cache[cid] != "?":
                campus = f" [{campus_cache[cid]}]"
        listing.add(p["Id"], f"{p.get('FirstName', '')} {p.get('LastName', '')}"
                             f"{email}{campus}")
    raise LookupMiss(listing)


def _person_heading(person):
    return f"{person.get('FirstName', '')} {person.get('LastName', '')} (ID: {person['Id']})"


def _person_detail(person, client):
    detail = Detail(_person_heading(person))
    detail.field("Email", person.get("Email"))
    if person.get("Gender"):
        detail.field("Gender", GENDERS.get(person["Gender"], "Unknown"))
    if person.get("BirthDate"):
        detail.field("DOB", person["BirthDate"][:10])

    for label, key, endpoint, name_field in (
            ("Connection Status", "ConnectionStatusValueId", "DefinedValues", "Value"),
            ("Record Status", "RecordStatusValueId", "DefinedValues", "Value"),
            ("Campus", "PrimaryCampusId", "Campuses", "Name")):
        if person.get(key):
            resolved = _resolve_name(client, endpoint, person[key], field=name_field)
            if resolved != "?":
                detail.field(label, resolved)

    role_cache = {}
    try:
        families = client.get(f"Groups/GetFamilies/{person['Id']}")
        for fam in families or []:
            members, members_capped = get_capped(client, "GroupMembers", {
                "$filter": f"GroupId eq {fam['Id']}",
                "$select": "PersonId,GroupRoleId",
            }, CHILD_LIMIT)
            roles = {}
            for m in members:
                rid = m["GroupRoleId"]
                if rid not in role_cache:
                    role_cache[rid] = _resolve_name(client, "GroupTypeRoles", rid)
                roles[m["PersonId"]] = role_cache[rid]
            capped = f" (first {CHILD_LIMIT})" if members_capped else ""
            detail.field("Family", f"{fam['Name']} (ID: {fam['Id']}){capped}")
            for m in members:
                if m["PersonId"] == person["Id"]:
                    continue
                try:
                    p = client.get(f"People/{m['PersonId']}",
                                   params={"$select": "FirstName,LastName"})
                    detail.line(f"{roles.get(m['PersonId'], '?'):10s} "
                                f"{p['FirstName']} {p['LastName']}", depth=1)
                except RockNotFound as _e:
                    log.debug("lookup failed: %s", _e)
    except RockNotFound as _e:
        log.debug("lookup failed: %s", _e)

    try:
        rel_group = first(client, "Groups", {
            "$filter": f"GroupTypeId eq {KNOWN_RELATIONSHIPS_GROUP_TYPE_ID} and Members/any(m: m/PersonId eq {person['Id']})",
            "$select": "Id",
        })
        if rel_group:
            members, members_capped = get_capped(client, "GroupMembers", {
                "$filter": f"GroupId eq {rel_group['Id']} and PersonId ne {person['Id']}",
                "$select": "PersonId,GroupRoleId",
            }, CHILD_LIMIT)
            related = detail.section("Known Relationships", members,
                                     members_capped, hint=CHILD_HINT)
            for m in members:
                try:
                    p = client.get(f"People/{m['PersonId']}",
                                   params={"$select": "FirstName,LastName"})
                    pname = f"{p['FirstName']} {p['LastName']}"
                    rid = m["GroupRoleId"]
                    if rid not in role_cache:
                        role_cache[rid] = _resolve_name(client, "GroupTypeRoles", rid)
                    related.add(f"{role_cache[rid]:20s} {pname}")
                except RockNotFound as _e:
                    log.debug("lookup failed: %s", _e)
    except RockNotFound as _e:
        log.debug("lookup failed: %s", _e)

    return detail


def cmd_group(args, client):
    group = _find_entity(client, "Groups", args.identifier, label="group")
    if args.json:
        return Raw(group)

    detail = Detail(f"{group['Name']} (ID: {group['Id']})")
    detail.line((group.get("Description") or "")[:200])
    if group.get("GroupTypeId"):
        gt_name = _resolve_name(client, "GroupTypes", group["GroupTypeId"])
        if gt_name != "?":
            detail.field("Type", gt_name)
    detail.field("Active", group.get("IsActive", False))
    for label, key, endpoint in (("Campus", "CampusId", "Campuses"),
                                 ("Schedule", "ScheduleId", "Schedules")):
        if group.get(key):
            resolved = _resolve_name(client, endpoint, group[key])
            if resolved != "?":
                detail.field(label, resolved)

    members, mem_more = get_capped(client, "GroupMembers", {
        "$filter": f"GroupId eq {group['Id']}",
        "$select": "PersonId,GroupRoleId,GroupMemberStatus",
    }, args.limit)
    roster = detail.section("Members", members, mem_more)
    role_cache = {}
    for m in members:
        rid = m.get("GroupRoleId")
        if rid not in role_cache:
            role_cache[rid] = _resolve_name(client, "GroupTypeRoles", rid)
        try:
            p = client.get(f"People/{m['PersonId']}",
                           params={"$select": "FirstName,LastName"})
            pname = f"{p['FirstName']} {p['LastName']}"
        except RockNotFound as _e:
            log.debug("person lookup failed: %s", _e)
            pname = f"ID:{m['PersonId']}"
        status = GROUP_MEMBER_STATUSES.get(m.get("GroupMemberStatus"), "?")
        roster.add(f"{pname:30s} {role_cache[rid]:15s} [{status}]")
    return detail


def cmd_report(args, client):
    report = _find_entity(client, "Reports", args.identifier, label="report")
    if args.json:
        return Raw(report)

    detail = Detail(f"{report['Name']} (ID: {report['Id']})")
    detail.line((report.get("Description") or "")[:200])

    if report.get("DataViewId"):
        dv_name = _resolve_name(client, "DataViews", report["DataViewId"])
        if dv_name != "?":
            detail.field("Data View", f"{dv_name} (ID: {report['DataViewId']})")
        else:
            detail.field("Data View ID", report["DataViewId"])

    if report.get("CategoryId"):
        cat_name = _resolve_name(client, "Categories", report["CategoryId"])
        if cat_name != "?":
            detail.field("Category", cat_name)

    fields, fields_capped = get_capped(client, "ReportFields", {
        "$filter": f"ReportId eq {report['Id']}",
        "$select": "ReportFieldType,ShowInGrid,ColumnOrder,ColumnHeaderText,DataSelectComponentEntityTypeId",
    }, CHILD_LIMIT)
    columns = detail.section("Fields", fields, fields_capped, hint=CHILD_HINT)
    for f in sorted(fields, key=lambda x: x.get("ColumnOrder", 0)):
        header = f.get("ColumnHeaderText", "") or "(no header)"
        columns.add(f"{f.get('ColumnOrder', '?'):3}  {header}")
    return detail


def _short_type(exception_type):
    return exception_type.split(".")[-1] if "." in exception_type else exception_type


def cmd_exceptions(args, client):
    params = {"$orderby": "CreatedDateTime desc"}
    if args.type:
        params["$filter"] = f"substringof('{odata_str(args.type)}', ExceptionType) eq true"

    exceptions, more = get_capped(client, "ExceptionLogs", params, args.limit)

    if args.summary:
        if not exceptions:
            return Text("No exceptions found.")
        counts = {}
        for ex in exceptions:
            short = _short_type(ex.get("ExceptionType", "Unknown"))
            counts[short] = counts.get(short, 0) + 1
        window = f"{len(exceptions)} most recent" + (" of more" if more else "")
        summary = Detail(f"Exception summary ({window}):")
        for etype, count in sorted(counts.items(), key=lambda x: -x[1]):
            summary.line(f"{count:4d}  {etype}")
        return summary

    listing = Listing("Exceptions", more, spaced=True)
    for ex in exceptions:
        dt = (ex.get("CreatedDateTime") or "")[:19]
        desc = (ex.get("Description") or "")[:120]
        url = ex.get("PageUrl", "")
        trace = ex["StackTrace"].split("\n")[:5] if (
            args.verbose and ex.get("StackTrace")) else []
        listing.add(ex["Id"], f"[{dt}] {_short_type(ex.get('ExceptionType', 'Unknown'))}",
                    desc, f"URL: {url}" if url else "",
                    *(line.strip() for line in trace))
    return listing


def cmd_exception(args, client):
    ex = client.get(f"ExceptionLogs/{args.id}")

    if args.json:
        return Raw(ex)

    dt = (ex.get("CreatedDateTime") or "")[:19]
    detail = Detail(f"Exception {ex['Id']} ({dt})")
    detail.field("Type", ex.get("ExceptionType", "Unknown"))
    detail.field("HTTP Status", ex.get("StatusCode"))
    detail.field("Source", ex.get("Source"))
    detail.field("Description", ex.get("Description"))
    detail.field("URL", ex.get("PageUrl"))

    if ex.get("StackTrace"):
        trace = detail.section("Stack Trace")
        for line in ex["StackTrace"].split("\n")[:15]:
            trace.add(line.strip())

    if ex.get("HasInnerException") and ex.get("Id"):
        inner = first(client, "ExceptionLogs", {
            "$filter": f"ParentId eq {ex['Id']}",
        })
        if inner:
            detail.field("Inner Exception", inner.get("ExceptionType", "?"))
            detail.line((inner.get("Description") or "")[:200], depth=1)
    return detail


def cmd_schedules(args, client):
    params = {
        "$select": "Id,Name,IsActive",
        "$orderby": "Name",
    }
    filters = []
    if args.active:
        filters.append("IsActive eq true")
    if args.query:
        filters.append(f"substringof('{odata_str(args.query)}', Name) eq true")
    if filters:
        params["$filter"] = " and ".join(filters)

    schedules, more = get_capped(client, "Schedules", params, args.limit)

    listing = Listing("Schedules", more)
    for s in schedules:
        active = _inactive(s)
        listing.add(s["Id"], f"{s['Name']}{active}")
    return listing


def cmd_schedule(args, client):
    schedule = _find_entity(client, "Schedules", args.identifier, label="schedule")
    if args.json:
        return Raw(schedule)

    detail = Detail(f"{schedule['Name']} (ID: {schedule['Id']})")
    detail.field("Active", schedule.get("IsActive", False))
    detail.field("Description", (schedule.get("Description") or "")[:200])
    for label, key in (("Start", "EffectiveStartDate"), ("End", "EffectiveEndDate")):
        if schedule.get(key):
            detail.field(label, schedule[key][:10])
    if schedule.get("CheckInStartOffsetMinutes"):
        detail.field("Check-in window",
                     f"-{schedule['CheckInStartOffsetMinutes']}min to "
                     f"+{schedule.get('CheckInEndOffsetMinutes', 0)}min")
    if schedule.get("CategoryId"):
        cat_name = _resolve_name(client, "Categories", schedule["CategoryId"])
        if cat_name != "?":
            detail.field("Category", cat_name)
    return detail


def cmd_registrations(args, client):
    params = {
        "$select": "Id,Name,StartDateTime,EndDateTime,MaxAttendees,IsActive,RegistrationTemplateId",
        "$orderby": "StartDateTime desc",
    }
    filters = []
    if args.active:
        filters.append("IsActive eq true")
    if args.query:
        filters.append(f"substringof('{odata_str(args.query)}', Name) eq true")
    if filters:
        params["$filter"] = " and ".join(filters)

    regs, more = get_capped(client, "RegistrationInstances", params, args.limit)

    listing = Listing("Registration Instances", more)
    for r in regs:
        active = _inactive(r)
        start = (r.get("StartDateTime") or "")[:10]
        end = (r.get("EndDateTime") or "")[:10]
        date_range = f" ({start} to {end})" if start else ""
        max_att = f" [max: {r['MaxAttendees']}]" if r.get("MaxAttendees") else ""
        listing.add(r["Id"], f"{r['Name']}{active}{date_range}{max_att}")
    return listing


def cmd_registration(args, client):
    reg = _find_entity(client, "RegistrationInstances", args.identifier, label="registration")
    if args.json:
        return Raw(reg)

    detail = Detail(f"{reg['Name']} (ID: {reg['Id']})")
    detail.field("Active", reg.get("IsActive", False))
    for label, key in (("Start", "StartDateTime"), ("End", "EndDateTime")):
        if reg.get(key):
            detail.field(label, reg[key][:19])
    detail.field("Max Attendees", reg.get("MaxAttendees"))
    if reg.get("Cost"):
        detail.field("Cost", f"${reg['Cost']}")
    detail.field("Contact", reg.get("ContactEmail"))

    if reg.get("RegistrationTemplateId"):
        tmpl_name = _resolve_name(client, "RegistrationTemplates",
                                  reg["RegistrationTemplateId"])
        if tmpl_name != "?":
            detail.field("Template",
                         f"{tmpl_name} (ID: {reg['RegistrationTemplateId']})")
        else:
            detail.field("Template ID", reg["RegistrationTemplateId"])

    if reg.get("RegistrationWorkflowTypeId"):
        wf_name = _resolve_name(client, "WorkflowTypes",
                               reg["RegistrationWorkflowTypeId"])
        if wf_name != "?":
            detail.field("Workflow",
                         f"{wf_name} (ID: {reg['RegistrationWorkflowTypeId']})")

    detail.field("Details", (reg.get("Details") or "")[:200])
    return detail


def cmd_connections(args, client):
    params = {
        "$orderby": "CreatedDateTime desc",
    }
    filters = []
    if args.state:
        filters.append(f"ConnectionState eq {CONNECTION_STATE_FILTER[args.state]}")
    if args.opportunity:
        filters.append(f"substringof('{odata_str(args.opportunity)}', ConnectionOpportunity/Name) eq true")
    if filters:
        params["$filter"] = " and ".join(filters)

    requests, more = get_capped(client, "ConnectionRequests", params, args.limit)

    opp_cache = {}
    status_cache = {}
    person_cache = {}

    listing = Listing("Connection Requests", more, spaced=True)
    for cr in requests:
        dt = (cr.get("CreatedDateTime") or "")[:10]
        person = _resolve_person_name(client, cr.get("PersonAliasId"), person_cache)
        connector = _resolve_person_name(client, cr.get("ConnectorPersonAliasId"), person_cache) if cr.get("ConnectorPersonAliasId") else "unassigned"
        state = CONNECTION_STATES.get(cr.get("ConnectionState"), "?")

        opp_id = cr.get("ConnectionOpportunityId")
        if opp_id and opp_id not in opp_cache:
            opp_cache[opp_id] = _resolve_name(client, "ConnectionOpportunities", opp_id)
        opp_name = opp_cache.get(opp_id, "?")

        status_id = cr.get("ConnectionStatusId")
        if status_id and status_id not in status_cache:
            status_cache[status_id] = _resolve_name(client, "ConnectionStatuses", status_id)
        status_name = status_cache.get(status_id, "?")

        listing.add(cr["Id"], f"[{state:9s}] {person:25s} -> {connector}",
                    f"{opp_name} | {status_name} | {dt}",
                    (cr.get("Comments") or "")[:100])
    return listing


def cmd_block(args, client):
    block = client.get(f"Blocks/{args.id}", params={"loadAttributes": "simple"})

    if args.json:
        return Raw(block)

    detail = Detail(f"{block.get('Name', '(unnamed)')} (ID: {block['Id']})")
    if block.get("BlockTypeId"):
        bt_name = _resolve_name(client, "BlockTypes", block["BlockTypeId"])
        if bt_name != "?":
            detail.field("Block Type", bt_name)
    detail.field("Zone", block.get("Zone", "?"))
    detail.field("Order", block.get("Order", "?"))
    detail.field("Page ID", block.get("PageId"))

    values = {key: (val.get("Value") if isinstance(val, dict) else val) or ""
              for key, val in (block.get("AttributeValues") or {}).items()}
    set_keys = [key for key, v in values.items() if v]
    empty_keys = [key for key, v in values.items() if not v]
    settings = detail.section("Attributes", set_keys)
    for key in set_keys:
        v = str(values[key])
        max_len = 300 if key.lower() in ("query", "formattedoutput", "template",
                                         "lavatemplate") else 150
        settings.add(f"{key}: {v[:max_len]}" + ("..." if len(v) > max_len else ""))
    unset = detail.section("Attributes with no value", empty_keys)
    for key in empty_keys:
        unset.add(key)
    return detail


def cmd_bgc(args, client):
    params = {
        "$orderby": "RequestDate desc",
    }
    filters = []
    if args.status:
        filters.append(f"substringof('{odata_str(args.status)}', Status) eq true")
    person = _find_person(client, args.person) if args.person else None
    person_cache = {}
    aliases_capped = False
    if person:
        aliases, aliases_capped = get_capped(client, "PersonAlias", {
            "$filter": f"PersonId eq {person['Id']}", "$select": "Id",
        }, CHILD_LIMIT)
        either = " or ".join(f"PersonAliasId eq {alias['Id']}" for alias in aliases)
        filters.append(f"({either})")
        person_cache = dict.fromkeys((alias["Id"] for alias in aliases),
                                     f"{person['FirstName']} {person['LastName']}")
    if filters:
        params["$filter"] = " and ".join(filters)

    checks, more = get_capped(client, "BackgroundChecks", params, args.limit)

    listing = Listing("Background Checks", more)
    for bc in checks:
        req_date = (bc.get("RequestDate") or "")[:10]
        resp_date = (bc.get("ResponseDate") or "")[:10]
        name = _resolve_person_name(client, bc.get("PersonAliasId"), person_cache)
        status = bc.get("Status", "?")
        found = " [RECORD FOUND]" if bc.get("RecordFound") else ""
        pkg = bc.get("PackageName", "")
        pkg_str = f" ({pkg})" if pkg else ""

        listing.add(bc["Id"], f"{name:25s} [{status}]{found}{pkg_str}",
                    f"Requested: {req_date}  "
                    f"Responded: {resp_date or 'pending'}")
    report = [Text(_person_heading(person)), listing] if person else [listing]
    if aliases_capped:
        report.append(Text(f"(only the checks under the first {CHILD_LIMIT} "
                           f"of this person's aliases were searched)"))
    return report


def _checkin_purposes(client):
    values, _more = get_capped(client, "DefinedValues", {
        "$filter": (f"Guid eq guid'{CHECKIN_TEMPLATE_PURPOSE}' or "
                    f"Guid eq guid'{CHECKIN_FILTER_PURPOSE}'"),
        "$select": "Id,Guid",
    }, 2)
    ids = {v["Guid"].lower(): v["Id"] for v in values}
    return ids.get(CHECKIN_TEMPLATE_PURPOSE), ids.get(CHECKIN_FILTER_PURPOSE)


def _group_types_with_children(client, type_ids):
    """Each type is asked for itself, because a child's own ChildGroupTypes is not reliably filled."""
    loaded = {}
    for i in range(0, len(type_ids), TYPE_CHUNK):
        chunk = type_ids[i:i + TYPE_CHUNK]
        rows, _more = get_capped(client, "GroupTypes", {
            "$filter": " or ".join(f"Id eq {t}" for t in chunk),
            "$expand": "ChildGroupTypes",
        }, len(chunk))
        loaded.update((t["Id"], t) for t in rows)
    return loaded


def _checkin_templates(client):
    """Walks each template's areas the way Rock's Check-in Configuration page does."""
    template_purpose, filter_purpose = _checkin_purposes(client)
    if template_purpose is None:
        return [], False
    templates, capped = get_capped(client, "GroupTypes", {
        "$filter": f"GroupTypePurposeValueId eq {template_purpose}",
        "$expand": "ChildGroupTypes",
        "$orderby": "Order,Name",
    }, CHILD_LIMIT)
    loaded = {t["Id"]: t for t in templates}

    def children(type_id):
        found = [c for c in loaded.get(type_id, {}).get("ChildGroupTypes") or []
                 if c and c.get("GroupTypePurposeValueId") != filter_purpose]
        return sorted(found, key=lambda c: (c.get("Order", 0), c["Name"].casefold()))

    asked = set(loaded)
    wanted = {c["Id"] for t in templates for c in children(t["Id"])} - asked
    while wanted:
        asked |= wanted
        fresh = _group_types_with_children(client, sorted(wanted))
        loaded.update(fresh)
        wanted = {c["Id"] for type_id in fresh for c in children(type_id)} - asked

    def walk(type_id, shown):
        nodes = []
        for child in children(type_id):
            if child["Id"] in shown:
                continue
            shown.add(child["Id"])
            nodes.append((loaded.get(child["Id"], child), walk(child["Id"], shown)))
        return nodes

    return [(t, walk(t["Id"], {t["Id"]})) for t in templates], capped


def _areas_in(nodes):
    for area, children in nodes:
        yield area
        yield from _areas_in(children)


def _area_groups(client, area_id, cache):
    if area_id not in cache:
        cache[area_id] = get_capped(client, "Groups", {
            "$filter": f"GroupTypeId eq {area_id}",
            "$select": "Id,Name,IsActive,ParentGroupId",
            "$orderby": "Order,Name",
        }, CHILD_LIMIT)
    return cache[area_id]


def _group_rows(groups, indent):
    """A group whose parent is not among the area's groups is one of its roots."""
    ids = {g["Id"] for g in groups}
    by_parent = {}
    for g in groups:
        parent = g.get("ParentGroupId")
        by_parent.setdefault(parent if parent in ids else None, []).append(g)

    def rows_under(parent, depth):
        for g in by_parent.get(parent, []):
            yield row(g["Id"], f"{g['Name']}{_inactive(g)}", indent=indent + 2 * depth)
            yield from rows_under(g["Id"], depth + 1)

    return list(rows_under(None, 0))


def _area_lines(client, nodes, indent, cache):
    lines = []
    for area, child_areas in nodes:
        lines.append(f"{' ' * indent}Area: {area['Name']} (ID: {area['Id']})")
        lines.extend(_area_lines(client, child_areas, indent + 2, cache))
        groups, capped = _area_groups(client, area["Id"], cache)
        if capped:
            lines.append(f"{' ' * (indent + 2)}{only_first('groups')}")
        lines.extend(_group_rows(groups, indent + 2))
    return lines


def _checkin_group(args, client, templates, templates_capped):
    areas = {area["Id"]: area for _template, nodes in templates
             for area in _areas_in(nodes)}

    def in_areas(odata_filter, limit):
        return groups_of_types(client, odata_filter, sorted(areas), limit)

    try:
        group = _find_entity(client, "Groups", args.group, label="check-in group",
                             search=in_areas)
        area = areas.get(group.get("GroupTypeId"))
        if area is None:
            raise LookupMiss(Text(f"{group['Name']} (ID: {group['Id']}) is not in a check-in area"))
    except LookupMiss as miss:
        if not templates_capped:
            raise
        searched = Text(f"(only the areas of the first {CHILD_LIMIT} check-in templates were searched)")
        raise LookupMiss([miss.report, searched]) from None

    detail = Detail(f"{group['Name']} (ID: {group['Id']})")
    detail.field("Area", f"{area['Name']} (ID: {area['Id']})")
    detail.field("Active", group.get("IsActive", False))

    group_locs, locs_capped = get_capped(client, "GroupLocations", {
        "$filter": f"GroupId eq {group['Id']}",
        "$select": "LocationId",
    }, CHILD_LIMIT)
    places = detail.section("Locations", group_locs, locs_capped, hint=CHILD_HINT)
    for gl in group_locs:
        loc_name = _resolve_name(client, "Locations", gl["LocationId"])
        if loc_name != "?":
            places.add(f"{loc_name} (ID: {gl['LocationId']})")
        else:
            places.add(f"Location ID: {gl['LocationId']}")

    children, children_capped = get_capped(client, "Groups", {
        "$filter": f"ParentGroupId eq {group['Id']} and GroupTypeId eq {area['Id']}",
        "$select": "Id,Name,IsActive",
        "$orderby": "Order,Name",
    }, CHILD_LIMIT)
    sub = detail.section("Child groups", children, children_capped, hint=CHILD_HINT)
    for child in children:
        sub.row(child["Id"], f"{child['Name']}{_inactive(child)}")
    return detail


def cmd_checkin(args, client):
    templates, templates_capped = _checkin_templates(client)
    if args.group:
        return _checkin_group(args, client, templates, templates_capped)
    if not templates:
        return Text("No check-in templates found.")

    lines = ["Check-in Configuration:"]
    if templates_capped:
        lines.append(f"  {only_first('check-in templates')}")
    cache = {}
    for template, nodes in templates:
        lines += ["", f"  Template: {template['Name']} (ID: {template['Id']})"]
        lines += _area_lines(client, nodes, 4, cache)
    return Text("\n".join(lines))


def cmd_attendance(args, client):
    params = {
        "$orderby": "OccurrenceDate desc",
    }
    filters = []
    if args.group:
        group = _find_entity(client, "Groups", args.group, label="group")
        filters.append(f"GroupId eq {group['Id']}")
    if args.date:
        filters.append(f"OccurrenceDate eq datetime'{args.date.isoformat()}'")
    if filters:
        params["$filter"] = " and ".join(filters)

    occurrences, more = get_capped(client, "AttendanceOccurrences", params,
                                   args.limit)

    group_cache = {}
    location_cache = {}

    listing = Listing("Attendance Occurrences", more)
    for occ in occurrences:
        occ_date = (occ.get("OccurrenceDate") or "")[:10]

        gid = occ.get("GroupId")
        if gid and gid not in group_cache:
            group_cache[gid] = _resolve_name(client, "Groups", gid)
        group_name = group_cache.get(gid, "?")

        lid = occ.get("LocationId")
        if lid and lid not in location_cache:
            location_cache[lid] = _resolve_name(client, "Locations", lid)
        loc_name = location_cache.get(lid, "")

        did_not = " [DID NOT OCCUR]" if occ.get("DidNotOccur") else ""
        loc_str = f" @ {loc_name}" if loc_name else ""

        listing.add(occ["Id"], f"{occ_date}  {group_name}{loc_str}{did_not}")
    return listing


def cmd_occurrence(args, client):
    occ = client.get(f"AttendanceOccurrences/{args.id}")

    if args.json:
        return Raw(occ)

    occ_date = (occ.get("OccurrenceDate") or "")[:10]
    detail = Detail(f"Occurrence {occ['Id']} ({occ_date})")

    for label, endpoint, key in (("Group", "Groups", "GroupId"),
                                 ("Location", "Locations", "LocationId"),
                                 ("Schedule", "Schedules", "ScheduleId")):
        if occ.get(key):
            name = _resolve_name(client, endpoint, occ[key])
            if name != "?":
                detail.field(label, f"{name} (ID: {occ[key]})")
            else:
                detail.field(f"{label} ID", occ[key])

    if occ.get("DidNotOccur"):
        detail.field("Status", "DID NOT OCCUR")

    attendees, att_more = get_capped(client, "Attendances", {
        "$filter": f"OccurrenceId eq {occ['Id']}",
        "$select": "PersonAliasId,DidAttend,StartDateTime,RSVP",
    }, args.limit)

    if attendees:
        did_attend = sum(1 for a in attendees if a.get("DidAttend"))
        cut = " – more exist, raise --limit" if att_more else ""
        detail.field("Attendees",
                     f"{did_attend} attended / {len(attendees)} total{cut}")
        if args.names:
            person_cache = {}
            for a in attendees:
                pname = _resolve_person_name(client, a.get("PersonAliasId"),
                                             person_cache)
                attended = "Y" if a.get("DidAttend") else "N"
                rsvp = f" RSVP:{a['RSVP']}" if a.get("RSVP") else ""
                detail.line(f"{pname:30s} [{attended}]{rsvp}", depth=1)
    return detail


def cmd_block_set(args, client):
    # The read is only a check: a missing block stops here with Rock's 404, before the write.
    client.get(f"Blocks/{args.id}")

    print(f"Setting {args.key}={args.value[:80]}{'...' if len(args.value) > 80 else ''} on block {args.id}")

    try:
        client.set_attribute_value("Blocks", args.id, args.key, args.value)
    except RockApiError as e:
        if e.status != 400:
            raise
        log.error("block-set failed block=%d key=%s\n%s", args.id, args.key, traceback.format_exc())
        print(f"Error setting attribute: {e}")
        print(f"  Rock rejects a key it does not know. Check it against: "
              f"rock.sh query block {args.id}")
        # Exit 1: the calling skill reads exit 0 as the setting having landed.
        sys.exit(1)
    log.info("block-set ok block=%d key=%s", args.id, args.key)
    return Text("Done.")


def cmd_person_create(args, client):
    data = {
        "FirstName": args.first,
        "LastName": args.last,
        "IsSystem": False,
    }
    if args.email:
        data["Email"] = args.email
    if args.connection_status is not None:
        data["ConnectionStatusValueId"] = args.connection_status
    if args.record_status is not None:
        data["RecordStatusValueId"] = args.record_status
    if args.campus is not None:
        data["CampusId"] = args.campus

    pid = client.post("People", data)
    return Text(f"Created person: {args.first} {args.last} (ID: {pid})")


PERSON_UPDATE_ALIASES = {
    "campus": "CampusId",
    "connectionstatus": "ConnectionStatusValueId",
    "recordstatus": "RecordStatusValueId",
    "maritalstatus": "MaritalStatusValueId",
}
PERSON_UPDATE_COLUMNS = ("FirstName", "LastName", "Email", "NickName", "CampusId",
                         "ConnectionStatusValueId", "RecordStatusValueId",
                         "MaritalStatusValueId", "BirthDate", "Gender")
PERSON_UPDATE_FIELDS = {**{c.lower(): c for c in PERSON_UPDATE_COLUMNS},
                        **PERSON_UPDATE_ALIASES}


def cmd_person_update(args, client):
    person = client.get(f"People/{args.id}")

    data = {}
    for kv in args.fields:
        if "=" not in kv:
            print(f"Invalid field format: {kv} (expected key=value)")
            sys.exit(1)
        key, value = kv.split("=", 1)
        mapped = PERSON_UPDATE_FIELDS.get(key.lower())
        if mapped is None:
            print(f"Unknown field: {key}. Valid fields: "
                  f"{', '.join(sorted(PERSON_UPDATE_FIELDS))}")
            sys.exit(1)
        data[mapped] = value

    client.patch(f"People/{args.id}", data)
    pname = f"{person.get('FirstName', '')} {person.get('LastName', '')}"
    return Text(f"Updated {pname} (ID: {args.id}): {', '.join(f'{k}={v}' for k, v in data.items())}")


def cmd_exception_clear(args, client):
    params = {"$select": "Id", "$orderby": "CreatedDateTime asc"}
    filters = []
    if args.before:
        filters.append(f"CreatedDateTime lt datetime'{args.before.isoformat()}T00:00:00'")
    if args.type:
        filters.append(f"substringof('{odata_str(args.type)}', ExceptionType) eq true")
    if filters:
        params["$filter"] = " and ".join(filters)

    exceptions, more = get_capped(client, "ExceptionLogs", params, args.limit)
    if not exceptions:
        return Text("No exceptions matching criteria.")

    print(f"Deleting {plural(len(exceptions), 'exception log')}..."
          + (f" More than {args.limit} match, so run this again." if more else ""))
    deleted = 0
    errors = 0
    for ex in exceptions:
        try:
            client.delete(f"ExceptionLogs/{ex['Id']}")
            deleted += 1
        except Exception as _e:
            log.debug("exception delete failed id=%d: %s", ex['Id'], _e)
            errors += 1
    log.info("exception-clear deleted=%d errors=%d", deleted, errors)
    summary = f"Deleted {deleted}/{len(exceptions)} exceptions."
    if errors:
        print(f"{summary} ({plural(errors, 'error')})")
        sys.exit(1)
    return Text(summary)


def _guard_writes(parsed):
    effect = getattr(parsed, "writes", None)
    if effect is None:
        return
    refuse_unless_writes_enabled(
        f"Refusing to run '{parsed.command}': it {effect}, and it was not "
        f"reached through rock.sh.\n"
        f"Run it as `rock.sh query {parsed.command} ...` – rock.sh enables the write "
        f"and this script logs the command name to rock.log."
    )


def positive_int(value):
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError("must be a whole number of 1 or more")
    return number


def iso_date(value):
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError("must be a date as YYYY-MM-DD") from None


def not_blank(value):
    if not value.strip():
        raise argparse.ArgumentTypeError("cannot be blank")
    return value


def main():
    parser = argparse.ArgumentParser(description="Query Rock RMS entities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_wfs = subparsers.add_parser("workflows", help="List workflow types")
    p_wfs.add_argument("--category", help="Filter by category name")
    p_wfs.add_argument("--limit", type=positive_int, default=100)
    p_wfs.set_defaults(func=cmd_workflows)

    p_wf = subparsers.add_parser("workflow", help="Get a workflow by name or ID")
    p_wf.add_argument("identifier", type=not_blank, help="Workflow name or ID")
    p_wf.add_argument("--json", action="store_true", help="Output raw JSON")
    p_wf.set_defaults(func=cmd_workflow)

    p_pgs = subparsers.add_parser("pages", help="List pages")
    p_pgs.add_argument("--site", type=int, help="Filter by site ID")
    p_pgs.add_argument("--limit", type=positive_int, default=100)
    p_pgs.set_defaults(func=cmd_pages)

    p_pg = subparsers.add_parser("page", help="Get a page by name, route, or ID")
    p_pg.add_argument("identifier", type=not_blank, help="Page name, route, or ID")
    p_pg.add_argument("--json", action="store_true", help="Output raw JSON")
    p_pg.set_defaults(func=cmd_page)

    p_search = subparsers.add_parser("search", help="Search across entities")
    p_search.add_argument("query", type=not_blank, help="Search text")
    p_search.set_defaults(func=cmd_search)

    p_audit = subparsers.add_parser("audit", help="Audit a workflow for issues")
    p_audit.add_argument("identifier", type=not_blank, help="Workflow name or ID")
    p_audit.add_argument("--skip-settings", action="store_true",
                         help="Skip per-action settings checks (faster)")
    p_audit.set_defaults(func=cmd_audit)

    p_actions = subparsers.add_parser("actions", help="Show detailed actions for an activity")
    p_actions.add_argument("activity_id", type=int, help="Activity type ID")
    p_actions.set_defaults(func=cmd_actions)

    p_attrs = subparsers.add_parser("attributes", help="Show workflow attributes")
    p_attrs.add_argument("identifier", type=not_blank, help="Workflow name or ID")
    p_attrs.set_defaults(func=cmd_attributes)

    p_dvs = subparsers.add_parser("dataviews", help="List data views")
    p_dvs.add_argument("--category", help="Filter by category name substring")
    p_dvs.add_argument("--limit", type=positive_int, default=100)
    p_dvs.set_defaults(func=cmd_dataviews)

    p_dv = subparsers.add_parser("dataview", help="Get a data view by name or ID")
    p_dv.add_argument("identifier", type=not_blank, help="Data view name or ID")
    p_dv.add_argument("--json", action="store_true", help="Output raw JSON")
    p_dv.set_defaults(func=cmd_dataview)

    p_person = subparsers.add_parser("person", help="Look up a person by name, email, or ID")
    p_person.add_argument("identifier", type=not_blank, help="Person name, email, or ID")
    p_person.set_defaults(func=cmd_person)

    p_group = subparsers.add_parser("group", help="Get a group by name or ID")
    p_group.add_argument("identifier", type=not_blank, help="Group name or ID")
    p_group.add_argument("--json", action="store_true", help="Output raw JSON")
    p_group.add_argument("--limit", type=positive_int, default=50, help="Max members to show")
    p_group.set_defaults(func=cmd_group)

    p_report = subparsers.add_parser("report", help="Get a report by name or ID")
    p_report.add_argument("identifier", type=not_blank, help="Report name or ID")
    p_report.add_argument("--json", action="store_true", help="Output raw JSON")
    p_report.set_defaults(func=cmd_report)

    p_exs = subparsers.add_parser("exceptions", help="List recent exception logs")
    p_exs.add_argument("--type", help="Filter by exception type substring")
    p_exs.add_argument("--summary", action="store_true", help="Group by type with counts")
    p_exs.add_argument("--verbose", action="store_true", help="Show stack traces")
    p_exs.add_argument("--limit", type=positive_int, default=50)
    p_exs.set_defaults(func=cmd_exceptions)

    p_ex = subparsers.add_parser("exception", help="Get exception detail by ID")
    p_ex.add_argument("id", type=int, help="Exception log ID")
    p_ex.add_argument("--json", action="store_true", help="Output raw JSON")
    p_ex.set_defaults(func=cmd_exception)

    p_scheds = subparsers.add_parser("schedules", help="List schedules")
    p_scheds.add_argument("--active", action="store_true", help="Active only")
    p_scheds.add_argument("--query", help="Filter by name substring")
    p_scheds.add_argument("--limit", type=positive_int, default=100)
    p_scheds.set_defaults(func=cmd_schedules)

    p_sched = subparsers.add_parser("schedule", help="Get a schedule by name or ID")
    p_sched.add_argument("identifier", type=not_blank, help="Schedule name or ID")
    p_sched.add_argument("--json", action="store_true", help="Output raw JSON")
    p_sched.set_defaults(func=cmd_schedule)

    p_regs = subparsers.add_parser("registrations", help="List registration instances")
    p_regs.add_argument("--active", action="store_true", help="Active only")
    p_regs.add_argument("--query", help="Filter by name substring")
    p_regs.add_argument("--limit", type=positive_int, default=50)
    p_regs.set_defaults(func=cmd_registrations)

    p_reg = subparsers.add_parser("registration", help="Get a registration instance by name or ID")
    p_reg.add_argument("identifier", type=not_blank, help="Registration name or ID")
    p_reg.add_argument("--json", action="store_true", help="Output raw JSON")
    p_reg.set_defaults(func=cmd_registration)

    p_conns = subparsers.add_parser("connections", help="List connection requests")
    p_conns.add_argument("--state", type=str.lower, choices=sorted(CONNECTION_STATE_FILTER),
                         help="Filter by connection state")
    p_conns.add_argument("--opportunity", help="Filter by opportunity name substring")
    p_conns.add_argument("--limit", type=positive_int, default=50)
    p_conns.set_defaults(func=cmd_connections)

    p_block = subparsers.add_parser("block", help="Get block with attributes by ID")
    p_block.add_argument("id", type=int, help="Block ID")
    p_block.add_argument("--json", action="store_true", help="Output raw JSON")
    p_block.set_defaults(func=cmd_block)

    p_bgc = subparsers.add_parser("bgc", help="List background checks")
    p_bgc.add_argument("--status", help="Filter by status substring")
    p_bgc.add_argument("--person", type=not_blank, help="Filter by person name or ID")
    p_bgc.add_argument("--limit", type=positive_int, default=50)
    p_bgc.set_defaults(func=cmd_bgc)

    p_checkin = subparsers.add_parser("checkin", help="Show check-in configuration")
    p_checkin.add_argument("--group", type=not_blank,
                           help="One group in a check-in area, by name or ID")
    p_checkin.set_defaults(func=cmd_checkin)

    p_att = subparsers.add_parser("attendance", help="List attendance occurrences")
    p_att.add_argument("--group", type=not_blank, help="Filter by group name or ID")
    p_att.add_argument("--date", type=iso_date, help="Filter by date (YYYY-MM-DD)")
    p_att.add_argument("--limit", type=positive_int, default=50)
    p_att.set_defaults(func=cmd_attendance)

    p_occ = subparsers.add_parser("occurrence", help="Get attendance occurrence detail")
    p_occ.add_argument("id", type=int, help="Occurrence ID")
    p_occ.add_argument("--names", action="store_true", help="Show attendee names")
    p_occ.add_argument("--json", action="store_true", help="Output raw JSON")
    p_occ.add_argument("--limit", type=positive_int, default=200, help="Max attendees to show")
    p_occ.set_defaults(func=cmd_occurrence)

    p_bset = subparsers.add_parser("block-set", help="Set a block attribute value")
    p_bset.add_argument("id", type=int, help="Block ID")
    p_bset.add_argument("key", help="Attribute key")
    p_bset.add_argument("value", help="Attribute value")
    p_bset.set_defaults(func=cmd_block_set, writes="changes a block's settings")

    p_pcreate = subparsers.add_parser("person-create", help="Create a new person record")
    p_pcreate.add_argument("--first", required=True, help="First name")
    p_pcreate.add_argument("--last", required=True, help="Last name")
    p_pcreate.add_argument("--email", help="Email address")
    p_pcreate.add_argument("--connection-status", type=int, help="ConnectionStatusValueId")
    p_pcreate.add_argument("--record-status", type=int, help="RecordStatusValueId")
    p_pcreate.add_argument("--campus", type=int, help="CampusId")
    p_pcreate.set_defaults(func=cmd_person_create, writes="creates a person record")

    p_pupdate = subparsers.add_parser("person-update", help="Update a person's fields")
    p_pupdate.add_argument("id", type=int, help="Person ID")
    p_pupdate.add_argument("fields", nargs="+", help="Field=value pairs (e.g. Email=foo@bar.com)")
    p_pupdate.set_defaults(func=cmd_person_update, writes="modifies a person record")

    p_exclear = subparsers.add_parser("exception-clear", help="Delete exception logs")
    p_exclear.add_argument("--before", type=iso_date, help="Delete exceptions before date (YYYY-MM-DD)")
    p_exclear.add_argument("--type", help="Filter by exception type substring")
    p_exclear.add_argument("--limit", type=positive_int, default=500, help="Max exceptions to delete per run")
    p_exclear.set_defaults(func=cmd_exception_clear, writes="deletes exception logs")

    parsed = parser.parse_args()
    _guard_writes(parsed)
    log.info("cmd=%s args=%d", parsed.command, len(sys.argv) - 2)
    with api_errors_reported():
        client = RockClient()
        try:
            render(parsed.func(parsed, client))
            log.info("cmd=%s ok", parsed.command)
        except LookupMiss as miss:
            # The rock skill documents a miss as exit 1 and an empty Listing as exit 0.
            render(miss.report)
            log.info("cmd=%s no match", parsed.command)
            sys.exit(1)
        except Exception:
            log.error("cmd=%s failed\n%s", parsed.command, traceback.format_exc())
            raise


if __name__ == "__main__":
    main()
