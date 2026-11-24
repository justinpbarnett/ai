import argparse
import sys

import rock_paths

try:
    from playwright.sync_api import Error as PwError, TimeoutError as PwTimeout, sync_playwright
except ModuleNotFoundError:
    sys.exit(
        "Rock's browser tooling is not installed. It is opt-in, because it needs\n"
        "Playwright and a ~150 MB Chromium download that nothing else here uses.\n"
        "\n"
        "  ROCK_WITH_BROWSER=1 rock.sh catalog status\n"
        "\n"
        "That installs both, once. Every later command keeps them."
    )

from rock_client import RockError, RockLoginFailed, api_errors_reported, get_credentials
from rock_log import get_logger

log = get_logger("rock.browser")


class RockBrowser:
    def __init__(self, headless=True):
        self.base_url, self._username, self._password = get_credentials()
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._context = self._browser.new_context(viewport={"width": 1280, "height": 900})
        self.page = self._context.new_page()
        self._logged_in = False

    def login(self):
        if self._logged_in:
            return True

        log.info("browser login user=%s", self._username)
        self._open(f"{self.base_url}/Login")

        try:
            self.page.fill('input[id$="tbUserName"]', self._username, timeout=10000)
            self.page.fill('input[id$="tbPassword"]', self._password, timeout=5000)
            with self.page.expect_navigation(wait_until="networkidle", timeout=30000):
                self.page.click('a[id$="btnLogin"]', timeout=5000)
        except PwTimeout:
            log.error("browser login timed out -- login form not found or submission hung")
            return False

        current_url = self.page.url
        if "/Login" in current_url or "/login" in current_url:
            error = self.page.query_selector('.alert-danger, .validation-summary-errors, .text-danger')
            err_text = error.inner_text() if error else "unknown"
            log.error("browser login failed: %s", err_text)
            return False

        self._logged_in = True
        log.info("browser login ok url=%s", current_url)
        return True

    def goto(self, path):
        if not self._logged_in and not self.login():
            raise RockLoginFailed()
        url = f"{self.base_url}/{path.lstrip('/')}"
        log.info("browser goto %s", path)
        self._open(url)
        return self.page

    def _open(self, url):
        try:
            self.page.goto(url, wait_until="networkidle", timeout=30000)
        except PwError as exc:
            log.error("browser could not open %s: %s", url, exc)
            raise RockError(f"Error: could not reach Rock. {str(exc).splitlines()[0]}") from exc

    def screenshot(self, path, output=None):
        self.goto(path)
        if output is None:
            rock_paths.SCREENSHOTS.mkdir(parents=True, exist_ok=True)
            slug = path.strip("/").replace("/", "-").replace("?", "_") or "home"
            output = str(rock_paths.SCREENSHOTS / f"{slug}.png")
        self.page.screenshot(path=output, full_page=True)
        log.info("screenshot saved %s", output)
        return output

    def check_element(self, path, selector, timeout=10000):
        self.goto(path)
        try:
            el = self.page.wait_for_selector(selector, timeout=timeout)
            visible = el.is_visible() if el else False
            bbox = el.bounding_box() if el else None
            log.info("check_element path=%s selector=%s visible=%s", path, selector, visible)
            return {"found": True, "visible": visible, "bbox": bbox}
        except PwTimeout:
            log.info("check_element path=%s selector=%s not_found", path, selector)
            return {"found": False, "visible": False, "bbox": None}

    def verify_page(self, page_id):
        path = f"page/{page_id}"
        self.goto(path)
        title = self.page.title()
        status = self.page.evaluate("() => document.readyState")
        errors = self.page.query_selector_all('.alert-danger, .alert-warning, .error')
        error_texts = [e.inner_text() for e in errors]

        rock_error = self.page.query_selector('.exception-detail, .rock-error')
        if rock_error:
            error_texts.append(rock_error.inner_text()[:300])

        result = {
            "page_id": page_id,
            "title": title,
            "url": self.page.url,
            "ready_state": status,
            "errors": error_texts,
            "ok": len(error_texts) == 0,
        }
        log.info("verify_page id=%d ok=%s errors=%d", page_id, result["ok"], len(error_texts))
        return result

    def close(self):
        self._context.close()
        self._browser.close()
        self._pw.stop()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def cmd_login(args):
    with RockBrowser(headless=not args.headed) as browser:
        ok = browser.login()
        if ok:
            print(f"Login successful. URL: {browser.page.url}")
            print(f"Title: {browser.page.title()}")
        else:
            print("Login failed.")
            sys.exit(1)


def cmd_screenshot(args):
    with RockBrowser(headless=not args.headed) as browser:
        output = browser.screenshot(args.path, args.output)
        print(f"Screenshot saved: {output}")


def cmd_check_element(args):
    with RockBrowser(headless=not args.headed) as browser:
        result = browser.check_element(args.path, args.selector)
        if result["found"]:
            vis = "visible" if result["visible"] else "hidden"
            print(f"Element found ({vis}): {args.selector}")
            if result["bbox"]:
                b = result["bbox"]
                print(f"  Position: {b['x']:.0f},{b['y']:.0f} Size: {b['width']:.0f}x{b['height']:.0f}")
        else:
            print(f"Element NOT found: {args.selector}")
            sys.exit(1)


def cmd_verify_page(args):
    with RockBrowser(headless=not args.headed) as browser:
        result = browser.verify_page(args.page_id)
        print(f"Page {args.page_id}: {'OK' if result['ok'] else 'ERRORS'}")
        print(f"  Title: {result['title']}")
        print(f"  URL: {result['url']}")
        if result["errors"]:
            print(f"  Errors ({len(result['errors'])}):")
            for e in result["errors"]:
                print(f"    {e[:200]}")
        if not result["ok"]:
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Rock RMS browser automation")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser")
    headed_anywhere = argparse.ArgumentParser(add_help=False)
    headed_anywhere.add_argument("--headed", action="store_true", default=argparse.SUPPRESS,
                                 help="Run with visible browser")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login", help="Verify browser login works", parents=[headed_anywhere])

    p_ss = subparsers.add_parser("screenshot", help="Take a screenshot", parents=[headed_anywhere])
    p_ss.add_argument("path", help="URL path (e.g. /page/123)")
    p_ss.add_argument("output", nargs="?", help="Output file path")

    p_ce = subparsers.add_parser("check-element", help="Check if element exists", parents=[headed_anywhere])
    p_ce.add_argument("path", help="URL path")
    p_ce.add_argument("selector", help="CSS selector")

    p_vp = subparsers.add_parser("verify-page", help="Verify a page loads without errors", parents=[headed_anywhere])
    p_vp.add_argument("page_id", type=int, help="Rock page ID")

    parsed = parser.parse_args()
    with api_errors_reported():
        if parsed.command == "login":
            cmd_login(parsed)
        elif parsed.command == "screenshot":
            cmd_screenshot(parsed)
        elif parsed.command == "check-element":
            cmd_check_element(parsed)
        elif parsed.command == "verify-page":
            cmd_verify_page(parsed)


if __name__ == "__main__":
    main()
