import json
import os
import sys
import traceback
from contextlib import contextmanager

import requests

import passion_env
from rock_log import get_logger

log = get_logger("rock.client")

BASE_URL_ENV = "ROCK_BASE_URL"
USERNAME_ENV = "ROCK_USERNAME"
PASSWORD_ENV = "ROCK_PASSWORD"


class RockError(RuntimeError):
    def operator_message(self):
        return str(self)


class RockConfigError(RockError):
    pass


class RockApiError(RockError):
    def __init__(self, status, method, endpoint, detail):
        self.status = status
        self.method = method
        self.endpoint = endpoint
        self.detail = detail
        super().__init__(f"Rock API HTTP {status} on {method} {endpoint}: {detail}")

    def operator_message(self):
        return f"Error: {self}"


class RockNotFound(RockApiError):
    def operator_message(self):
        return f"Error: not found (404): {self.endpoint}"


class RockAuthError(RockApiError):
    def operator_message(self):
        hint = "The account may lack permission for this endpoint or this record"
        if self.status == 401:
            hint += ", or the session expired"
        return f"{super().operator_message()}\n  {hint}."


class RockLoginFailed(RockAuthError):
    def __init__(self, status=401, method="POST", endpoint="Auth/Login", detail="login rejected"):
        super().__init__(status, method, endpoint, detail)

    def operator_message(self):
        return f"Error: Rock login failed. Check {USERNAME_ENV} and {PASSWORD_ENV} in {passion_env.ENV_FILE}"


class RockUnexpectedResponse(RockApiError):
    def operator_message(self):
        return (f"Error: Rock sent a reply that is not JSON (HTTP {self.status}) on "
                f"{self.method} {self.endpoint}: {self.detail}\n"
                "  The session may have expired or a proxy answered instead of Rock.")


class RockRateLimited(RockApiError):
    def operator_message(self):
        return "Error: rate limited by the Rock API. Try again later."


_STATUS_ERRORS = {404: RockNotFound, 401: RockAuthError, 403: RockAuthError,
                  429: RockRateLimited}


@contextmanager
def api_errors_reported():
    """Library code raises rather than exits, so a build that fails partway still reports what it created."""
    try:
        yield
    except RockError as exc:
        print(exc.operator_message())
        sys.exit(1)
    except requests.RequestException as exc:
        print(f"Error: could not reach Rock. {exc}")
        sys.exit(1)


def require_https(base_url):
    if not base_url.startswith("https://"):
        log.error("%s not HTTPS: %s", BASE_URL_ENV, base_url[:20])
        raise RockConfigError(
            f"Error: {BASE_URL_ENV} must use HTTPS (got: {base_url[:20]}...)\n"
            "  Credentials must not be transmitted over plain HTTP."
        )
    return base_url.rstrip("/")


def get_credentials():
    base_url, username, password = passion_env.require(
        BASE_URL_ENV, USERNAME_ENV, PASSWORD_ENV
    )
    return require_https(base_url), username, password


class RockClient:
    def __init__(self, base_url=None, username=None, password=None):
        if base_url and username and password:
            self.base_url = require_https(base_url)
            self._username = username
            self._password = password
        else:
            self.base_url, self._username, self._password = get_credentials()
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        self._login()

    def _login(self):
        url = f"{self.base_url}/api/Auth/Login"
        resp = self.session.post(url, json={
            "Username": self._username,
            "Password": self._password,
        }, timeout=30)
        if resp.status_code == 204:
            log.info("login ok user=%s", self._username)
            return
        if resp.status_code == 401:
            log.error("login failed user=%s status=401", self._username)
            raise RockLoginFailed()
        log.error("login unexpected status=%d user=%s body=%s",
                   resp.status_code, self._username, resp.text[:200])
        raise RockApiError(resp.status_code, "POST", "Auth/Login", resp.text[:200] or resp.reason)

    def _request(self, method, endpoint, params=None, data=None, timeout=30):
        url = f"{self.base_url}/api/{endpoint.lstrip('/')}"
        resp = self.session.request(method, url, json=data, params=params,
                                    timeout=timeout)
        self._handle_error(resp, method, endpoint, params=params, data=data)
        log.info("%s %s ok %dB", method, endpoint, len(resp.content))
        return resp

    @staticmethod
    def _json_body(resp, method, endpoint):
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            log.error("%s %s non-JSON body=%s", method, endpoint, resp.text[:200])
            raise RockUnexpectedResponse(resp.status_code, method, endpoint, resp.text[:200]) from None

    def get(self, endpoint, params=None, timeout=30):
        resp = self._request("GET", endpoint, params=params, timeout=timeout)
        return self._json_body(resp, "GET", endpoint)

    def post(self, endpoint, data=None, params=None, timeout=30):
        resp = self._request("POST", endpoint, params=params, data=data,
                             timeout=timeout)
        result = None
        if resp.status_code == 201:
            try:
                result = int(resp.text.strip())
            except (ValueError, TypeError):
                pass
        if result is None:
            result = self._json_body(resp, "POST", endpoint)
        log.info("POST %s id=%s", endpoint, result)
        return result

    def patch(self, endpoint, data, params=None, timeout=30):
        self._request("PATCH", endpoint, params=params, data=data, timeout=timeout)
        return True

    def put(self, endpoint, data, *, full_replace, params=None, timeout=30):
        """Rock copies every column from the body, so a partial one nulls the rest and re-Guids the row."""
        if not full_replace:
            raise ValueError(
                "put() replaces every column in the row, nulling the ones you "
                "omit. Pass full_replace=True and send the entity back whole, "
                "or call patch() to change only the fields you supply."
            )
        self._request("PUT", endpoint, params=params, data=data, timeout=timeout)
        return True

    def delete(self, endpoint, params=None, timeout=30):
        self._request("DELETE", endpoint, params=params, timeout=timeout)
        return True

    def set_attribute_value(self, entity, entity_id, key, value, timeout=30):
        """Both go in the query string, because a body makes Rock route this to OData and answer 404."""
        return self.post(f"{entity}/AttributeValue/{entity_id}", params={
            "attributeKey": key,
            "attributeValue": "" if value is None else str(value),
        }, timeout=timeout)

    def _handle_error(self, resp, method="?", endpoint="?", params=None, data=None):
        if resp.ok:
            return
        status = resp.status_code
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text or resp.reason

        detail_str = json.dumps(detail, indent=2) if isinstance(detail, (dict, list)) else str(detail)

        if status == 404:
            log.debug("%s %s status=404", method, endpoint)
            raise RockNotFound(404, method, endpoint, detail)

        log.error(
            "%s %s status=%d\n  response: %s\n  traceback:\n%s",
            method, endpoint, status,
            detail_str[:500],
            "".join(traceback.format_stack()),
        )
        raise _STATUS_ERRORS.get(status, RockApiError)(
            status, method, endpoint, detail_str)


def refuse_unless_writes_enabled(refusal):
    if os.environ.get("ROCK_ALLOW_WRITES") == "1":
        return
    print(refusal, file=sys.stderr)
    sys.exit(2)


def odata_str(value):
    return value.replace("'", "''")

