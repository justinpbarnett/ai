import hashlib
import os
import stat
import subprocess
from collections import Counter, defaultdict


def subcommand(args):
    remaining = iter(args)
    for argument in remaining:
        if argument == "-c":
            next(remaining, None)
        elif not argument.startswith("-"):
            return argument
    return args[0]


def git(root, *args, allowed=(0,), env=None, stdin=None):
    environment = dict(os.environ if env is None else env)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_PREFIX",
    ):
        environment.pop(key, None)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        input=stdin,
        env=environment,
        timeout=45,
    )
    if result.returncode not in allowed:
        raise OSError(
            f"git {subcommand(args)} failed: {os.fsdecode(result.stderr).strip()}"
        )
    return result


def hotspots(root, is_git, files):
    if not is_git:
        return {"available": False, "reason": "non-Git project"}
    try:
        result = git(
            root,
            "log",
            "-n",
            "100",
            "--format=",
            "--name-only",
            "-z",
            "--no-renames",
            "--diff-filter=ACMRT",
            "HEAD",
            allowed=(0, 128),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "reason": "Git history unavailable"}
    if result.returncode:
        return {"available": False, "reason": "no readable HEAD"}
    counts = Counter(
        os.fsdecode(raw)
        for raw in result.stdout.split(b"\0")
        if os.fsdecode(raw) in files
    )
    return {"available": True, "recent_touches": dict(counts.most_common(100))}


HISTORY_COMMITS = 500
HISTORY_MAX_FILES = 30
COMMIT_MARK = b"\x01"


def status_commits(raw):
    tokens, commits, index = raw.split(b"\0"), [], 0
    while index < len(tokens):
        token = tokens[index].lstrip(b"\n")
        index += 1
        if token.startswith(COMMIT_MARK):
            commits.append([])
        elif token:
            width = 2 if token[:1] in b"RC" else 1
            paths = [os.fsdecode(t) for t in tokens[index : index + width]]
            commits[-1].append((os.fsdecode(token[:1]), *paths))
            index += width
    return commits


REGULAR_MODES = {b"100644", b"100755"}
DIGEST_BY_HEX_LENGTH = {40: "sha1", 64: "sha256"}


def deleted_blobs(root):
    result = git(
        root,
        "diff",
        "--raw",
        "--no-abbrev",
        "--no-renames",
        "--diff-filter=D",
        "-z",
        "HEAD",
        allowed=(0, 128),
    )
    if result.returncode:
        return {}
    tokens = result.stdout.split(b"\0")
    deleted = {}
    for meta, path in zip(tokens[0::2], tokens[1::2], strict=False):
        fields = meta.split()
        if fields[0].lstrip(b":") in REGULAR_MODES:
            deleted[os.fsdecode(path)] = fields[2].decode()
    return deleted


def blob_sizes(root, blobs):
    listed = git(
        root,
        "cat-file",
        "--batch-check=%(objectname) %(objectsize)",
        stdin=os.fsencode("\n".join(sorted(blobs)) + "\n"),
    ).stdout.split(b"\n")
    sizes = {}
    for line in listed:
        fields = line.split()
        if len(fields) == 2 and fields[1].isdigit():
            sizes[fields[0].decode()] = int(fields[1])
    return sizes


def blob_id(content, algorithm):
    digest = hashlib.new(algorithm, b"blob %d\0" % len(content))
    digest.update(content)
    return digest.hexdigest()


def untracked_blobs(root, wanted_sizes, algorithm):
    listed = git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    blobs = {}
    for raw in listed.split(b"\0"):
        if not raw:
            continue
        name = os.fsdecode(raw)
        try:
            status = os.lstat(os.path.join(root, name))
            if not stat.S_ISREG(status.st_mode) or status.st_size not in wanted_sizes:
                continue
            with open(os.path.join(root, name), "rb") as handle:
                blobs[name] = blob_id(handle.read(), algorithm)
        except OSError:
            continue
    return blobs


def unstaged_renames(root, staged):
    deleted = {
        path: blob for path, blob in deleted_blobs(root).items() if path not in staged
    }
    if not deleted:
        return {}
    sizes = blob_sizes(root, set(deleted.values()))
    deleted = {path: blob for path, blob in deleted.items() if blob in sizes}
    if not deleted:
        return {}
    algorithm = DIGEST_BY_HEX_LENGTH.get(len(next(iter(deleted.values()))), "sha1")
    untracked = untracked_blobs(root, set(sizes.values()), algorithm)
    old_by_blob, new_by_blob = defaultdict(list), defaultdict(list)
    for path, blob in deleted.items():
        old_by_blob[blob].append(path)
    for path, blob in untracked.items():
        new_by_blob[blob].append(path)
    return {
        old[0]: new_by_blob[blob][0]
        for blob, old in old_by_blob.items()
        if len(old) == 1 and len(new_by_blob.get(blob, ())) == 1
    }


def working_tree_renames(root):
    result = git(root, "diff", "-M", "--name-status", "-z", "HEAD", allowed=(0, 128))
    if result.returncode:
        return {}
    entries = status_commits(COMMIT_MARK + b"\0" + result.stdout)[0]
    staged = {entry[1]: entry[2] for entry in entries if entry[0] == "R"}
    return {**unstaged_renames(root, staged), **staged}


def commit_history(root, is_git):
    if not is_git:
        return {"available": False, "reason": "non-Git project"}
    try:
        result = git(
            root,
            "log",
            "-n",
            str(HISTORY_COMMITS),
            "--format=%x01%H",
            "--name-status",
            "-z",
            "-M",
            "--diff-filter=ACMRT",
            "HEAD",
            allowed=(0, 128),
        )
        forward = working_tree_renames(root) if not result.returncode else {}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "reason": "Git history unavailable"}
    if result.returncode:
        return {"available": False, "reason": "no readable HEAD"}
    commits, remapped = [], set()
    for entries in status_commits(result.stdout):
        if len(entries) <= HISTORY_MAX_FILES:
            files = []
            for entry in entries:
                path = entry[-1]
                files.append(forward.get(path, path))
                if forward.get(path, path) != path:
                    remapped.add(path)
            commits.append(files)
        for entry in entries:
            if entry[0] == "R":
                forward[entry[1]] = forward.get(entry[2], entry[2])
    return {
        "available": True,
        "commits": commits,
        "window_commits": HISTORY_COMMITS,
        "max_commit_files": HISTORY_MAX_FILES,
        "mapped_paths": len(remapped),
    }
