import json
import os
import sys
import tempfile
from datetime import datetime, timezone

from rock_client import RockApiError, RockClient, RockError, api_errors_reported
from rock_log import get_logger
from rock_text import plural
import rock_paths

log = get_logger("rock.catalog")

rock_paths.ensure()
CATALOG_PATH = rock_paths.CATALOG

PAGE = 500

ACTION_ASSEMBLIES = ("Rock", "com.bemaservices", "com.kfs")

USAGE = "Usage: rock.sh catalog status | refresh | show [text]"


def get_all(client, endpoint, params=None, page=PAGE):
    """Pages with $skip, because one capped request drops the tail of the list without saying so."""
    params = dict(params or {})
    params.pop("$top", None)
    params.pop("$skip", None)
    rows, skip = [], 0
    while True:
        batch = client.get(endpoint, params={**params, "$top": page, "$skip": skip})
        if not batch:
            return rows
        rows += batch
        if len(batch) < page:
            return rows
        skip += page


class CatalogUnreadable(RockError):
    def operator_message(self):
        return f"Error: {self}"


def load_catalog():
    try:
        return json.loads(CATALOG_PATH.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise CatalogUnreadable(
            f"{CATALOG_PATH.name} cannot be read ({exc}). Refresh it: rock.sh catalog refresh") from exc


def catalog_mismatch(catalog, rock_url):
    if catalog.get("instance_url") == rock_url:
        return None
    return (f"{CATALOG_PATH.name} is from {catalog.get('instance_url')}, not {rock_url}, and IDs differ between "
            "Rock instances. Refresh it: rock.sh catalog refresh")


def save_catalog(catalog):
    fd, temporary = tempfile.mkstemp(dir=CATALOG_PATH.parent, prefix="catalog.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(catalog, f, indent=2)
        os.replace(temporary, CATALOG_PATH)
    except BaseException:
        os.unlink(temporary)
        raise


def fetch_action_components(client):
    # Current Rock answers IsComponent with a 400, so the workflow scan below is the path that runs.
    actions = []
    try:
        all_types = get_all(client, "EntityTypes", params={
            "$filter": "IsComponent eq true",
            "$select": "Id,Name,FriendlyName,AssemblyName",
        })
    except RockApiError as exc:
        if exc.status != 400:
            raise
        log.info("Rock refused the IsComponent filter, so the workflow scan runs: %s", exc)
        all_types = []
    for et in all_types:
        name = et.get("Name", "")
        assembly = et.get("AssemblyName", "")
        if not any(name.startswith(f"{p}.Workflow.Action")
                   for p in ACTION_ASSEMBLIES):
            if "WorkflowAction" not in name:
                continue
        actions.append({
            "entity_type_id": et["Id"],
            "name": et.get("FriendlyName") or name.split(".")[-1],
            "class_name": name,
            "assembly": assembly,
        })

    source = "components"

    if not actions:
        source = "workflow-scan"
        print("  This Rock has no component list, so reading action types off existing workflows...")
        existing = get_all(client, "WorkflowActionTypes", params={
            "$select": "EntityTypeId",
        })
        if existing:
            seen_ids = set()
            entity_type_ids = []
            for wa in existing:
                eid = wa.get("EntityTypeId")
                if eid and eid not in seen_ids:
                    seen_ids.add(eid)
                    entity_type_ids.append(eid)
            for eid in entity_type_ids:
                et = client.get(f"EntityTypes/{eid}")
                actions.append({
                    "entity_type_id": et["Id"],
                    "name": et.get("FriendlyName") or et.get("Name", "").split(".")[-1],
                    "class_name": et.get("Name", ""),
                    "assembly": et.get("AssemblyName", ""),
                })

    return sorted(actions, key=lambda a: a["name"]), source


def fetch_block_types(client):
    blocks = get_all(client, "BlockTypes", params={
        "$select": "Id,Name,Description,Category",
        "$orderby": "Name",
    })
    if not blocks:
        return []
    return [{
        "id": b["Id"],
        "name": b.get("Name", ""),
        "description": b.get("Description", ""),
        "category": b.get("Category", ""),
    } for b in blocks]


def fetch_field_types(client):
    fields = get_all(client, "FieldTypes", params={
        "$select": "Id,Name,Description,Assembly,Class",
        "$orderby": "Name",
    })
    if not fields:
        return []
    return [{
        "id": f["Id"],
        "name": f.get("Name", ""),
        "description": f.get("Description", ""),
        "class_name": f.get("Class", ""),
    } for f in fields]


def fetch_categories(client):
    cats = get_all(client, "Categories", params={
        "$select": "Id,Name,ParentCategoryId,EntityTypeId",
        "$orderby": "Name",
    })
    if not cats:
        return []
    return [{
        "id": c["Id"],
        "name": c.get("Name", ""),
        "parent_id": c.get("ParentCategoryId"),
        "entity_type_id": c.get("EntityTypeId"),
    } for c in cats]


def fetch_sites(client):
    sites = get_all(client, "Sites", params={
        "$select": "Id,Name,IsActive",
    })
    if not sites:
        return []
    return [{
        "id": s["Id"],
        "name": s.get("Name", ""),
        "is_active": s.get("IsActive", False),
    } for s in sites]


def fetch_layouts(client):
    layouts = get_all(client, "Layouts", params={
        "$select": "Id,Name,SiteId,FileName",
    })
    if not layouts:
        return []
    return [{
        "id": layout["Id"],
        "name": layout.get("Name", ""),
        "site_id": layout.get("SiteId"),
        "file_name": layout.get("FileName", ""),
    } for layout in layouts]


def refresh(client):
    print("Refreshing Rock catalog...")

    print("  Fetching action components...")
    actions, actions_source = fetch_action_components(client)
    scope = "in use" if actions_source == "workflow-scan" else "available"
    print(f"    {plural(len(actions), 'action type')} ({scope})")

    print("  Fetching block types...")
    blocks = fetch_block_types(client)
    print(f"    {plural(len(blocks), 'block type')}")

    print("  Fetching field types...")
    fields = fetch_field_types(client)
    print(f"    {plural(len(fields), 'field type')}")

    print("  Fetching categories...")
    categories = fetch_categories(client)
    print(f"    {plural(len(categories), 'category', 'categories')}")

    print("  Fetching sites...")
    sites = fetch_sites(client)
    print(f"    {plural(len(sites), 'site')}")

    print("  Fetching layouts...")
    layouts = fetch_layouts(client)
    print(f"    {plural(len(layouts), 'layout')}")

    catalog = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "instance_url": client.base_url,
        "action_components": actions,
        "action_components_source": actions_source,
        "block_types": blocks,
        "field_types": fields,
        "categories": categories,
        "sites": sites,
        "layouts": layouts,
    }

    save_catalog(catalog)
    log.info("catalog refreshed: %d actions, %d blocks, %d fields, %d categories",
             len(actions), len(blocks), len(fields), len(categories))
    print(f"\nCatalog saved to {CATALOG_PATH.name}")
    return catalog


def entry(name, detail=""):
    return f"  {name:40s} {detail}" if detail else f"  {name}"


def show_section(title, rows, text, scope=""):
    shown = [(name, detail) for name, detail in rows if text in name.casefold() or text in detail.casefold()]
    scope = f" {scope}" if scope else ""
    if not shown:
        print(f"{title} (none of {len(rows)}{scope})" if rows else f"{title} (none{scope})")
    elif text:
        print(f"{title} ({len(shown)} of {len(rows)}{scope}):")
    else:
        print(f"{title} ({len(rows)}{scope}):")
    for name, detail in shown:
        print(entry(name, detail))


def show(text=""):
    catalog = load_catalog()
    if not catalog:
        print("No catalog found. Refresh it: rock.sh catalog refresh")
        sys.exit(1)

    print(f"Rock RMS Catalog (refreshed: {catalog['refreshed_at'][:19]})")
    print(f"Instance: {catalog['instance_url']}")
    if text:
        print(f'Only the entries that contain "{text}", ignoring case.')
    text = text.casefold()

    scanned = catalog.get("action_components_source") == "workflow-scan"
    print()
    show_section("Action Components",
                 [(a["name"], a["class_name"]) for a in catalog.get("action_components", [])],
                 text, "in use" if scanned else "available")
    if scanned:
        print("This Rock has no component list, so the catalog holds only the action types its workflows "
              "already use.")
        print("An action type missing here may still be available.")

    print()
    show_section("Block Types",
                 [(b["name"], f"[{b['category']}]" if b.get("category") else "")
                  for b in catalog.get("block_types", [])],
                 text)

    print()
    show_section("Field Types", [(f["name"], "") for f in catalog.get("field_types", [])], text)

    sites = sorted(catalog.get("sites", []), key=lambda s: s["name"].casefold())
    print()
    show_section("Sites", [(s["name"], "(active)" if s.get("is_active") else "(inactive)") for s in sites], text)

    site_names = {s["id"]: s["name"] for s in sites}
    layouts = sorted(((layout["name"], site_names.get(layout["site_id"], f"site {layout['site_id']}"))
                      for layout in catalog.get("layouts", [])),
                     key=lambda row: (row[1].casefold(), row[0].casefold()))
    print()
    show_section("Layouts", layouts, text)


def main():
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    with api_errors_reported():
        _dispatch(sys.argv[1], sys.argv[2:])


def status():
    client = RockClient()
    campuses = client.get("Campuses", params={"$top": 1})
    try:
        version = client.get("Utility/GetRockSemanticVersionNumber") or "unknown"
    except RockApiError as exc:
        version = f"unknown (Rock answered {exc.status} to {exc.endpoint})"

    print(f"Connected to Rock RMS at {client.base_url}")
    if campuses:
        print(f"  Campus: {campuses[0].get('Name', 'unknown')}")
    print(f"  Version: {version}")
    try:
        catalog = load_catalog()
    except CatalogUnreadable as exc:
        print(f"  Catalog: {exc}")
        return
    if not catalog:
        print("  Catalog: not cached (refresh it: rock.sh catalog refresh)")
        return
    mismatch = catalog_mismatch(catalog, client.base_url)
    if mismatch:
        print(f"  Catalog: {mismatch}")
        return
    print(f"  Catalog: {catalog['refreshed_at'][:19]}")
    print(f"  Actions: {len(catalog.get('action_components', []))}")
    print(f"  Blocks:  {len(catalog.get('block_types', []))}")
    print(f"  Fields:  {len(catalog.get('field_types', []))}")


def _dispatch(cmd, args):
    if cmd == "status" and not args:
        status()

    elif cmd == "refresh" and not args:
        client = RockClient()
        refresh(client)

    elif cmd == "show":
        show(" ".join(args).strip())

    elif cmd in ("status", "refresh"):
        print(f"Unknown argument: {' '.join(args)}")
        print(USAGE)
        sys.exit(1)

    else:
        print(f"Unknown command: {cmd}")
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()
