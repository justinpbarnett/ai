import base64
import fcntl
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import namedtuple
from contextlib import ExitStack, contextmanager
from pathlib import Path

Viewport = namedtuple("Viewport", "width height tall phone")
WIDTHS = (Viewport(1280, 900, 1500, False), Viewport(390, 844, 2200, True))
BROWSERS = ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium")
ANSWER_TIMEOUT_S = 120
QUIET_MS = 400
SETTLE_S = 10
GROUP_TERM_S = 5
GROUP_KILL_S = 5
COUNT_REQUESTS = """(() => {
  let busy = 0;
  const fetchFirst = window.fetch;
  window.fetch = function () { busy++; return fetchFirst.apply(this, arguments).finally(() => busy--); };
  const sendFirst = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () {
    busy++;
    this.addEventListener("loadend", () => busy--, { once: true });
    return sendFirst.apply(this, arguments);
  };
  Object.defineProperty(window, "__patternBusy", { get: () => busy });
})();"""
SETTLE = """(quiet, cap) => new Promise((done) => {
  const start = performance.now();
  let changed = start;
  new MutationObserver(() => { changed = performance.now(); })
    .observe(document, { subtree: true, childList: true, characterData: true, attributes: true });
  (function look() {
    const now = performance.now();
    if (!window.__patternBusy && now - changed >= quiet) return done("true");
    if (now - start >= cap) return done("false");
    setTimeout(look, 50);
  })();
})"""


def find_browser(candidates=BROWSERS):
    chosen = os.environ.get("PATTERN_BROWSER")
    if chosen:
        found = shutil.which(chosen) or (chosen if Path(chosen).is_file() else None)
        if not found:
            raise BrowserError(f"PATTERN_BROWSER is {chosen}, which is neither a file nor on the PATH")
        return found
    for name in candidates:
        if shutil.which(name) or Path(name).is_file():
            return shutil.which(name) or name
    return None


class BrowserError(Exception):
    pass


class Gone(BrowserError):
    def __init__(self):
        super().__init__("the browser went away")


class Browser:
    def __init__(self, exe, work):
        for flags in ((), ("--no-sandbox",)):
            with ExitStack() as cleanup:
                self.start(exe, work, flags)
                cleanup.callback(self.stop)
                try:
                    self.call("Browser.getVersion")
                except Gone:
                    continue
                self.attach_tab()
                cleanup.pop_all()
                return
        raise BrowserError("the browser would not start")

    def start(self, exe, work, flags):
        ours_r, theirs_w = os.pipe()
        theirs_r, ours_w = os.pipe()
        # the browser listens on its descriptor 3 and answers on 4; the shell renumbers ours to those
        r, w = fcntl.fcntl(theirs_r, fcntl.F_DUPFD, 20), fcntl.fcntl(theirs_w, fcntl.F_DUPFD, 20)
        profile = tempfile.mkdtemp(prefix="profile-", dir=work)
        # Off-viewport captures need complete compositor layers and a full raster pass to be repeatable.
        self.proc = subprocess.Popen(
            ["/bin/sh", "-c", f'exec "$@" 3<&{r} 4>&{w}', "sh", exe, "--headless=new", "--remote-debugging-pipe",
             "--run-all-compositor-stages-before-draw", "--disable-partial-raster", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
             f"--user-data-dir={profile}", *flags],
            pass_fds=(r, w), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for fd in (theirs_r, theirs_w, r, w):
            os.close(fd)
        self.r, self.w, self.buf, self.n, self.events = ours_r, ours_w, b"", 0, []

    def attach_tab(self):
        target = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.tab = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        self.call("Page.enable", tab=True)
        self.call("Page.addScriptToEvaluateOnNewDocument", {"source": COUNT_REQUESTS}, tab=True)

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
            self.proc.wait()
        self.end_group()

    def end_group(self):
        for sig, patience_s in ((signal.SIGTERM, GROUP_TERM_S), (signal.SIGKILL, GROUP_KILL_S)):
            if self.signal_group(sig):
                return
            end = time.monotonic() + patience_s
            while time.monotonic() < end:
                if self.signal_group(0):
                    return
                time.sleep(0.02)
        raise BrowserError("the browser left processes running")

    def signal_group(self, sig):
        try:
            os.killpg(self.proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return True
        return False

    def read(self):
        end = time.monotonic() + ANSWER_TIMEOUT_S
        while b"\0" not in self.buf:
            if not select.select([self.r], [], [], max(0, end - time.monotonic()))[0]:
                raise BrowserError("the browser stopped answering")
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
                    raise BrowserError(f"{method}: {got['error'].get('message')}")
                return got["result"]
            self.events.append(got.get("method"))

    def wait(self, event):
        while event not in self.events:
            self.events.append(self.read().get("method"))
        self.events.clear()

    def open(self, url, width, height, phone):
        self.call("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": phone}, tab=True)
        self.go("about:blank")      # a page reopened at the same address with a #fragment never fires load
        self.go(url)
        return self.settle()

    def settle(self):
        return self.ask(f"({SETTLE})({QUIET_MS}, {SETTLE_S * 1000})")

    def go(self, url):
        self.events.clear()
        got = self.call("Page.navigate", {"url": url}, tab=True)
        if got.get("errorText"):
            raise BrowserError(f"could not open {url}: {got['errorText']}")
        self.wait("Page.loadEventFired")

    def ask(self, js):
        got = self.call("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True}, tab=True)
        if "exceptionDetails" in got:
            detail = got["exceptionDetails"]
            raise BrowserError(f"the check itself broke: {detail.get('exception', {}).get('description') or detail.get('text')}")
        return json.loads(got["result"]["value"])

    def shoot(self, path, y, width, height):
        got = self.call("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": True,
            "clip": {"x": 0, "y": y, "width": width, "height": height, "scale": 1}}, tab=True)
        path.write_bytes(base64.b64decode(got["data"]))

    def view(self, path):
        got = self.call("Page.captureScreenshot", {"format": "png"}, tab=True)
        path.write_bytes(base64.b64decode(got["data"]))


@contextmanager
def browser_session(exe, prefix):
    with tempfile.TemporaryDirectory(prefix=prefix) as directory:
        work = Path(directory)
        browser = Browser(exe, work)
        try:
            yield browser, work
        finally:
            browser.stop()


def cuts(height, tall):
    tops = list(range(0, height, tall))
    if len(tops) > 1 and height - tops[-1] < tall // 4:
        tops.pop()
    return [(y, (tops[i + 1] if i + 1 < len(tops) else height) - y) for i, y in enumerate(tops)]


def run_reporting(body, argv, program):
    try:
        body(argv)
    except BrowserError as failure:
        print(f"{program}: {failure}", file=sys.stderr)
        raise SystemExit(2)
    except SystemExit as stop:
        if isinstance(stop.code, str):
            print(stop.code, file=sys.stderr)
            raise SystemExit(2)
        raise
