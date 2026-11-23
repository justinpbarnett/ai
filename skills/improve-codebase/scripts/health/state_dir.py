import os
import stat
from pathlib import Path

from .inventory import STATE_DIR, git
from .validation import require


def check_ignore(root, relative, *git_options):
    return not git(
        root,
        *git_options,
        "check-ignore",
        "--quiet",
        "--no-index",
        "--",
        relative + "/",
        allowed=(0, 1),
    ).returncode


def require_exclusion_beats_negations(root, relative, fallback_excludes):
    require(
        check_ignore(root, relative, "-c", f"core.excludesFile={fallback_excludes}"),
        "an existing Git ignore negation overrides the proposed local state exclusion",
    )


def add_local_exclusion(root, relative):
    raw = git(root, "rev-parse", "--git-path", "info/exclude").stdout.rstrip(b"\n")
    path = root / os.fsdecode(raw)
    require(path.resolve() == path, "Git local exclude is redirected by a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    with lock.open("xb") as stream:
        try:
            old = path.read_bytes() if path.exists() else b""
            rule = f"/{relative}/".encode()
            require(
                rule not in old.splitlines(),
                "local Git exclusion is overridden; fix the ignore rules before writing state",
            )
            stream.write(
                old + (b"\n" if old and not old.endswith(b"\n") else b"") + rule + b"\n"
            )
            if path.exists():
                os.fchmod(stream.fileno(), stat.S_IMODE(path.stat().st_mode))
            stream.flush()
            os.fsync(stream.fileno())
            require_exclusion_beats_negations(root, relative, lock)
            os.replace(lock, path)
        finally:
            lock.unlink(missing_ok=True)
    require(
        check_ignore(root, relative), "cannot protect state with Git local excludes"
    )


def safe_state_dir(root, is_git, requested, write):
    default = root / STATE_DIR
    path = Path(os.path.abspath(Path(requested).expanduser())) if requested else default
    require(
        path.resolve() == path, "state directory must not be a symlink or traverse one"
    )
    require(
        path not in (root, *root.parents)
        and not (path == root / ".git" or path.is_relative_to(root / ".git")),
        "state directory cannot cover the worktree or Git metadata",
    )
    if is_git and path.is_relative_to(root):
        relative = path.relative_to(root).as_posix()
        tracked = git(
            root, "--literal-pathspecs", "ls-files", "-z", "--", relative
        ).stdout
        require(not tracked, f"state path is tracked: {relative!r}")
        if write and not check_ignore(root, relative):
            require(
                path == default,
                "custom state inside a worktree must already be ignored",
            )
            add_local_exclusion(root, relative)
    if path.exists():
        require(path.is_dir(), "state location is not a directory")
    return path
