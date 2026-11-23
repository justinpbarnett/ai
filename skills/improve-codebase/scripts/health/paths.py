import re
from pathlib import PurePosixPath

TEST_SEGMENTS = {"test", "tests", "__tests__", "spec", "specs"}
TEST_FILE = re.compile(
    r"test_.*\.py|.*_test\.py|conftest\.py|.*\.test\..*|.*\.spec\..*|.*_test\.go|.*Tests?\.cs"
)


def within(path, prefix):
    return prefix == "." or path == prefix or path.startswith(prefix + "/")


def in_paths(path, paths):
    return any(within(path, prefix) for prefix in paths)


def is_test_path(path):
    parts = PurePosixPath(path).parts
    folders, name = parts[:-1], parts[-1]
    return (
        any(p.lower() in TEST_SEGMENTS or p.endswith(".Tests") for p in folders)
        or PurePosixPath(name).stem.lower() in TEST_SEGMENTS
        or bool(TEST_FILE.fullmatch(name))
    )
