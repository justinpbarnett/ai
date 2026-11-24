import os
from pathlib import Path

HOME = Path(os.environ["ROCK_HOME"])

CATALOG = HOME / "catalog.json"
LOG = HOME / "rock.log"
SCREENSHOTS = HOME / "screenshots"
SNAPSHOTS = HOME / "snapshots"


def ensure() -> Path:
    HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
    return HOME
