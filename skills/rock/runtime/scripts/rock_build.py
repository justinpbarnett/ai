import inspect
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import rock_paths
from rock_client import (RockClient, RockError, RockNotFound, api_errors_reported, get_credentials,
                         odata_str, refuse_unless_writes_enabled)
from rock_catalog import CatalogUnreadable, catalog_mismatch, load_catalog
from rock_log import get_logger
from rock_text import plural

log = get_logger("rock.build")


class PlanError(ValueError):
    pass


SENT_AS_WRITTEN = {"settings", "updates", "body"}


def without_nulls(node):
    if isinstance(node, dict):
        return {key: value if key in SENT_AS_WRITTEN else without_nulls(value)
                for key, value in node.items() if value is not None}
    if isinstance(node, list):
        return [without_nulls(item) for item in node]
    return node


JSON_KINDS = {dict: "an object", list: "a list", str: "a string", bool: "a boolean",
              int: "a number", float: "a number"}


def wrong_shape(where, wanted, value):
    return f'"{where}" must be {JSON_KINDS[wanted]}, got {JSON_KINDS[type(value)]}'


def is_id(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_name(value):
    return isinstance(value, str) and bool(value.strip())


def plan_nodes(plan, path, problems):
    nodes = [("", plan)]
    for segment in path.split("."):
        key = segment.removesuffix("[]")
        fans_out = key != segment
        found = []
        for where, node in nodes:
            here = f"{where}.{key}" if where else key
            if node is None:
                if not fans_out:
                    found.append((here, None))
            elif not isinstance(node, dict):
                problems.setdefault(where, wrong_shape(where, dict, node))
            elif not fans_out:
                found.append((here, node.get(key)))
            elif isinstance(node.get(key), list):
                found.extend((f"{here}[{i}]", item) for i, item in enumerate(node[key]))
            elif node.get(key) is not None:
                problems.setdefault(here, wrong_shape(here, list, node[key]))
        nodes = found
    return nodes


def given_nodes(plan, path, problems):
    parent, _, key = path.rpartition(".")
    if key.endswith("[]"):
        return plan_nodes(plan, path, problems)
    return [(f"{where}.{key}", node[key]) for where, node in plan_nodes(plan, parent, problems)
            if isinstance(node, dict) and key in node]


def rock_field(field_map, key, also_accepted=()):
    if key in field_map:
        return field_map[key]
    accepted = ", ".join(sorted(set(field_map) | set(also_accepted)))
    raise PlanError(f"unknown field {key!r}. This operation accepts: {accepted}")


CHECKIN_SCHEDULES = (
    "cannot be built. Check-in reads its schedules from each of the group's locations, "
    "and Rock's API cannot set them there. Leave \"schedules\" out, and add them afterwards "
    "with the Schedule button on Rock's Check-in Configuration page.")

REQUIREMENTS = {
    "create_workflow": {
        "requires": ["workflow.name", "workflow.attributes[].key",
                     "workflow.activities[].name",
                     "workflow.activities[].actions[].name",
                     "workflow.activities[].actions[].action_type"],
        "objects": ["workflow.activities[].actions[].settings"],
        "lists": ["workflow.activities[].actions[].form.attributes"],
        "names": ["workflow.category", "workflow.attributes[].key",
                  "workflow.attributes[].field_type",
                  "workflow.activities[].actions[].action_type",
                  "workflow.activities[].actions[].form.attributes[]"],
    },
    "create_page": {
        "requires": ["page.name", ("page.layout_id", "page.layout"),
                     ("page.parent_page_id", "page.parent_page"),
                     ("page.blocks[].block_type_id", "page.blocks[].block_type")],
        "objects": ["page.blocks[].settings"],
        "names": ["page.layout", "page.parent_page", "page.blocks[].block_type"],
    },
    "add_action": {
        "requires": ["modification.activity_type_id", "modification.action.name",
                     "modification.action.action_type"],
        "objects": ["modification.action.settings"],
        "names": ["modification.action.action_type"],
    },
    "add_block": {
        "requires": ["modification.page_id",
                     ("modification.block.block_type_id",
                      "modification.block.block_type")],
        "objects": ["modification.block.settings"],
        "names": ["modification.block.block_type"],
    },
    "update_workflow": {
        "requires": ["modification.workflow_type_id", "modification.updates"],
        "objects": ["modification.updates"],
        "non_empty": ["modification.updates"],
        "names": ["modification.updates.category"],
    },
    "update_activity": {
        "requires": ["modification.activity_type_id", "modification.updates"],
        "objects": ["modification.updates"],
        "non_empty": ["modification.updates"],
    },
    "update_action": {
        "requires": ["modification.action_type_id"],
        "objects": ["modification.updates", "modification.settings"],
        "any_non_empty": ["modification.updates", "modification.settings"],
        "names": ["modification.updates.action_type"],
    },
    "delete_action": {
        "requires": ["modification.action_type_id"],
    },
    "delete_activity": {
        "requires": ["modification.activity_type_id"],
    },
    "reorder_actions": {
        "requires": ["modification.action_order"],
        "lists": ["modification.action_order"],
        "non_empty": ["modification.action_order"],
        "ids": ["modification.action_order[]"],
    },
    "move_action": {
        "requires": ["modification.action_type_id",
                     "modification.target_activity_type_id"],
    },
    "create_checkin_area": {
        "requires": ["checkin_area.name",
                     ("checkin_area.group_type_id", "checkin_area.group_type")],
        "lists": ["checkin_area.locations"],
        "names": ["checkin_area.group_type"],
        "ids_or_names": ["checkin_area.locations[]"],
        "refused": {"checkin_area.schedules": CHECKIN_SCHEDULES},
    },
    "create_group": {
        "requires": ["group.name", ("group.group_type_id", "group.group_type")],
        "objects": ["group.settings"],
        "names": ["group.group_type"],
    },
    "update_group": {
        "requires": ["modification.group_id", "modification.updates"],
        "objects": ["modification.updates", "modification.settings"],
        "non_empty": ["modification.updates"],
    },
    "add_group_member": {
        "requires": ["modification.group_id", "modification.person_id",
                     ("modification.group_role_id", "modification.role")],
        "names": ["modification.role"],
    },
    "update_group_member": {
        "requires": ["modification.group_member_id", "modification.updates"],
        "objects": ["modification.updates"],
        "non_empty": ["modification.updates"],
        "names": ["modification.updates.role"],
    },
    "remove_group_member": {
        "requires": ["modification.group_member_id"],
    },
    "create_group_sync": {
        "requires": ["modification.group_id",
                     ("modification.group_type_role_id", "modification.role"),
                     ("modification.sync_data_view_id", "modification.data_view")],
        "names": ["modification.role", "modification.data_view"],
    },
    "api_request": {
        "requires": ["request"],
        "objects": ["request", "request.params"],
    },
}

CHANGES_NOTHING = "The build would change nothing and still report success."


def required_id_paths(spec):
    for requirement in spec.get("requires", ()):
        for path in (requirement,) if isinstance(requirement, str) else requirement:
            if path.endswith("_id"):
                yield path


def plan_problems(operation, plan):
    spec = REQUIREMENTS.get(operation, {})
    problems = {}

    def nodes(path):
        return plan_nodes(plan, path, problems)

    for requirement in spec.get("requires", ()):
        options = (requirement,) if isinstance(requirement, str) else requirement
        for alternatives in zip(*map(nodes, options), strict=True):
            if all(value is None for _, value in alternatives):
                problems.setdefault(alternatives[0][0], "needs " + " or ".join(
                    f'"{where}"' for where, _ in alternatives))

    for shape, wanted in (("objects", dict), ("lists", list)):
        for path in spec.get(shape, ()):
            for where, value in nodes(path):
                if value is not None and not isinstance(value, wanted):
                    problems.setdefault(where, wrong_shape(where, wanted, value))

    for path in spec.get("non_empty", ()):
        for where, value in nodes(path):
            if value is not None and not value:
                problems.setdefault(where, f'"{where}" is empty. {CHANGES_NOTHING}')

    any_of = spec.get("any_non_empty", ())
    if any_of and not any(value for path in any_of for _, value in nodes(path)):
        listed = " or ".join(f'"{path}"' for path in any_of)
        problems.setdefault(any_of[0], f"needs something in {listed}. {CHANGES_NOTHING}")

    for path in required_id_paths(spec):
        for where, value in nodes(path):
            if value is not None and not is_id(value):
                problems.setdefault(where, f'"{where}" must be a whole number id, '
                                           f'got {json.dumps(value)}')

    for path in spec.get("ids", ()):
        for where, value in given_nodes(plan, path, problems):
            if not is_id(value):
                problems.setdefault(where, f'"{where}" must be a whole number id, '
                                           f'got {json.dumps(value)}')

    for path in spec.get("names", ()):
        for where, value in given_nodes(plan, path, problems):
            if not is_name(value):
                problems.setdefault(where, f'"{where}" must be a name, got {json.dumps(value)}')

    for path in spec.get("ids_or_names", ()):
        for where, value in nodes(path):
            if not (is_id(value) or is_name(value)):
                problems.setdefault(where, f'"{where}" must be an id or a name, '
                                           f'got {json.dumps(value)}')

    for path, reason in spec.get("refused", {}).items():
        for where, _ in given_nodes(plan, path, problems):
            problems.setdefault(where, f'"{where}" {reason}')

    return list(problems.values())


def _exact_or_unique(candidates, noun, name, is_exact, contains):
    exact = {entry_id: label for entry_id, label, entry in candidates if is_exact(entry)}
    matched = exact or {entry_id: label for entry_id, label, entry in candidates if contains(entry)}
    if len(matched) > 1:
        listed = ", ".join(f"{label!r} (id {entry_id})" for entry_id, label in matched.items())
        raise PlanError(f"{name!r} matches {len(matched)} {noun}: {listed}. "
                        f"Give the exact name.")
    return next(iter(matched), None)


def resolve_action_type(catalog, name):
    name_lower = name.lower().replace(" ", "")
    candidates = [(ac["entity_type_id"], ac["name"], ac)
                  for ac in catalog.get("action_components", [])]
    return _exact_or_unique(
        candidates, "action types", name,
        lambda ac: (ac["name"].lower().replace(" ", "") == name_lower
                    or ac["class_name"].lower().split(".")[-1] == name_lower),
        lambda ac: (name_lower in ac["name"].lower()
                    or name_lower in ac["class_name"].lower()))


def _resolve_entry(entries, name):
    name_lower = name.lower()
    candidates = [(entry["id"], entry["name"], entry) for entry in entries]
    return _exact_or_unique(
        candidates, "catalog entries", name,
        lambda entry: entry["name"].lower() == name_lower,
        lambda entry: name_lower in entry["name"].lower())


def resolve_field_type(catalog, name):
    return _resolve_entry(catalog.get("field_types", []), name)


def resolve_block_type(catalog, name):
    return _resolve_entry(catalog.get("block_types", []), name)


def resolve_page_layout(client, catalog, parent_id, name):
    """A page's site is its layout's site, and several sites can each have a "Full Width"."""
    layouts = catalog.get("layouts", [])
    if parent_id is None:
        # The parent lookup failed, so the build stops. This only reports a name that no site has.
        return _resolve_entry(layouts, name)
    try:
        parent = client.get(f"Pages/{parent_id}", params={"$select": "LayoutId"})
    except RockNotFound:
        raise PlanError(f"no page has id {parent_id}") from None
    parent_layout = next((layout for layout in layouts if layout["id"] == parent["LayoutId"]), None)
    if parent_layout is None:
        raise PlanError(f"the parent page's layout, id {parent['LayoutId']}, is not in "
                        f"{rock_paths.CATALOG.name}. Refresh it: rock.sh catalog refresh")
    site_id = parent_layout["site_id"]
    site_layouts = [layout for layout in layouts if layout["site_id"] == site_id]
    found = _resolve_entry(site_layouts, name)
    if found is None:
        site_name = next((site["name"] for site in catalog.get("sites", []) if site["id"] == site_id),
                         f"site {site_id}")
        names = ", ".join(sorted((repr(layout["name"]) for layout in site_layouts), key=str.casefold))
        raise PlanError(f"no 'layout' matches {name!r} in {site_name}, the parent page's site. "
                        f"It has {plural(len(site_layouts), 'layout')}: {names}.")
    return found


def _first_id(client, endpoint, filter_str, column="Id"):
    found = client.get(endpoint, params={
        "$filter": filter_str,
        "$select": column,
        "$top": 1,
    })
    return found[0][column] if found else None


def _named(client, endpoint, name):
    return _first_id(client, endpoint, f"Name eq '{odata_str(name)}'")


def entity_type_named(client, name):
    found = _named(client, "EntityTypes", name)
    if not found:
        raise RockError(f"Rock has no entity type named {name!r}")
    return found


def resolve_workflow_category(client, name):
    workflow_type = entity_type_named(client, "Rock.Model.WorkflowType")
    return uniquely_named(client, "Categories", "category", name,
                          scope=f"EntityTypeId eq {workflow_type} and ")


NEAR_NAMES = 5


def uniquely_named(client, endpoint, name_key, name, scope="", column="Name", id_column="Id"):
    matches = client.get(endpoint, params={
        "$filter": f"{scope}{column} eq '{odata_str(name)}'",
        "$select": id_column,
    })
    ids = list(dict.fromkeys(match[id_column] for match in matches))
    if len(ids) == 1:
        return ids[0]
    if ids:
        listed = ", ".join(str(found) for found in ids)
        noun = name_key.replace("_", " ")
        raise PlanError(f"{len(ids)} {noun}s are named {name!r}, ids {listed}. "
                        f"Give the id of the one you mean.")
    near = client.get(endpoint, params={
        "$filter": f"{scope}substringof('{odata_str(name)}', {column}) eq true",
        "$select": column,
        "$top": NEAR_NAMES,
    })
    hint = ", ".join(dict.fromkeys(repr(row[column]) for row in near))
    raise PlanError(f"no {name_key!r} matches {name!r}"
                    + (f". Names that contain it include {hint}." if hint else ""))


def resolve_group_type(client, name):
    return uniquely_named(client, "GroupTypes", "group_type", name)


def resolve_location(client, name):
    return uniquely_named(client, "Locations", "location", name)


def resolve_group_role(client, group_id, role_name):
    """Role names repeat across group types: the name alone can match the wrong one."""
    group = client.get(f"Groups/{group_id}", params={"$select": "GroupTypeId"})
    return _first_id(client, "GroupTypeRoles",
                     f"GroupTypeId eq {group['GroupTypeId']} and "
                     f"Name eq '{odata_str(role_name)}'")


def resolve_member_role(client, member_id, role_name):
    member = client.get(f"GroupMembers/{member_id}", params={"$select": "GroupId"})
    return resolve_group_role(client, member["GroupId"], role_name)


def resolve_data_view(client, name):
    return uniquely_named(client, "DataViews", "data_view", name)


def resolve_page_route(client, route):
    return uniquely_named(client, "PageRoutes", "parent_page", route.lstrip("/"),
                          column="Route", id_column="PageId")


def resolve_named(name_key, name, resolve, *lookup_args):
    found = resolve(*lookup_args, name)
    if not found:
        raise PlanError(f"no {name_key!r} matches {name!r}")
    return found


def resolve_ref(source, id_key, name_key, resolve, *lookup_args):
    if source.get(id_key):
        return source[id_key]
    if not source.get(name_key):
        raise PlanError(f"give {id_key!r} or {name_key!r}")
    return resolve_named(name_key, source[name_key], resolve, *lookup_args)


MEMBER_STATUS = {"inactive": 0, "active": 1, "pending": 2}


def member_status(value):
    if isinstance(value, int) and not isinstance(value, bool) and value in MEMBER_STATUS.values():
        return value
    name = value.strip().lower() if isinstance(value, str) else None
    if name not in MEMBER_STATUS:
        raise PlanError(f"unknown status {json.dumps(value)}. "
                        f"Expected one of {', '.join(MEMBER_STATUS)}")
    return MEMBER_STATUS[name]


def _next_order(client, endpoint, filter_str):
    existing = client.get(endpoint, params={
        "$filter": filter_str,
        "$select": "Order",
        "$orderby": "Order desc",
        "$top": 1,
    })
    return (existing[0]["Order"] + 1) if existing else 0


def apply_settings(result, client, endpoint, entity_id, label, settings):
    for key, value in settings.items():
        with step(result, "Setting", f"{key} on {label}"):
            client.set_attribute_value(endpoint, entity_id, key, value)
            result.add("Setting", f"{key} on {label}")


def describe(error):
    if isinstance(error, (str, PlanError, RockError)):
        return str(error)
    return f"{type(error).__name__}: {error}"


class BuildResult:
    def __init__(self):
        self.applied = []
        self.failures = []

    def add(self, kind, name, entity_id=None):
        self.applied.append({"kind": kind, "name": name, "id": entity_id})
        log.info("applied %s: %s (id: %s)", kind, name, entity_id)

    def fail(self, kind, name, error):
        self.failures.append({"kind": kind, "name": name, "error": describe(error)})
        log.error("failed %s: %s -- %s", kind, name, error,
                  exc_info=error if isinstance(error, BaseException) else None)

    def report(self):
        print("\nBuild results:")
        for item in self.applied:
            created = "" if item["id"] is None else f" (id: {item['id']})"
            print(f"  ✓ {item['kind']}: {item['name']}{created}")
        for item in self.failures:
            error = item["error"].replace("\n", "\n    ")
            print(f"  ✗ {item['kind']}: {item['name']} -- {error}")
        if not self.failures:
            print(f"\nDone: {plural(len(self.applied), 'step')} succeeded.")
        elif not self.applied:
            print("\nNothing was applied.")
        else:
            print("\nStopped at the failure. The steps marked ✓ are in Rock, "
                  "and nothing after the failure was attempted.")

    @property
    def success(self):
        return not self.failures


class StepFailed(Exception):
    pass


@contextmanager
def step(result, kind, label):
    try:
        yield
    except StepFailed:
        raise
    except Exception as exc:
        result.fail(kind, label, exc)
        raise StepFailed from exc


@contextmanager
def lookup(result, kind, label):
    try:
        yield
    except PlanError as exc:
        result.fail(kind, label, exc)
    except Exception as exc:
        result.fail(kind, label, exc)
        raise StepFailed from exc


SUBMIT_BUTTON = "Submit^^^Your information has been submitted successfully."


def create_workflow(result, plan, client, catalog):
    wf = plan["workflow"]
    attributes = wf.get("attributes", [])
    keys = [attr_def["key"] for attr_def in attributes]
    is_required = {attr_def["key"]: attr_def.get("is_required", False) for attr_def in attributes}

    category_id = None
    if "category_id" in wf or "category" in wf:
        with lookup(result, "WorkflowType", wf["name"]):
            category_id = resolve_ref(wf, "category_id", "category",
                                      resolve_workflow_category, client)

    wf_entity_type_id = None
    if attributes:
        with lookup(result, "Attribute", keys[0]):
            wf_entity_type_id = entity_type_named(client, "Rock.Model.Workflow")

    field_type_ids = {}
    for order, attr_def in enumerate(attributes):
        if attr_def["key"] in keys[:order]:
            result.fail("Attribute", attr_def["key"],
                        "an earlier attribute has this key too. Each attribute needs its own key.")
        with lookup(result, "Attribute", attr_def["key"]):
            field_type_ids[order] = resolve_named("field_type",
                                                  attr_def.get("field_type", "Text"),
                                                  resolve_field_type, catalog)

    action_type_ids = {}
    for act_order, act_def in enumerate(wf.get("activities", [])):
        for action_order, action_def in enumerate(act_def.get("actions", [])):
            with lookup(result, "ActionType", action_def["name"]):
                action_type_ids[act_order, action_order] = resolve_named(
                    "action_type", action_def["action_type"], resolve_action_type, catalog)
            for field_key in action_def.get("form", {}).get("attributes", []):
                if field_key not in keys:
                    result.fail("FormAttribute", field_key,
                                f"no attribute {field_key!r} on this workflow. "
                                f"It defines: {', '.join(dict.fromkeys(keys)) or 'none'}")

    if result.failures:
        raise StepFailed

    wf_data = {
        "Name": wf["name"],
        "Description": wf.get("description", ""),
        "IsActive": wf.get("is_active", True),
        "IsPersisted": wf.get("is_persisted", True),
        "WorkTerm": wf.get("work_term", "Workflow"),
        "ProcessingIntervalSeconds": wf.get("processing_interval", None),
    }
    if category_id:
        wf_data["CategoryId"] = category_id

    with step(result, "WorkflowType", wf["name"]):
        wf_id = client.post("WorkflowTypes", wf_data)
        result.add("WorkflowType", wf["name"], wf_id)

    attr_ids = {}
    for order, attr_def in enumerate(attributes):
        attr_data = {
            "EntityTypeId": wf_entity_type_id,
            "EntityTypeQualifierColumn": "WorkflowTypeId",
            "EntityTypeQualifierValue": str(wf_id),
            "FieldTypeId": field_type_ids[order],
            "Key": attr_def["key"],
            "Name": attr_def.get("name", attr_def["key"]),
            "Description": attr_def.get("description", ""),
            "IsRequired": is_required[attr_def["key"]],
            "Order": attr_def.get("order", order),
            "IsGridColumn": attr_def.get("is_grid_column", False),
        }

        with step(result, "Attribute", attr_def["key"]):
            attr_id = client.post("Attributes", attr_data)
            attr_ids[attr_def["key"]] = attr_id
            result.add("Attribute", attr_def["key"], attr_id)

    for act_order, act_def in enumerate(wf.get("activities", [])):
        act_data = {
            "WorkflowTypeId": wf_id,
            "Name": act_def["name"],
            "Description": act_def.get("description", ""),
            "IsActivatedWithWorkflow": act_def.get("is_activated_with_workflow", act_order == 0),
            "Order": act_def.get("order", act_order),
            "IsActive": True,
        }

        with step(result, "ActivityType", act_def["name"]):
            act_id = client.post("WorkflowActivityTypes", act_data)
            result.add("ActivityType", act_def["name"], act_id)

        for action_order, action_def in enumerate(act_def.get("actions", [])):
            action_data = {
                "ActivityTypeId": act_id,
                "Name": action_def["name"],
                "EntityTypeId": action_type_ids[act_order, action_order],
                "Order": action_def.get("order", action_order),
                "IsActionCompletedOnSuccess": action_def.get("complete_on_success", True),
                "IsActivityCompletedOnSuccess": action_def.get("complete_activity_on_success", False),
            }

            with step(result, "ActionType", action_def["name"]):
                action_id = client.post("WorkflowActionTypes", action_data)
                result.add("ActionType", action_def["name"], action_id)

            apply_settings(result, client, "WorkflowActionTypes", action_id,
                           action_def["name"], action_def.get("settings", {}))

            form_def = action_def.get("form")
            if form_def:
                form_data = {
                    "WorkflowActionTypeId": action_id,
                    "Header": form_def.get("header", ""),
                    "Footer": form_def.get("footer", ""),
                    "Actions": SUBMIT_BUTTON,
                    "AllowNotes": form_def.get("allow_notes", False),
                }

                with step(result, "Form", f"form on {action_def['name']}"):
                    form_id = client.post("WorkflowActionForms", form_data)
                    result.add("Form", f"form on {action_def['name']}", form_id)

                for field_order, field_key in enumerate(form_def.get("attributes", [])):
                    form_attr_data = {
                        "WorkflowActionFormId": form_id,
                        "AttributeId": attr_ids[field_key],
                        "Order": field_order,
                        "IsVisible": True,
                        "IsReadOnly": False,
                        "IsRequired": is_required[field_key],
                        "HideLabel": False,
                    }

                    with step(result, "FormAttribute", field_key):
                        fa_id = client.post("WorkflowActionFormAttributes", form_attr_data)
                        result.add("FormAttribute", field_key, fa_id)


DISPLAY_IN_NAV_WHEN = {"when_allowed": 0, "always": 1, "never": 2}


def display_in_nav_when(name):
    key = name.strip().lower() if isinstance(name, str) else None
    if key not in DISPLAY_IN_NAV_WHEN:
        raise PlanError(f"display_in_nav must be one of {', '.join(DISPLAY_IN_NAV_WHEN)}, "
                        f"got {json.dumps(name)}")
    return DISPLAY_IN_NAV_WHEN[key]


def block_label(block_def, order):
    return block_def.get("name", f"block-{order}")


def create_page(result, plan, client, catalog):
    pg = plan["page"]
    blocks = pg.get("blocks", [])

    with lookup(result, "Page", pg["name"]):
        nav_when = display_in_nav_when(pg.get("display_in_nav", "never"))
    parent_id = None
    with lookup(result, "Page", pg["name"]):
        parent_id = resolve_ref(pg, "parent_page_id", "parent_page",
                                resolve_page_route, client)
    with lookup(result, "Page", pg["name"]):
        layout_id = resolve_ref(pg, "layout_id", "layout", resolve_page_layout,
                                client, catalog, parent_id)

    block_type_ids = {}
    for order, block_def in enumerate(blocks):
        with lookup(result, "Block", block_label(block_def, order)):
            block_type_ids[order] = resolve_ref(block_def, "block_type_id", "block_type",
                                                resolve_block_type, catalog)

    if result.failures:
        raise StepFailed

    page_data = {
        "InternalName": pg["name"],
        "PageTitle": pg.get("title", pg["name"]),
        "LayoutId": layout_id,
        "DisplayInNavWhen": nav_when,
        "ParentPageId": parent_id,
        "IsSystem": False,
    }

    with step(result, "Page", pg["name"]):
        page_id = client.post("Pages", page_data)
        result.add("Page", pg["name"], page_id)

    route = pg.get("route")
    if route:
        with step(result, "PageRoute", route):
            route_id = client.post("PageRoutes", {
                "PageId": page_id,
                "Route": route.lstrip("/"),
            })
            result.add("PageRoute", route, route_id)

    for order, block_def in enumerate(blocks):
        label = block_label(block_def, order)
        block_data = {
            "PageId": page_id,
            "BlockTypeId": block_type_ids[order],
            "Zone": block_def.get("zone", "Main"),
            "Name": block_def.get("name", ""),
            "Order": block_def.get("order", order),
            "IsSystem": False,
        }

        with step(result, "Block", label):
            block_id = client.post("Blocks", block_data)
            result.add("Block", label, block_id)

        apply_settings(result, client, "Blocks", block_id, label,
                       block_def.get("settings", {}))


def add_workflow_action(result, plan, client, catalog):
    mod = plan["modification"]
    activity_id = mod["activity_type_id"]
    action_def = mod["action"]

    with step(result, "ActionType", action_def["name"]):
        entity_type_id = resolve_named("action_type", action_def["action_type"],
                                       resolve_action_type, catalog)
        next_order = _next_order(client, "WorkflowActionTypes", f"ActivityTypeId eq {activity_id}")

    action_data = {
        "ActivityTypeId": activity_id,
        "Name": action_def["name"],
        "EntityTypeId": entity_type_id,
        "Order": action_def.get("order", next_order),
        "IsActionCompletedOnSuccess": action_def.get("complete_on_success", True),
        "IsActivityCompletedOnSuccess": action_def.get("complete_activity_on_success", False),
    }

    with step(result, "ActionType", action_def["name"]):
        action_id = client.post("WorkflowActionTypes", action_data)
        result.add("ActionType", action_def["name"], action_id)

    apply_settings(result, client, "WorkflowActionTypes", action_id,
                   action_def["name"], action_def.get("settings", {}))


def add_page_block(result, plan, client, catalog):
    mod = plan["modification"]
    page_id = mod["page_id"]
    block_def = mod["block"]
    label = block_def.get("name", "new block")

    zone = block_def.get("zone", "Main")

    with step(result, "Block", label):
        block_type_id = resolve_ref(block_def, "block_type_id", "block_type",
                                    resolve_block_type, catalog)
        next_order = _next_order(client, "Blocks",
                                 f"PageId eq {page_id} and Zone eq '{odata_str(zone)}'")

    block_data = {
        "PageId": page_id,
        "BlockTypeId": block_type_id,
        "Zone": zone,
        "Name": block_def.get("name", ""),
        "Order": block_def.get("order", next_order),
        "IsSystem": False,
    }

    with step(result, "Block", label):
        block_id = client.post("Blocks", block_data)
        result.add("Block", label, block_id)

    apply_settings(result, client, "Blocks", block_id, label,
                   block_def.get("settings", {}))


def update_workflow(result, plan, client):
    mod = plan["modification"]
    wf_id = mod["workflow_type_id"]
    updates = mod["updates"]

    field_map = {
        "name": "Name", "description": "Description", "is_active": "IsActive",
        "is_persisted": "IsPersisted", "processing_interval": "ProcessingIntervalSeconds",
        "category_id": "CategoryId",
    }

    with step(result, "WorkflowType", str(wf_id)):
        data = {}
        for key, value in updates.items():
            if key == "category":
                data["CategoryId"] = resolve_named("category", value,
                                                   resolve_workflow_category, client)
            else:
                data[rock_field(field_map, key, ("category",))] = value

        client.patch(f"WorkflowTypes/{wf_id}", data)
        result.add("WorkflowType", f"updated {wf_id}")


def update_activity(result, plan, client):
    mod = plan["modification"]
    act_id = mod["activity_type_id"]
    updates = mod["updates"]

    field_map = {
        "name": "Name", "description": "Description",
        "is_activated_with_workflow": "IsActivatedWithWorkflow",
        "order": "Order", "is_active": "IsActive",
    }

    with step(result, "ActivityType", str(act_id)):
        data = {rock_field(field_map, k): v for k, v in updates.items()}
        client.patch(f"WorkflowActivityTypes/{act_id}", data)
        result.add("ActivityType", f"updated {act_id}")


def update_action(result, plan, client, catalog):
    mod = plan["modification"]
    action_id = mod["action_type_id"]

    updates = mod.get("updates", {})
    if updates:
        field_map = {
            "name": "Name", "order": "Order",
            "complete_on_success": "IsActionCompletedOnSuccess",
            "complete_activity_on_success": "IsActivityCompletedOnSuccess",
        }

        with step(result, "ActionType", str(action_id)):
            data = {}
            for key, value in updates.items():
                if key == "action_type":
                    data["EntityTypeId"] = resolve_named("action_type", value,
                                                         resolve_action_type, catalog)
                else:
                    data[rock_field(field_map, key, ("action_type",))] = value

            client.patch(f"WorkflowActionTypes/{action_id}", data)
            result.add("ActionType", f"updated {action_id}")

    apply_settings(result, client, "WorkflowActionTypes", action_id,
                   f"action {action_id}", mod.get("settings", {}))


def delete_action(result, plan, client):
    action_id = plan["modification"]["action_type_id"]

    with step(result, "ActionType", str(action_id)):
        client.delete(f"WorkflowActionTypes/{action_id}")
        result.add("ActionType", f"deleted {action_id}")


def delete_activity(result, plan, client):
    act_id = plan["modification"]["activity_type_id"]

    with step(result, "ActivityType", str(act_id)):
        actions = client.get("WorkflowActionTypes", params={
            "$filter": f"ActivityTypeId eq {act_id}",
            "$select": "Id,Name",
        })

    for action in (actions or []):
        with step(result, "ActionType", action.get("Name", str(action["Id"]))):
            client.delete(f"WorkflowActionTypes/{action['Id']}")
            result.add("ActionType", f"deleted {action['Name']}", action["Id"])

    with step(result, "ActivityType", str(act_id)):
        client.delete(f"WorkflowActivityTypes/{act_id}")
        result.add("ActivityType", f"deleted {act_id}")


def reorder_actions(result, plan, client):
    mod = plan["modification"]

    for i, action_id in enumerate(mod["action_order"]):
        with step(result, "ActionType", str(action_id)):
            client.patch(f"WorkflowActionTypes/{action_id}", {"Order": i})
            result.add("ActionType", f"reordered {action_id} -> {i}")


def move_action(result, plan, client):
    mod = plan["modification"]
    action_id = mod["action_type_id"]
    new_activity_id = mod["target_activity_type_id"]

    with step(result, "ActionType", str(action_id)):
        next_order = _next_order(client, "WorkflowActionTypes",
                                 f"ActivityTypeId eq {new_activity_id}")
        client.patch(f"WorkflowActionTypes/{action_id}", {
            "ActivityTypeId": new_activity_id,
            "Order": mod.get("order", next_order),
        })
        result.add("ActionType", f"moved {action_id} to activity {new_activity_id}")


def location_label(location):
    return f"location {location}" if is_id(location) else location


def create_checkin_area(result, plan, client):
    area = plan["checkin_area"]
    locations = area.get("locations", [])

    with lookup(result, "Group", area["name"]):
        group_type_id = resolve_ref(area, "group_type_id", "group_type",
                                    resolve_group_type, client)

    location_ids = []
    for location in locations:
        with lookup(result, "GroupLocation", location_label(location)):
            location_id = location if is_id(location) else resolve_location(client, location)
            if location_id in location_ids:
                raise PlanError(f"location {location_id} is already in the list. "
                                "List each location once.")
            location_ids.append(location_id)

    if result.failures:
        raise StepFailed

    group_data = {
        "Name": area["name"],
        "GroupTypeId": group_type_id,
        "IsActive": True,
        "IsPublic": area.get("is_public", True),
    }
    if area.get("parent_group_id"):
        group_data["ParentGroupId"] = area["parent_group_id"]
    if area.get("campus_id"):
        group_data["CampusId"] = area["campus_id"]
    if area.get("description"):
        group_data["Description"] = area["description"]

    with step(result, "Group", area["name"]):
        group_id = client.post("Groups", group_data)
        result.add("Group", area["name"], group_id)

    for order, (location, location_id) in enumerate(zip(locations, location_ids, strict=True)):
        label = location_label(location)
        with step(result, "GroupLocation", label):
            group_location_id = client.post("GroupLocations", {
                "GroupId": group_id,
                "LocationId": location_id,
                "Order": order,
            })
            result.add("GroupLocation", label, group_location_id)


GROUP_FIELDS = {
    "name": "Name", "description": "Description", "is_active": "IsActive",
    "is_public": "IsPublic", "is_security_role": "IsSecurityRole",
    "campus_id": "CampusId", "parent_group_id": "ParentGroupId",
    "schedule_id": "ScheduleId", "group_capacity": "GroupCapacity",
    "order": "Order",
}


def create_group(result, plan, client):
    grp = plan["group"]

    with step(result, "Group", grp["name"]):
        group_type_id = resolve_ref(grp, "group_type_id", "group_type",
                                    resolve_group_type, client)

    data = {
        "Name": grp["name"],
        "GroupTypeId": group_type_id,
        "IsActive": grp.get("is_active", True),
        "IsPublic": grp.get("is_public", True),
        "IsSecurityRole": grp.get("is_security_role", False),
        "Order": grp.get("order", 0),
    }
    for key in ("parent_group_id", "campus_id", "description", "schedule_id",
                "group_capacity"):
        if grp.get(key) is not None:
            data[GROUP_FIELDS[key]] = grp[key]

    with step(result, "Group", grp["name"]):
        group_id = client.post("Groups", data)
        result.add("Group", grp["name"], group_id)

    apply_settings(result, client, "Groups", group_id, grp["name"],
                   grp.get("settings", {}))


def update_group(result, plan, client):
    mod = plan["modification"]
    group_id = mod["group_id"]

    with step(result, "Group", str(group_id)):
        data = {rock_field(GROUP_FIELDS, k): v for k, v in mod["updates"].items()}
        client.patch(f"Groups/{group_id}", data)
        result.add("Group", f"updated {group_id}")

    apply_settings(result, client, "Groups", group_id, f"group {group_id}",
                   mod.get("settings", {}))


def add_group_member(result, plan, client):
    mod = plan["modification"]
    group_id = mod["group_id"]
    person_id = mod["person_id"]
    label = f"person {person_id} in group {group_id}"

    with step(result, "GroupMember", label):
        status = member_status(mod.get("status", "active"))
        role_id = resolve_ref(mod, "group_role_id", "role",
                              resolve_group_role, client, group_id)

    data = {
        "GroupId": group_id,
        "PersonId": person_id,
        "GroupRoleId": role_id,
        "GroupMemberStatus": status,
        "IsNotified": mod.get("is_notified", False),
        "IsArchived": False,
    }
    if mod.get("note"):
        data["Note"] = mod["note"]
    if mod.get("order") is not None:
        data["GroupOrder"] = mod["order"]

    with step(result, "GroupMember", label):
        member_id = client.post("GroupMembers", data)
        result.add("GroupMember", label, member_id)


GROUP_MEMBER_FIELDS = {
    "group_role_id": "GroupRoleId", "note": "Note", "is_notified": "IsNotified",
    "order": "GroupOrder", "guest_count": "GuestCount",
}

RESTORED_MEMBER = {"IsArchived": False, "ArchivedDateTime": None, "ArchivedByPersonAliasId": None}


def update_group_member(result, plan, client):
    mod = plan["modification"]
    member_id = mod["group_member_id"]

    with step(result, "GroupMember", str(member_id)):
        data = {}
        for key, value in mod["updates"].items():
            if key == "status":
                data["GroupMemberStatus"] = member_status(value)
            elif key == "role":
                role_id = resolve_member_role(client, member_id, value)
                if role_id is None:
                    raise PlanError(f"no role {value!r} in this member's group. Role "
                                    f"names belong to the group type, so take it from "
                                    f"the group's own roster.")
                data["GroupRoleId"] = role_id
            elif key == "is_archived":
                if value is not False:
                    raise PlanError("\"is_archived\" can only be false here, which restores an "
                                    "archived membership. To archive one, use "
                                    "\"remove_group_member\": Rock archives the membership "
                                    "itself, with the date, when its group type keeps history, "
                                    "and deletes it otherwise.")
                data.update(RESTORED_MEMBER)
            else:
                data[rock_field(GROUP_MEMBER_FIELDS, key,
                                ("status", "role", "is_archived"))] = value

        client.patch(f"GroupMembers/{member_id}", data)
        result.add("GroupMember", f"updated {member_id}")


def remove_group_member(result, plan, client):
    member_id = plan["modification"]["group_member_id"]

    with step(result, "GroupMember", str(member_id)):
        client.delete(f"GroupMembers/{member_id}")
        result.add("GroupMember", f"removed {member_id}")


def create_group_sync(result, plan, client):
    mod = plan["modification"]
    group_id = mod["group_id"]
    label = f"sync on group {group_id}"

    with step(result, "GroupSync", label):
        role_id = resolve_ref(mod, "group_type_role_id", "role",
                              resolve_group_role, client, group_id)
        data_view_id = resolve_ref(mod, "sync_data_view_id", "data_view",
                                   resolve_data_view, client)

    data = {
        "GroupId": group_id,
        "GroupTypeRoleId": role_id,
        "SyncDataViewId": data_view_id,
    }
    for key, field in (("add_user_accounts", "AddUserAccountsDuringSync"),
                       ("schedule_interval_minutes", "ScheduleIntervalMinutes"),
                       ("welcome_email_id", "WelcomeSystemCommunicationId"),
                       ("exit_email_id", "ExitSystemCommunicationId")):
        if mod.get(key) is not None:
            data[field] = mod[key]

    with step(result, "GroupSync", label):
        sync_id = client.post("GroupSyncs", data)
        result.add("GroupSync", label, sync_id)


API_METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")


def check_request(method, endpoint, req):
    if method not in API_METHODS:
        raise PlanError(f"method must be one of {', '.join(API_METHODS)}, got {method!r}")

    if not endpoint:
        raise PlanError("endpoint is required, e.g. \"GroupSyncs/12\"")

    # `requests` sends %2e%2e untouched and the server decodes it, so check both forms.
    for form in (endpoint, unquote(endpoint)):
        if ("://" in form or form.startswith("/")
                or ".." in form.replace("\\", "/").split("/")):
            raise PlanError("endpoint must be a path under /api/, with no scheme, no "
                            "leading slash and no '..', encoded or not")

    body = req.get("body")
    # Rock answers an empty PATCH with 200 and no change, and an empty PUT nulls the row.
    if method in ("PATCH", "PUT") and not (isinstance(body, dict) and body):
        raise PlanError(f"{method} needs a non-empty \"body\" object holding the fields "
                        f"to send. Read the entity with a GET first if you need its "
                        f"field names.")

    if method == "PUT" and req.get("full_replace") is not True:
        raise PlanError("PUT replaces the whole entity in Rock: every field absent from "
                        "the body is set to null, the created-by audit is lost, and the "
                        "row gets a new Guid. Use PATCH to change some fields. If you "
                        "really mean to replace the entity, read it first and send it "
                        "back whole with \"full_replace\": true.")


def api_request(result, plan, client):
    req = plan["request"]
    method = str(req.get("method", "")).strip().upper()
    endpoint = str(req.get("endpoint", "")).strip()
    label = f"{method} {endpoint}".strip() or "api_request"
    params = req.get("params")
    body = req.get("body")

    with step(result, "Request", label):
        check_request(method, endpoint, req)

        print(f"  {method} /api/{endpoint}" + (f"  params={params}" if params else ""))
        if method == "GET":
            print(json.dumps(client.get(endpoint, params=params), indent=2, default=str))
            result.add("Request", label)
        elif method == "POST":
            result.add("Request", label, client.post(endpoint, body, params=params))
        elif method == "PATCH":
            client.patch(endpoint, body, params=params)
            result.add("Request", label)
        elif method == "PUT":
            # No snapshot, no PUT: a full replace has no other undo.
            saved = snapshot_entity(client, endpoint)
            print(f"  saved the current entity to {saved}")
            client.put(endpoint, body, full_replace=True, params=params)
            result.add("Request", label)
        else:
            client.delete(endpoint, params=params)
            result.add("Request", label)


def snapshot_entity(client, endpoint):
    current = client.get(endpoint)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = endpoint.strip("/").replace("/", "-")
    rock_paths.SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = rock_paths.SNAPSHOTS / f"{slug}-{stamp}.json"
    path.write_text(json.dumps(current, indent=2, default=str))
    log.info("snapshot %s -> %s", endpoint, path)
    return path


def require_writes_enabled(operation):
    refuse_unless_writes_enabled(
        f"Refusing to run '{operation}': everything in this script changes Rock, "
        f"and ROCK_ALLOW_WRITES is not set.\n"
        f"Run it as `rock.sh build <plan.json>`, which sets it."
    )


OPERATIONS = {
    "create_workflow": create_workflow,
    "create_page": create_page,
    "add_action": add_workflow_action,
    "add_block": add_page_block,
    "update_workflow": update_workflow,
    "update_activity": update_activity,
    "update_action": update_action,
    "delete_action": delete_action,
    "delete_activity": delete_activity,
    "reorder_actions": reorder_actions,
    "move_action": move_action,
    "create_checkin_area": create_checkin_area,
    "create_group": create_group,
    "update_group": update_group,
    "add_group_member": add_group_member,
    "update_group_member": update_group_member,
    "remove_group_member": remove_group_member,
    "create_group_sync": create_group_sync,
    "api_request": api_request,
}

NEEDS_CATALOG = {name for name, handler in OPERATIONS.items()
                 if "catalog" in inspect.signature(handler).parameters}


def run_plan(plan, connect):
    result = BuildResult()
    _apply_plan(result, without_nulls(plan), connect)
    result.report()
    return result


def _apply_plan(result, plan, connect):
    operation = plan.get("operation")
    handler = OPERATIONS.get(operation)
    if not handler:
        result.fail("Operation", str(operation),
                    f"unknown operation: {operation!r}. Supported: {', '.join(OPERATIONS)}")
        return

    require_writes_enabled(operation)

    catalog = None
    if operation in NEEDS_CATALOG:
        try:
            catalog = load_catalog()
        except CatalogUnreadable as exc:
            result.fail("Catalog", operation, exc)
            return
        if catalog is None:
            result.fail("Catalog", operation, "no catalog found. Refresh it: rock.sh catalog refresh")
            return

    problems = plan_problems(operation, plan)
    for problem in problems:
        result.fail("Plan", operation, problem)
    if problems:
        return

    rock_url, username, password = get_credentials()
    if operation in NEEDS_CATALOG:
        mismatch = catalog_mismatch(catalog, rock_url)
        if mismatch:
            result.fail("Catalog", operation, mismatch)
            return

    log.info("build operation=%s", operation)
    # connect() logs in, so a gate below this line lets a refused plan reach Rock.
    client = connect(rock_url, username, password)
    handler_args = (result, plan, client)
    if operation in NEEDS_CATALOG:
        handler_args += (catalog,)
    try:
        handler(*handler_args)
    except StepFailed:
        pass
    except PlanError as exc:
        result.fail("Plan", operation, exc)
    except Exception as exc:
        result.fail("Operation", operation, exc)


def read_plan():
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        source = Path(sys.argv[1]).resolve()
        if not source.is_relative_to(Path("/tmp").resolve()):
            print(f"Error: build plan must be under /tmp/, got: {source}")
            sys.exit(1)
        try:
            text = source.read_bytes()
        except FileNotFoundError:
            print(f"Error: file not found: {source}")
            sys.exit(1)
        except OSError as exc:
            print(f"Error: cannot read {source}: {exc.strerror}")
            sys.exit(1)
    else:
        source = "the plan on stdin"
        text = sys.stdin.buffer.read()

    try:
        plan = json.loads(text)
    except ValueError as exc:
        print(f"Error: {source} is not valid JSON: {exc}")
        sys.exit(1)
    if not isinstance(plan, dict):
        print(f'Error: {source} must hold one JSON object with an "operation" key. '
              f"One plan builds one operation.")
        sys.exit(1)
    return plan


def main():
    plan = read_plan()
    with api_errors_reported():
        result = run_plan(plan, RockClient)
    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
