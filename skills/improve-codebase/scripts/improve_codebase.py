#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

from health.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
