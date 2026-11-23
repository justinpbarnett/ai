#!/usr/bin/env python3
"""Check a built page against the look, in a real browser at desktop and phone width.

    check.py PAGE                 run the checks
    check.py PAGE --shots DIR     run the checks, then photograph the whole page in slices at both widths

PAGE is a built file, or the http address of a page that a running app serves.
Each width is read once the page has drawn what it fetches after it loads.

FAIL is a broken rule: fix it. WARN is probably wrong: fix it, or know why it stays.
NOTE is for your judgement. The slices are the other half of the check, because a page
can pass every rule and still look wrong: read each one.

The browser is $PATTERN_BROWSER, or the first of chromium and google-chrome on the PATH.
It is driven over its debugging pipe, so nothing needs installing beyond the browser.
"""
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
from browser import BROWSERS, SETTLE_S, WIDTHS, browser_session, cuts, find_browser, run_reporting  # noqa: E402
from build import PLACE, DocumentShell  # noqa: E402
from tokens import tokens as page_tokens  # noqa: E402

KIT = Path(__file__).resolve().parent
ARTIFACT_BYTE_LIMIT = 16 * 1024 * 1024


def tokens():
    found = {"#000000": "black"}
    for name, value in page_tokens().items():
        found.setdefault(value.upper(), name)
    return found


def script():
    js = (KIT / "check.js").read_text(encoding="utf-8")
    coverage = (KIT / "fonts" / "coverage.json").read_text(encoding="utf-8")
    return js.replace("/*TOKENS*/{}", json.dumps(tokens())).replace("/*COVERAGE*/{}", coverage)


def address(page, text, work):
    if DocumentShell(text).has_skeleton:
        return page.as_uri()
    whole = work / "page.html"
    whole.write_text('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                     '<meta name="viewport" content="width=device-width, initial-scale=1">'
                     f'<base href="{page.parent.as_uri()}/"></head><body>{text}</body></html>', encoding="utf-8")
    return whole.as_uri()


def report(results):
    worst = 0
    for level in ("fail", "warn", "note"):
        kinds = {}
        for (width, *_), result in zip(WIDTHS, results):
            for kind, msg in result[level]:
                seen_at = kinds.setdefault(kind, {}).setdefault(msg, [])
                if width not in seen_at:
                    seen_at.append(width)
        for kind, msgs in kinds.items():
            worst = max(worst, level == "fail")
            print(f"{level.upper():5} {kind} ({len(msgs)})")
            for msg, widths in list(msgs.items())[:6]:
                print(f"        {msg}" + ("" if len(widths) == len(results) else f"  [{widths[0]} only]"))
            if len(msgs) > 6:
                print(f"        and {len(msgs) - 6} more")
    return int(worst)


def source(text, size):
    found = {"fail": [], "warn": [], "note": []}
    for slot in sorted({m.group(0) for m in PLACE.finditer(text)})[:6]:
        found["fail"].append(["slot", f"{slot} was never filled: hand out the built page, never the template"])
    if size > ARTIFACT_BYTE_LIMIT:
        found["warn"].append(["size", "over 16 MB, which is more than an Artifact takes: shrink the images"])
    if re.search(r"<html\b", text, flags=re.I) and not re.search(r"<meta[^>]+name=[\"']viewport", text, flags=re.I):
        found["warn"].append(["viewport", "no viewport meta, so a phone draws the page at desktop width"])
    return found


def check_viewport(browser, url, viewport, js, file_findings):
    width = viewport.width
    settled = browser.open(url, width, viewport.height, viewport.phone)
    if file_findings is None:
        markup = browser.ask("fetch(location.href).then((got) => got.text()).then(JSON.stringify)")
        source_findings = source(markup, 0)
    else:
        source_findings = file_findings
    result = browser.ask(js.replace("/*VIEWPORT_WIDTH*/null", str(width), 1))
    for level, findings in source_findings.items():
        result[level] = findings + result[level]
    if not settled:
        result["note"].append(["settle", f"the page still changed {SETTLE_S} s after it loaded, so it was read mid-change"])
    info = result["info"]
    actual = f"{info['width']} wide · {info['height']} tall"
    print(actual if info["width"] == width else f"{actual} (asked for {width})")
    return result


def save_slices(browser, viewport, page_height, out, stem):
    names = []
    for number, (top, height) in enumerate(cuts(page_height, viewport.tall), 1):
        path = out / f"{stem}-{viewport.width}-{number:02d}.png"
        browser.shoot(path, top, viewport.width, height)
        names.append(path)
    return names


def report_run(results, names):
    worst = report(results)
    print("FAIL" if worst else "PASS")
    if names:
        print(f"{len(names)} slices to read:")
        for name in names:
            print(f"  {name}")
    return worst


def without_browser(served, file_findings):
    if served:
        print("check: no browser found, so nothing was checked. Set PATTERN_BROWSER to a Chromium or Chrome binary.")
        raise SystemExit(2)
    worst = report([file_findings])
    print("NOTE  no browser found, so only the file was read. Set PATTERN_BROWSER to a Chromium or Chrome binary.")
    raise SystemExit(worst or 2)


def main(argv):
    out = None
    if len(argv) == 3 and argv[1] == "--shots":
        out = Path(argv[2])
    elif len(argv) != 1 or argv[0].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(2)
    file_findings = None
    served = re.match(r"https?://", argv[0], flags=re.I)
    if served:
        url = argv[0]
        stem = re.sub(r"[^A-Za-z0-9]+", "-", url[served.end():]).strip("-") or "page"
        print(url)
    else:
        page = Path(argv[0]).resolve()
        if not page.is_file():
            raise SystemExit(f"check: no page at {page}")
        data = page.read_bytes()
        try:
            text, stem = data.decode("utf-8"), page.stem
        except UnicodeDecodeError:
            raise SystemExit(f"check: {page} is not valid UTF-8")
        file_findings = source(text, len(data))
        print(f"{page} · {len(data) / 1e6:.2f} MB")

    exe = find_browser(BROWSERS)
    if not exe:
        without_browser(served, file_findings)

    with browser_session(exe, "pattern-check-") as (browser, work):
        js, results, names = script(), [], []
        if not served:
            url = address(page, text, work)
        if out:
            out.mkdir(parents=True, exist_ok=True)
        for viewport in WIDTHS:
            result = check_viewport(browser, url, viewport, js, file_findings)
            results.append(result)
            if out:
                names.extend(save_slices(browser, viewport, result["info"]["height"], out, stem))
        worst = report_run(results, names)
    raise SystemExit(worst)


if __name__ == "__main__":
    run_reporting(main, sys.argv[1:], "check")
