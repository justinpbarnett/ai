import re
from pathlib import Path

KIT = Path(__file__).resolve().parent
TOKEN_NAMES = "ground|ink|muted|rule|act|ok|caution|fault"
TOKEN = re.compile(r"--(" + TOKEN_NAMES + r"):\s*(#[0-9A-Fa-f]{6})")
STACK_NAMES = "mark|read"
STACK = re.compile(r"--(" + STACK_NAMES + r"):\s*([^;]+);")


def font_stacks():
    css = (KIT / "style.css").read_text(encoding="utf-8")
    found = dict(STACK.findall(css))
    missing = [name for name in STACK_NAMES.split("|") if name not in found]
    if missing:
        raise SystemExit(
            f"tokens: {KIT / 'style.css'} has no --{', --'.join(missing)} font stack"
        )
    return {name: stack.strip().replace('"', "'") for name, stack in found.items()}


def tokens():
    css = (KIT / "style.css").read_text(encoding="utf-8")
    found = dict(TOKEN.findall(css))
    missing = [name for name in TOKEN_NAMES.split("|") if name not in found]
    if missing:
        raise SystemExit(
            f"tokens: {KIT / 'style.css'} has no --{', --'.join(missing)} color token"
        )
    return found
