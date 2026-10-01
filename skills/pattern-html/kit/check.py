#!/usr/bin/env python3
"""Check a built page against the look, in a real browser at desktop and phone width.

    check.py PAGE                 run the checks
    check.py PAGE --shots DIR     run the checks, then photograph the whole page in slices at both widths

PAGE is a built file, or the http address of a page that a running app serves.

FAIL is a broken rule: fix it. WARN is probably wrong: fix it, or know why it stays.
NOTE is for your judgement. The slices are the other half of the check, because a page
can pass every rule and still look wrong: read each one.

The browser is $PATTERN_BROWSER, or the first of chromium and google-chrome on the PATH.
It is driven over its debugging pipe, so nothing needs installing beyond the browser.
"""
import base64
import fcntl
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

KIT = Path(__file__).resolve().parent
PLACE = re.compile(r"\{\{(?:kit|css|js|img|svg|draw|font):[^{}\s]+\}\}")
WIDTHS = ((1280, 900, 1500, False), (390, 844, 2200, True))     # width, height, slice height, phone
BROWSERS = ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium")
LIMIT = 16 * 1024 * 1024                                        # the largest page the Artifact tool takes
PATIENCE = 120                                                  # seconds to wait for any one answer


def find_browser():
    for name in (os.environ.get("PATTERN_BROWSER"),) + BROWSERS:
        if name and (shutil.which(name) or Path(name).is_file()):
            return shutil.which(name) or name
    return None


class Gone(Exception):
    pass


class Browser:
    """One headless browser, driven by JSON messages over two pipes."""

    def __init__(self, exe, work):
        for flags in ([], ["--no-sandbox"]):
            self.start(exe, work, flags)
            try:
                self.call("Browser.getVersion")
                break
            except Gone:
                self.stop()
        else:
            raise SystemExit("check: the browser would not start")
        target = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.tab = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        self.call("Page.enable", tab=True)

    def start(self, exe, work, flags):
        ours_r, theirs_w = os.pipe()
        theirs_r, ours_w = os.pipe()
        # the browser listens on its descriptor 3 and answers on 4; the shell renumbers ours to those
        r, w = fcntl.fcntl(theirs_r, fcntl.F_DUPFD, 20), fcntl.fcntl(theirs_w, fcntl.F_DUPFD, 20)
        profile = tempfile.mkdtemp(prefix="profile-", dir=work)
        self.proc = subprocess.Popen(
            ["/bin/sh", "-c", f'exec "$@" 3<&{r} 4>&{w}', "sh", exe, "--headless=new", "--remote-debugging-pipe",
             "--disable-gpu", "--hide-scrollbars", "--no-first-run", f"--user-data-dir={profile}", *flags],
            pass_fds=(r, w), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for fd in (theirs_r, theirs_w, r, w):
            os.close(fd)
        self.r, self.w, self.buf, self.n, self.events = ours_r, ours_w, b"", 0, []

    def stop(self):
        for fd in (self.r, self.w):
            try:
                os.close(fd)
            except OSError:
                pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def read(self):
        end = time.monotonic() + PATIENCE
        while b"\0" not in self.buf:
            if not select.select([self.r], [], [], max(0, end - time.monotonic()))[0]:
                raise SystemExit("check: the browser stopped answering")
            chunk = os.read(self.r, 1 << 20)
            if not chunk:
                raise Gone()
            self.buf += chunk
        raw, _, self.buf = self.buf.partition(b"\0")
        return json.loads(raw)

    def call(self, method, params=None, tab=False):
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params or {}}
        if tab:
            msg["sessionId"] = self.tab
        try:
            os.write(self.w, json.dumps(msg).encode("utf-8") + b"\0")
        except OSError:
            raise Gone()
        while True:
            got = self.read()
            if got.get("id") == self.n:
                if "error" in got:
                    raise SystemExit(f"check: {method}: {got['error'].get('message')}")
                return got["result"]
            self.events.append(got.get("method"))

    def wait(self, event):
        while event not in self.events:
            self.events.append(self.read().get("method"))
        self.events.clear()

    def open(self, url, width, height, phone):
        self.call("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": phone}, tab=True)
        self.events.clear()
        got = self.call("Page.navigate", {"url": url}, tab=True)
        if got.get("errorText"):
            raise SystemExit(f"check: could not open {url}: {got['errorText']}")
        self.wait("Page.loadEventFired")

    def ask(self, js):
        got = self.call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True}, tab=True)
        if "exceptionDetails" in got:
            detail = got["exceptionDetails"]
            raise SystemExit(f"check: the check itself broke: {detail.get('exception', {}).get('description') or detail.get('text')}")
        return json.loads(got["result"]["value"])

    def shoot(self, path, y, width, height):
        got = self.call("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": True,
            "clip": {"x": 0, "y": y, "width": width, "height": height, "scale": 1}}, tab=True)
        path.write_bytes(base64.b64decode(got["data"]))

    def view(self, path):
        """Photograph what the window shows right now. shoot() draws the page from its own top,
        so only this sees what floats over the window: an open dialog, a part fixed in place."""
        got = self.call("Page.captureScreenshot", {"format": "png"}, tab=True)
        path.write_bytes(base64.b64decode(got["data"]))


def tokens():
    """Token colors, read from the stylesheet so the check can never drift from it."""
    css = (KIT / "style.css").read_text(encoding="utf-8")
    found = {"#000000": "black"}
    for name, value in re.findall(r"--(ground|ink|muted|rule|act|ok|fault):\s*(#[0-9A-Fa-f]{6})", css):
        found.setdefault(value.upper(), name)
    return found


def script():
    js = (KIT / "check.js").read_text(encoding="utf-8")
    coverage = (KIT / "fonts" / "coverage.json").read_text(encoding="utf-8")
    return js.replace("/*TOKENS*/{}", json.dumps(tokens())).replace("/*COVERAGE*/{}", coverage)


def address(page, text, work):
    """Where the browser finds the page. An Artifact body first gets the skeleton the Artifact tool gives it."""
    if re.search(r"<(?:html|head|body)\b", text, flags=re.I):
        return page.as_uri()
    whole = work / "page.html"
    whole.write_text('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                     '<meta name="viewport" content="width=device-width, initial-scale=1">'
                     f'<base href="{page.parent.as_uri()}/"></head><body>{text}</body></html>', encoding="utf-8")
    return whole.as_uri()


def cuts(height, tall):
    """Where each slice starts and how tall it is. A short last piece joins the slice before it."""
    tops = list(range(0, height, tall))
    if len(tops) > 1 and height - tops[-1] < tall // 4:
        tops.pop()
    return [(y, (tops[i + 1] if i + 1 < len(tops) else height) - y) for i, y in enumerate(tops)]


def report(results):
    """Print the findings of both widths together. A finding seen at one width only says which."""
    worst = 0
    for level in ("fail", "warn", "note"):
        kinds = {}
        for (width, *_), result in zip(WIDTHS, results):
            for kind, msg in result[level]:
                kinds.setdefault(kind, {}).setdefault(msg, []).append(width)
        for kind, msgs in kinds.items():
            worst = max(worst, level == "fail")
            print(f"{level.upper():5} {kind} ({len(msgs)})")
            for msg, widths in list(msgs.items())[:6]:
                print(f"        {msg}" + ("" if len(widths) == len(results) else f"  [{widths[0]} only]"))
            if len(msgs) > 6:
                print(f"        and {len(msgs) - 6} more")
    return int(worst)


def source(text, size):
    """What the page's own text shows, before any browser draws it."""
    found = {"fail": [], "warn": [], "note": []}
    for slot in sorted(set(PLACE.findall(text)))[:6]:
        found["fail"].append(["slot", f"{slot} was never filled: hand out the built page, never the template"])
    if size > LIMIT:
        found["warn"].append(["size", "over 16 MB, which is more than an Artifact takes: shrink the images"])
    if re.search(r"<html\b", text, flags=re.I) and not re.search(r"<meta[^>]+name=[\"']viewport", text, flags=re.I):
        found["warn"].append(["viewport", "no viewport meta, so a phone draws the page at desktop width"])
    return found


def main(argv):
    out = None
    if len(argv) == 3 and argv[1] == "--shots":
        out = Path(argv[2])
    elif len(argv) != 1 or argv[0].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(2)
    served = re.match(r"https?://", argv[0], flags=re.I)
    if served:
        url, static = argv[0], None     # a served page is read once the browser has it
        stem = re.sub(r"[^A-Za-z0-9]+", "-", url[served.end():]).strip("-") or "page"
        print(url)
    else:
        page = Path(argv[0]).resolve()
        if not page.is_file():
            raise SystemExit(f"check: no page at {page}")
        data = page.read_bytes()
        text, stem = data.decode("utf-8"), page.stem
        static = source(text, len(data))
        print(f"{page} · {len(data) / 1e6:.2f} MB")

    exe = find_browser()
    if not exe:
        if served:
            print("check: no browser found, so nothing was checked. Set PATTERN_BROWSER to a Chromium or Chrome binary.")
            raise SystemExit(2)
        worst = report([static])
        print("NOTE  no browser found, so only the file was read. Set PATTERN_BROWSER to a Chromium or Chrome binary.")
        raise SystemExit(worst)

    work = Path(tempfile.mkdtemp(prefix="pattern-check-"))
    browser = Browser(exe, work)
    try:
        js, results, names = script(), [], []
        if not served:
            url = address(page, text, work)
        if out:
            out.mkdir(parents=True, exist_ok=True)
        for width, height, tall, phone in WIDTHS:
            browser.open(url, width, height, phone)
            if static is None:
                static = source(browser.ask("JSON.stringify(document.documentElement.outerHTML)"), 0)
            result = browser.ask(js)
            for level in static:
                result[level] = static[level] + result[level]
            results.append(result)
            info = result["info"]
            print(f"{info['width']} wide · {info['height']} tall" + ("" if info["width"] == width else f" (asked for {width})"))
            for n, (y, h) in enumerate(cuts(info["height"], tall) if out else [], 1):
                names.append(out / f"{stem}-{width}-{n:02d}.png")
                browser.shoot(names[-1], y, width, h)
        worst = report(results)
        print("FAIL" if worst else "PASS")
        if names:
            print(f"{len(names)} slices to read:")
            for name in names:
                print(f"  {name}")
    finally:
        browser.stop()
        shutil.rmtree(work, ignore_errors=True)
    raise SystemExit(worst)


if __name__ == "__main__":
    main(sys.argv[1:])
