import re
from pathlib import Path

KIT = Path(__file__).resolve().parent
TOKEN_NAMES = "ground|ink|muted|rule|act|ok|caution|fault"
TOKEN = re.compile(r"--(" + TOKEN_NAMES + r"):\s*(#[0-9A-Fa-f]{6})")


def tokens():
    css = (KIT / "style.css").read_text(encoding="utf-8")
    return dict(TOKEN.findall(css))
