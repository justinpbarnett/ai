import os
import sys
from pathlib import Path

ENV_FILE = Path.home() / ".config" / "passion" / "rock.env"


def load() -> None:
    if not ENV_FILE.is_file():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


HINTS = {
    "ROCK_BASE_URL": "Your Rock instance URL. Must be https.",
    "ROCK_USERNAME": "Your Rock login.",
    "ROCK_PASSWORD": "Your Rock password.",
}


def require(*names: str) -> list:
    load()
    values = [os.environ.get(n, "").strip() for n in names]
    missing = [n for n, v in zip(names, values) if not v]
    if missing:
        lines = [
            f"ERROR: missing {', '.join(missing)}.",
            f"Set them in {ENV_FILE} (one KEY=value per line) or export them in your environment.",
        ]
        lines += [f"  {n} – {HINTS[n]}" for n in missing if n in HINTS]
        print("\n".join(lines), file=sys.stderr)
        sys.exit(1)
    return values
