#!/usr/bin/env python3
"""Build one self contained HTML file from a template.

    build.py TEMPLATE OUT               a whole page
    build.py --artifact TEMPLATE OUT    the same page without its document skeleton, for the Artifact tool
    build.py --css OUT                  the stylesheet alone, fonts inside, for an app that serves its own CSS
    build.py --draw DRAWING.py OUT      one drawing on a bare page, to look at while drawing it

Placeholders are replaced in place. PATH is relative to the file that holds the placeholder.

    {{kit:style.css}}    a text file from this kit, its own placeholders filled
    {{css:PATH}}         a stylesheet of your own, its own placeholders filled
    {{js:PATH}}          a script
    {{img:PATH}}         an image, as a data URI for src="..."
    {{svg:PATH}}         an SVG file, inline
    {{draw:PATH}}        the SVG a drawing script prints; {{draw:PATH#ARG}} runs it with ARG
    {{font:NAME}}        a font from kit/fonts, as base64

Anything else in double braces is left alone, so a template can keep slots for another tool to fill.
To show a placeholder as text on a page, write its first brace as &#123;.
"""
import base64
import os
import re
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
KINDS = "kit|css|js|img|svg|draw|font"
PLACE = re.compile(r"\{\{(" + KINDS + r"):([^{}\s]+)\}\}")
LOOSE = re.compile(r"\{\{\s*(?:" + KINDS + r")\s*:[^{}]*\}\}")
MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".avif": "image/avif",
}
BARE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Drawing</title>
<style>{{kit:style.css}}</style>
</head>
<body>
<div class="wrap">
<div class="mock" style="margin-top:24px"><!--drawing--></div>
</div>
</body>
</html>
"""


def fail(msg):
    raise SystemExit(f"build: {msg}")


def read(path, src, what):
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"{src}: {what}: no file at {path}")


def b64(path, src, what):
    try:
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except FileNotFoundError:
        fail(f"{src}: {what}: no file at {path}")


def draw(path, arg, src="--draw"):
    """Run a drawing script and return the SVG it prints."""
    if not path.is_file():
        fail(f"{src}: no drawing script at {path}")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(KIT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # importing draw.py must not leave a __pycache__ in the kit
    run = subprocess.run([sys.executable, str(path)] + ([arg] if arg else []),
                         cwd=str(path.parent), env=env, capture_output=True, text=True)
    if run.returncode != 0:
        fail(f"{path} stopped with an error:\n{run.stderr.strip()}")
    svg = run.stdout.strip()
    if not svg.startswith("<svg"):
        fail(f"{path} must print one <svg> element and nothing else; it printed: {svg[:80]!r}")
    return svg


def expand(text, base, src):
    """Fill every placeholder in text. base is the folder its paths start from."""
    for m in LOOSE.finditer(text):
        if not PLACE.fullmatch(m.group(0)):
            fail(f"{src}: malformed placeholder {m.group(0)!r} (no spaces, one colon, a path)")

    def sub(m):
        kind, name, what = m.group(1), m.group(2), m.group(0)
        if kind == "font":
            return b64(KIT / "fonts" / name, src, what)
        if kind == "kit":
            return expand(read(KIT / name, src, what), KIT, f"kit/{name}")
        if kind == "draw":
            script, _, arg = name.partition("#")
            return draw(base / script, arg, src)
        path = base / name
        if kind == "css":
            return expand(read(path, src, what), path.parent, str(path))
        if kind == "js":
            return re.sub(r"</(script)", r"<\\/\1", read(path, src, what), flags=re.I)
        if kind == "svg":
            svg = re.sub(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>", "", read(path, src, what), flags=re.I)
            return svg.strip()
        mime = MIME.get(path.suffix.lower())
        if not mime:
            fail(f"{src}: {what}: {path.suffix or 'no extension'} is not an image type this kit knows")
        return f"data:{mime};base64,{b64(path, src, what)}"

    return PLACE.sub(sub, text)


def strip_skeleton(html):
    """Drop what the Artifact tool adds itself: doctype, html, head, body, charset, viewport."""
    body = re.search(r"<body\b([^>]*)>", html, flags=re.I)
    if body and body.group(1).strip():
        print("build: warning: the body tag's attributes are dropped in an Artifact; move them to .wrap", file=sys.stderr)
    html = re.sub(r"<!doctype[^>]*>\s*", "", html, flags=re.I)
    html = re.sub(r"</?(?:html|head|body)\b[^>]*>\s*", "", html, flags=re.I)
    html = re.sub(r"<meta\s+(?:charset|name=[\"']viewport[\"'])[^>]*>\s*", "", html, flags=re.I)
    head = html.encode("utf-8")[:8192].decode("utf-8", "ignore")
    if not re.search(r"<title>[^<]+</title>", head, flags=re.I):
        print("build: warning: no <title> in the first 8 KB; put it above <style>", file=sys.stderr)
    return html.lstrip()


def size(n):
    return f"{n / 1e6:.2f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


def write(out, html):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = html.encode("utf-8")
    out.write_bytes(data)
    print(f"{out}: {size(len(data))}")


def main(argv):
    if len(argv) == 2 and argv[0] == "--css":
        return write(argv[1], expand("{{kit:style.css}}", KIT, "kit"))
    if len(argv) == 3 and argv[0] == "--draw":
        script, _, arg = argv[1].partition("#")
        svg = draw(Path(script).resolve(), arg)
        return write(argv[2], expand(BARE, KIT, "kit").replace("<!--drawing-->", svg))
    artifact = len(argv) == 3 and argv[0] == "--artifact"
    if artifact:
        argv = argv[1:]
    if len(argv) != 2 or argv[0].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(2)
    tmpl = Path(argv[0]).resolve()
    html = expand(read(tmpl, "build", "template"), tmpl.parent, str(tmpl))
    if artifact:
        html = strip_skeleton(html)
    write(argv[1], html)


if __name__ == "__main__":
    main(sys.argv[1:])
