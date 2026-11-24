from collections import Counter, defaultdict
from itertools import combinations
from pathlib import PurePosixPath

from .dependency_graph import components
from .paths import directory, is_test_path, within
from .rules import (
    CHANGE_COUPLING,
    FOLDER_CYCLE,
    GENERIC_FOLDER,
    SINGLE_IMPORTER,
    WIDE_FOLDER,
)

GENERIC_FOLDERS = {
    "utils",
    "util",
    "utilities",
    "helpers",
    "helper",
    "common",
    "misc",
    "shared",
    "stuff",
    "general",
}
SAMPLE_LIMIT = 20
EDGE_LIMIT = 100


def files_by_directory(files):
    grouped = defaultdict(list)
    for path in sorted(files):
        grouped[directory(path)].append(path)
    return grouped


def production_edges(edges):
    return [
        (source, target)
        for source, target, _ in edges
        if not is_test_path(source) and not is_test_path(target)
    ]


def outside_importer_edges(edges, folder):
    return [
        (source, target)
        for source, target in edges
        if within(target, folder) and not within(source, folder)
    ]


def generic_folders(files, edges):
    members = defaultdict(list)
    for path in sorted(files):
        parent = PurePosixPath(path).parent
        for ancestor in (parent, *parent.parents):
            if ancestor.name.lower() in GENERIC_FOLDERS:
                members[ancestor.as_posix()].append(path)
    for folder, paths in sorted(members.items()):
        importers = sorted(
            {directory(source) for source, _ in outside_importer_edges(edges, folder)}
        )
        yield (
            GENERIC_FOLDER,
            paths[0],
            f"directory:{folder}",
            {
                "directory": folder,
                "files": len(paths),
                "importer_directories": importers,
                "importer_count": len(importers),
                "samples": paths[:SAMPLE_LIMIT],
            },
            [],
        )


def single_importers(by_directory, edges):
    for folder, paths in sorted(by_directory.items()):
        if folder == "." or len(paths) < 2:
            continue
        shown = outside_importer_edges(edges, folder)
        if not shown:
            continue
        importers = {directory(source) for source, _ in shown}
        importer = next(iter(importers))
        if len(importers) != 1 or within(folder, importer):
            continue
        yield (
            SINGLE_IMPORTER,
            paths[0],
            f"directory:{folder}",
            {
                "directory": folder,
                "importer_directory": importer,
                "files": len(paths),
                "edge_count": len(shown),
                "edges": [list(edge) for edge in sorted(shown)[:EDGE_LIMIT]],
            },
            [{"path": shown[0][0]}],
        )


def folder_cycles(by_directory, edges):
    directory_edges = {
        (directory(source), directory(target), "directory")
        for source, target in edges
        if directory(source) != directory(target)
    }
    for members in components(sorted(directory_edges)):
        owned = [d for d in members if by_directory.get(d)]
        if not owned:
            continue
        member_set = set(members)
        file_edges = sorted(
            (source, target)
            for source, target in edges
            if {directory(source), directory(target)} <= member_set
            and directory(source) != directory(target)
        )
        endpoints = sorted({file for edge in file_edges for file in edge})
        selected = {path for d in owned for path in by_directory[d]}
        path = min([file for file in endpoints if file in selected] or selected)
        yield (
            FOLDER_CYCLE,
            path,
            "directories",
            {
                "members": members,
                "edge_count": len(file_edges),
                "edges": [list(edge) for edge in file_edges[:EDGE_LIMIT]],
            },
            [
                {"path": next(file for file in endpoints if directory(file) == d)}
                for d in members
                if d != directory(path)
            ],
        )


def wide_folders(by_directory, threshold):
    for folder, paths in sorted(by_directory.items()):
        if len(paths) > threshold:
            yield (
                WIDE_FOLDER,
                paths[0],
                f"directory:{folder}",
                {"directory": folder, "files": len(paths), "threshold": threshold},
                [],
            )


def directory_findings(files, edges, thresholds):
    by_directory = files_by_directory(files)
    graph = production_edges(edges)
    yield from generic_folders(files, graph)
    yield from single_importers(by_directory, graph)
    yield from folder_cycles(by_directory, graph)
    yield from wide_folders(by_directory, thresholds["folder_files"])


def commit_sets(history, files):
    if not history["available"]:
        return []
    return [
        sorted(touched)
        for commit in history["commits"]
        if (touched := {path for path in commit if path in files})
    ]


def change_coupling(sets, thresholds):
    revisions, shared = Counter(), Counter()
    for touched in sets:
        revisions.update(touched)
        shared.update(
            pair
            for pair in combinations(touched, 2)
            if directory(pair[0]) != directory(pair[1])
        )
    for (first, second), count in sorted(shared.items()):
        mean = (revisions[first] + revisions[second]) / 2
        degree = round(count / mean * 100, 1)
        if (
            count >= thresholds["coupling_revisions"]
            and degree >= thresholds["coupling_degree"]
        ):
            yield (
                CHANGE_COUPLING,
                first,
                f"with:{second}",
                {
                    "shared": count,
                    "revs_a": revisions[first],
                    "revs_b": revisions[second],
                    "degree": degree,
                },
                [{"path": second}],
            )


def locality(history, sets):
    if not history["available"]:
        return {"available": False, "reason": history["reason"]}
    spread = [len({directory(path) for path in touched}) for touched in sets]
    return {
        "available": True,
        "commits_considered": len(spread),
        "mean_directories_per_commit": round(sum(spread) / len(spread), 3)
        if spread
        else None,
        "single_directory_share": round(spread.count(1) / len(spread), 3)
        if spread
        else None,
        "window_commits": history["window_commits"],
        "max_commit_files": history["max_commit_files"],
        "mapped_paths": history["mapped_paths"],
    }
