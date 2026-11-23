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
import sys
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


def stylesheet_matches(src):
    approved = (src / "style.css").read_text(encoding="utf-8").strip()
    kit = (KIT / "style.css").read_text(encoding="utf-8")
    if approved in kit:
        print("SAME       the approved stylesheet sits inside the kit's, word for word")
        return True
    print("DIFFERENT  Part 1 of style.css is no longer the approved stylesheet: restore it, and put the change in Part 2")
    return False


def page_heights(shots):
    return {width: max(y + h for sw, y, h, _ in shots if sw == width) for width, *_ in check.WIDTHS}


def report_pixel_differences(differences, total, keep):
    locations = ", ".join(f"{approved[0]} wide at {approved[1]}" for approved, _ in differences[:8])
    print(f"DIFFERENT  {len(differences)} of {total} slices: {locations}")
    if not keep:
        print("           run it again with --keep DIR to save each pair and read them side by side")
        return
    keep.mkdir(parents=True, exist_ok=True)
    for approved, kit in differences:
        for tag, (width, y, _height, png) in (("approved", approved), ("kit", kit)):
            (keep / f"{width}-{y:05d}-{tag}.png").write_bytes(png)
    print(f"           each pair is in {keep}: read them side by side")


def slices_match(approved, kit, keep):
    if [shot[:3] for shot in approved] != [shot[:3] for shot in kit]:
        print(f"DIFFERENT  the page changed height: approved {page_heights(approved)}, kit {page_heights(kit)} (width: height)")
        return False
    differences = [(old, new) for old, new in zip(approved, kit) if old[3] != new[3]]
    if differences:
        report_pixel_differences(differences, len(approved), keep)
        return False
    widths = " and ".join(str(width) for width, *_ in check.WIDTHS)
    print(f"SAME       {len(approved)} of {len(approved)} slices, at {widths} wide")
    return True


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
    source_matches = stylesheet_matches(src)

    exe = check.find_browser()
    if not exe:
        print("regress: no browser found, so nothing was drawn. Set PATTERN_BROWSER to a Chromium or Chrome binary.")
        raise SystemExit(2)
    with check.browser_session(exe, "pattern-regress-") as (browser, work):
        shots = {}
        for tag, sheet in (("approved", own_sheet(src)), ("kit", "{{kit:style.css}}")):
            (work / f"{tag}.html").write_text(page(src, sheet), encoding="utf-8")
            shots[tag] = slices(browser, (work / f"{tag}.html").as_uri(), work, tag)

    render_matches = slices_match(shots["approved"], shots["kit"], keep)
    passed = source_matches and render_matches
    print("PASS" if passed else "FAIL")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
