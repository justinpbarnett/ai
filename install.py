#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

try:
    import tomllib
except ModuleNotFoundError:
    sys.exit(f"ERROR: install.py needs Python 3.11 or newer for tomllib; found {sys.version.split()[0]}")

REPO_DIR = Path(__file__).resolve().parent
CONFIG_FILE = REPO_DIR / "harnesses.toml"


def expand_path(p: str) -> Path:
    return Path(p).expanduser().resolve()


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        print(f"ERROR: {CONFIG_FILE} not found", file=sys.stderr)
        sys.exit(1)
    with CONFIG_FILE.open("rb") as f:
        return tomllib.load(f)


def get_harness_names(config: dict[str, Any]) -> list[str]:
    return [k for k in config if isinstance(config[k], dict) and "target" in config[k]]


def backup_path(target: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    while True:
        backup = target.with_name(f"{target.name}.bak.{timestamp}.{uuid4().hex}")
        if not backup.exists() and not backup.is_symlink():
            return backup


def is_managed_link(source: Path, target: Path) -> bool:
    return target.is_symlink() and target.resolve() == source.resolve()


def link_file(source: Path, target: Path, *, dry_run: bool = False) -> None:
    if not source.exists():
        print(f"    SKIP {target.name} (source missing: {source})")
        return

    if is_managed_link(source, target):
        print(f"    KEEP {target.name}")
        return

    if target.exists() or target.is_symlink():
        backup = backup_path(target)
        if not dry_run:
            target.rename(backup)
        print(f"    BACKUP {target.name} -> {backup.name}")

    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)

    print(f"    LINK {target.name} -> {source}")


def remove_managed_link(source: Path, target: Path, *, dry_run: bool) -> bool:
    if not is_managed_link(source, target):
        return False
    if not dry_run:
        target.unlink()
    return True


def seed_local_config(seed: Path, legacy_source: Path, target: Path, *, dry_run: bool) -> None:
    migrating = is_managed_link(legacy_source, target)
    if not migrating and (target.exists() or target.is_symlink()):
        print(f"    KEEP {target.name} (local config)")
        return

    source = legacy_source if migrating else seed
    if not source.is_file():
        print(f"    SKIP {target.name} (source missing: {source})")
        return

    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".config-", dir=target.parent) as directory:
            staged = Path(directory) / target.name
            staged.write_bytes(source.read_bytes())
            staged.chmod(0o600)
            if migrating and is_managed_link(legacy_source, target):
                staged.replace(target)
            else:
                try:
                    target.hardlink_to(staged)
                except FileExistsError:
                    print(f"    KEEP {target.name} (local config)")
                    return

    action = "LOCALIZE" if migrating else "SEED"
    print(f"    {action} {target.name} from {source}")


def is_skill_dir(path: Path) -> bool:
    return path.is_dir() and (path / "SKILL.md").is_file()


def configure_planning(config: dict[str, Any], *, uninstall: bool, dry_run: bool, optional: bool) -> None:
    target = Path(config["target"]).expanduser()
    skills_dir = target / "skills"
    context = target / "passion-planning-context.md"
    context_path = Path(config["context"])
    checkout = expand_path(os.environ.get("TECH_SKILLS_DIR") or config["checkout"])

    # The context link records the chosen checkout even if it has since moved or
    # been removed. A plain uninstall can still remove exactly its dangling links.
    if context.is_symlink():
        previous_context = context.resolve()
        if previous_context.parts[-len(context_path.parts):] == context_path.parts:
            previous = previous_context.parents[len(context_path.parts) - 1]
            if uninstall or "TECH_SKILLS_DIR" not in os.environ:
                checkout = previous

    sources = {
        skills_dir / name: checkout / root / name
        for root, names in config["skill_groups"].items()
        for name in names
    }
    context_source = checkout / context_path
    links = {context: context_source, **sources}
    # Older installs linked into an extra directory and used the upstream setup name.
    legacy_links = {}
    for destination, source in sources.items():
        if source.parent.name == "runtime":
            name = "setup-matt-pocock-skills" if destination.name == "setup-tech-skills" else destination.name
            legacy_links[skills_dir / name] = source.parent / "pocock" / name

    if skills_dir.is_symlink() or (skills_dir.exists() and not skills_dir.is_dir()):
        raise ValueError(f"existing {skills_dir} must be a real directory to manage individual planning skills")

    if uninstall:
        for destination, source in [*links.items(), *legacy_links.items()]:
            if remove_managed_link(source, destination, dry_run=dry_run):
                print(f"    REMOVE {destination}")
        return

    missing = [source for source in sources.values() if not is_skill_dir(source)]
    if not context_source.is_file():
        missing.append(context_source)
    if missing:
        message = (
            f"shared planning is unavailable in {checkout} (missing {missing[0].relative_to(checkout)}). "
            "Set TECH_SKILLS_DIR to a checkout with the planning skills."
        )
        if optional and "TECH_SKILLS_DIR" not in os.environ:
            print(f"    SKIP {message}")
            return
        raise ValueError(message)

    for destination, source in links.items():
        if destination.exists() or destination.is_symlink():
            if destination in legacy_links and is_managed_link(legacy_links[destination], destination):
                continue
            if not is_managed_link(source, destination):
                raise ValueError(f"{destination} already exists and points elsewhere; left the installation untouched")

    for destination, source in legacy_links.items():
        if remove_managed_link(source, destination, dry_run=dry_run):
            print(f"    REMOVE old planning link {destination}")

    for destination, source in links.items():
        if is_managed_link(source, destination):
            print(f"    KEEP {destination}")
            continue
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                destination.symlink_to(source)
            except FileExistsError:
                if not is_managed_link(source, destination):
                    raise
        print(f"    LINK {destination} -> {source}")


def link_children(source_dir: Path, target_dir: Path, *, dry_run: bool) -> None:
    if not source_dir.is_dir():
        print(f"    SKIP {target_dir.name} (source dir missing)")
        return

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
    if target_dir.is_dir():
        for child in sorted(target_dir.iterdir()):
            source = source_dir / child.name
            if not is_skill_dir(source) and remove_managed_link(source, child, dry_run=dry_run):
                print(f"    REMOVE stale {child.name}")

    for source in sorted(source_dir.iterdir()):
        if is_skill_dir(source):
            link_file(source, target_dir / source.name, dry_run=dry_run)


def unlink_children(source_dir: Path, target_dir: Path, *, dry_run: bool) -> None:
    if not target_dir.is_dir():
        return

    removed = remaining = False
    for child in sorted(target_dir.iterdir()):
        if remove_managed_link(source_dir / child.name, child, dry_run=dry_run):
            removed = True
            print(f"    REMOVE {child.name}")
        else:
            remaining = True

    if removed and not remaining and not target_dir.is_symlink():
        if not dry_run:
            target_dir.rmdir()
        print(f"    RMDIR {target_dir.name}")


def run_script(script_name: str, args: list[str], target_dir: Path, target_env: str, *, dry_run: bool) -> None:
    command = [str(REPO_DIR / script_name), *args]
    if dry_run:
        print(f"    WOULD RUN {' '.join(command)} ({target_env}={target_dir})")
        return
    sys.stdout.flush()
    subprocess.run(command, check=True, env={**os.environ, target_env: str(target_dir)})


def run_scripted_installer(config: dict[str, Any], target_dir: Path, *, uninstall: bool, dry_run: bool) -> None:
    target_env = config["target_env"]
    if uninstall:
        run_script(config["uninstaller"], ["--dry-run"] if dry_run else [], target_dir, target_env, dry_run=False)
    else:
        run_script(config["installer"], ["--mode", "symlink"], target_dir, target_env, dry_run=dry_run)


def resolve_target_dir(config: dict[str, Any]) -> Path:
    override = os.environ.get(config.get("target_env", ""))
    return expand_path(override or config["target"])


def configure_harness(name: str, config: dict[str, Any], *, uninstall: bool, dry_run: bool) -> None:
    target_dir = resolve_target_dir(config)
    action = "Uninstalling" if uninstall else "Installing"
    print(f"\n{action} {name}...")
    print(f"  Target: {target_dir}")

    if "installer" in config:
        run_scripted_installer(config, target_dir, uninstall=uninstall, dry_run=dry_run)
        return

    for target_name, source_path in config.get("symlinks", {}).items():
        source = REPO_DIR / source_path
        target = target_dir / target_name
        is_skills = source_path == "skills" or target_name == "skills" or target_name.endswith("-skills")
        if is_skills and config.get("skills_mode") == "children":
            if target.is_symlink():
                print(f"    SKIP {target.name} (target dir is a symlink)")
                continue
            configure_children = unlink_children if uninstall else link_children
            configure_children(source, target, dry_run=dry_run)
        elif not uninstall:
            link_file(source, target, dry_run=dry_run)
        elif remove_managed_link(source, target, dry_run=dry_run):
            print(f"    REMOVE {target.name}")

    if not uninstall:
        for target_name, spec in config.get("local_configs", {}).items():
            seed_local_config(
                REPO_DIR / spec["seed"],
                REPO_DIR / spec["legacy_link"],
                target_dir / target_name,
                dry_run=dry_run,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Install/uninstall AI coding harness configs")
    parser.add_argument("harnesses", nargs="*", help="Harness names or 'all'")
    parser.add_argument("--uninstall", "-u", action="store_true", help="Uninstall instead of install")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without making changes")
    parser.add_argument("--list", action="store_true", help="List available harnesses")
    args = parser.parse_args()

    config = load_config()
    available = get_harness_names(config)

    if args.list:
        for name in available:
            target = config[name].get("target", "")
            print(f"{name:12} -> {target}")
        return

    if not args.harnesses:
        print("Available harnesses:", ", ".join(available))
        print("Use 'all' to select everything.")
        return

    selected = []
    for h in args.harnesses:
        if h == "all":
            selected = available
            break
        if h not in available:
            print(f"Unknown harness: {h}", file=sys.stderr)
            print("Available:", ", ".join(available), file=sys.stderr)
            sys.exit(1)
        selected.append(h)

    failed = []
    for name in selected:
        try:
            if name == "planning":
                configure_planning(
                    config[name], uninstall=args.uninstall, dry_run=args.dry_run,
                    optional="all" in args.harnesses,
                )
            else:
                configure_harness(name, config[name], uninstall=args.uninstall, dry_run=args.dry_run)
        except subprocess.CalledProcessError as error:
            print(f"ERROR: {name} failed (exit {error.returncode}), continuing", file=sys.stderr)
            failed.append(name)
        except (OSError, ValueError) as error:
            print(f"ERROR: {name}: {error}", file=sys.stderr)
            failed.append(name)

    if not args.dry_run:
        print("\nDone. Restart your coding harness(es) to pick up changes.")

    if failed:
        print(f"Failed: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
