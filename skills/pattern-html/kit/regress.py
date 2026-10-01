#!/usr/bin/env python3
"""Prove the kit still draws the approved page exactly as it was approved.

    regress.py                  against ~/dev/design/refs/rugged/src
    regress.py SRC              the same, with the approved source somewhere else
    regress.py --keep DIR       also save each pair of slices that differ, to read side by side

SRC holds the page Justin approved: board.tmpl.html, the style.css he saw it in, and its fonts.
Two things have to hold, and the second is the one that counts:

    1. that style.css sits inside the kit's, word for word
    2. the page drawn with the kit's stylesheet and fonts matches the page drawn with its own,
       in every slice at desktop and phone width, byte for byte

Run it after any change to style.css or to fonts/. It ends 0 on a pass, 1 on a difference,
and 2 when it could not run (no approved page on this machine, or no browser).
"""
import base64
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True      # importing the kit must not leave a __pycache__ in it
KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))
import build    # noqa: E402
import check    # noqa: E402

SRC = Path.home() / "dev" / "design" / "refs" / "rugged" / "src"
READY = "document.fonts.ready.then(function () { return JSON.stringify(document.documentElement.scrollHeight); })"


def own_sheet(src):
    """The approved stylesheet with the fonts it was approved in (the kit's cover more characters)."""
    def font(m):
        path = src / "fonts" / m.group(1)
        if not path.is_file():
            raise SystemExit(f"regress: the approved stylesheet names a font that is not at {path}")
        return base64.b64encode(path.read_bytes()).decode("ascii")
    return re.sub(r"\{\{font:([^{}\s]+)\}\}", font, (src / "style.css").read_text(encoding="utf-8"))


def page(src, sheet):
    """The approved template as one file, with sheet in place of its stylesheet."""
    text = (src / "board.tmpl.html").read_text(encoding="utf-8")
    text, n = re.subn(r"\{\{css:style\.css\}\}", lambda m: sheet, text)
    if n != 1:
        raise SystemExit(f"regress: {src / 'board.tmpl.html'} names its stylesheet {n} times, not once")
    text = re.sub(r"\{\{img:([^{}\s/]+)\}\}", r"{{img:fig/\1}}", text)   # that page kept its images in fig/
    return build.expand(text, src, "regress")


def slices(browser, url, work, tag):
    """Every slice of the page at both widths: [(width, top, height, PNG bytes)]."""
    out = []
    for width, height, tall, phone in check.WIDTHS:
        browser.open(url, width, height, phone)
        for y, h in check.cuts(browser.ask(READY), tall):
            shot = work / f"{tag}.png"
            browser.shoot(shot, y, width, h)
            out.append((width, y, h, shot.read_bytes()))
    return out


def main(argv):
    keep = None
    if len(argv) >= 2 and argv[-2] == "--keep":
        keep, argv = Path(argv[-1]), argv[:-2]
    if len(argv) > 1 or (argv and argv[0].startswith("--")):
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(2)
    src = Path(argv[0]).resolve() if argv else SRC
    if not (src / "board.tmpl.html").is_file():
        print(f"regress: no approved page at {src}, so the proof cannot run on this machine")
        raise SystemExit(2)
    bad = 0

    if (src / "style.css").read_text(encoding="utf-8").strip() in (KIT / "style.css").read_text(encoding="utf-8"):
        print("SAME       the approved stylesheet sits inside the kit's, word for word")
    else:
        bad += 1
        print("DIFFERENT  Part 1 of style.css is no longer the approved stylesheet: restore it, and put the change in Part 2")

    exe = check.find_browser()
    if not exe:
        print("regress: no browser found, so nothing was drawn. Set PATTERN_BROWSER to a Chromium or Chrome binary.")
        raise SystemExit(2)
    work = Path(tempfile.mkdtemp(prefix="pattern-regress-"))
    browser = check.Browser(exe, work)
    try:
        shots = {}
        for tag, sheet in (("approved", own_sheet(src)), ("kit", "{{kit:style.css}}")):
            (work / f"{tag}.html").write_text(page(src, sheet), encoding="utf-8")
            shots[tag] = slices(browser, (work / f"{tag}.html").as_uri(), work, tag)
    finally:
        browser.stop()
        shutil.rmtree(work, ignore_errors=True)

    was, now = shots["approved"], shots["kit"]
    if [s[:3] for s in was] != [s[:3] for s in now]:
        bad += 1
        tall = {tag: {w[0]: max(y + h for sw, y, h, _ in shots[tag] if sw == w[0]) for w in check.WIDTHS} for tag in shots}
        print(f"DIFFERENT  the page changed height: approved {tall['approved']}, kit {tall['kit']} (width: height)")
    else:
        off = [(a, b) for a, b in zip(was, now) if a[3] != b[3]]
        if off:
            bad += 1
            print(f"DIFFERENT  {len(off)} of {len(was)} slices: " + ", ".join(f"{a[0]} wide at {a[1]}" for a, _ in off[:8]))
            if keep:
                keep.mkdir(parents=True, exist_ok=True)
                for a, b in off:
                    for tag, s in (("approved", a), ("kit", b)):
                        (keep / f"{s[0]}-{s[1]:05d}-{tag}.png").write_bytes(s[3])
                print(f"           each pair is in {keep}: read them side by side")
            else:
                print("           run it again with --keep DIR to save each pair and read them side by side")
        else:
            print(f"SAME       {len(was)} of {len(was)} slices, at {' and '.join(str(w[0]) for w in check.WIDTHS)} wide")
    print("FAIL" if bad else "PASS")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
