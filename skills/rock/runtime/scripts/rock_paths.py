import os
from pathlib import Path

HOME = Path(os.environ.get("ROCK_HOME") or Path.home() / ".local" / "share" / "passion-rock")

CATALOG = HOME / "catalog.json"
LOG = HOME / "rock.log"
SCREENSHOTS = HOME / "screenshots"
SNAPSHOTS = HOME / "snapshots"


def ensure() -> Path:
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    return HOME
