#!/usr/bin/env python3
"""
AI Harness Installer — data-driven from harnesses.toml

This is the single source of truth for installing/uninstalling skills and
per-harness config files across all supported AI coding tools.

Usage:
    ./install.py [harness|all]...
    ./install.py --uninstall [harness|all]...

The old install.sh / uninstall.sh are thin wrappers for convenience.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

REPO_DIR = Path(__file__).resolve().parent
CONFIG_FILE = REPO_DIR / "harnesses.toml"


def expand_path(p: str) -> Path:
    """Expand ~ and make absolute."""
    return Path(p).expanduser().resolve()


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        print(f"ERROR: {CONFIG_FILE} not found", file=sys.stderr)
        sys.exit(1)
    with CONFIG_FILE.open("rb") as f:
        return tomllib.load(f)


def get_harness_names(config: dict[str, Any]) -> list[str]:
    # Top-level tables that are not sections like "comment" keys
    return [k for k in config if isinstance(config[k], dict) and "target" in config[k]]


def backup_path(target: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    while True:
        backup = target.with_name(f"{target.name}.bak.{timestamp}.{uuid4().hex}")
        if not backup.exists() and not backup.is_symlink():
            return backup


def link_file(source: Path, target: Path, *, dry_run: bool = False) -> None:
    """Create a symlink from source to target, with backup if needed."""
    if not source.exists():
        print(f"    SKIP {target.name} (source missing: {source})")
        return

    if target.is_symlink() and target.resolve() == source.resolve():
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


def is_managed_link(source: Path, target: Path) -> bool:
    # Match the link we install, even when its source is missing or is itself a symlink.
    return target.is_symlink() and target.readlink() == source


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


def link_children(source_dir: Path, target_dir: Path, *, dry_run: bool) -> None:
    if not source_dir.is_dir():
        print(f"    SKIP {target_dir.name} (source dir missing)")
        return

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
    if target_dir.is_dir():
        for child in sorted(target_dir.iterdir()):
            source = source_dir / child.name
            if not source.exists() and remove_managed_link(source, child, dry_run=dry_run):
                print(f"    REMOVE stale {child.name}")

    for source in sorted(source_dir.iterdir()):
        if source.is_dir() or source.is_file():
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


def configure_harness(name: str, config: dict[str, Any], *, uninstall: bool, dry_run: bool) -> None:
    target_dir = expand_path(config["target"])
    action = "Uninstalling" if uninstall else "Installing"
    print(f"\n{action} {name}...")
    print(f"  Target: {target_dir}")

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

    for name in selected:
        configure_harness(name, config[name], uninstall=args.uninstall, dry_run=args.dry_run)

    if not args.dry_run:
        print("\nDone. Restart your coding harness(es) to pick up changes.")


if __name__ == "__main__":
    main()
