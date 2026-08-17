"""The thin HTTP layer both API clients share.

The transport is a plain callable so tests can substitute a scripted one. The
real implementation is urllib; nothing here needs `requests`, and not needing
it means nothing to install and nothing to keep up to date.
"""

import json
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 20


class ApiError(Exception):
    """A request failed in a way worth showing the user verbatim."""


class AuthError(ApiError):
    """Credentials were rejected. Names which service, so the right token
    gets renewed."""


class NetworkError(ApiError):
    """The service could not be reached at all — offline, VPN, proxy."""


class Response:
    def __init__(self, status, body):
        self.status = status
        self.body = body

    def json(self, service):
        try:
            return json.loads(self.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(
                f"{service} returned something that isn't JSON "
                f"(HTTP {self.status}). A proxy or sign-in page is the usual cause."
            ) from None


def urllib_transport(method, url, headers=None, body=None, timeout=DEFAULT_TIMEOUT):
    request = urllib.request.Request(
        url, data=body.encode("utf-8") if body else None,
        headers=headers or {}, method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(response.status, response.read())
    except urllib.error.HTTPError as error:
        return Response(error.code, error.read())
    except urllib.error.URLError as error:
        raise NetworkError(f"Can't reach {url.split('/')[2]}: {error.reason}") from None
    except TimeoutError:
        raise NetworkError(f"{url.split('/')[2]} did not respond in time.") from None


def check_status(response, service, context=""):
    """Turn a non-2xx response into the clearest exception available.

    Server error text is passed through rather than replaced: Tempo's own
    "Period is closed for the given date" tells the user far more than any
    message this code could invent.
    """
    if 200 <= response.status < 300:
        return

    detail = _extract_message(response)
    where = f" ({context})" if context else ""

    if response.status in (401, 403):
        raise AuthError(
            f"{service} rejected the credentials{where}. "
            f"Check your {service} API token in credentials.toml."
        )
    raise ApiError(f"{service} error {response.status}{where}: {detail}")


def _extract_message(response):
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return response.body.decode("utf-8", "replace")[:200] or "no detail given"

    if isinstance(payload, dict):
        # Jira uses errorMessages/errors; Tempo uses errors[].message.
        messages = payload.get("errorMessages") or []
        for error in payload.get("errors") or []:
            if isinstance(error, dict) and error.get("message"):
                messages.append(error["message"])
            elif isinstance(error, str):
                messages.append(error)
        if not messages and payload.get("message"):
            messages.append(payload["message"])
        if messages:
            return "; ".join(str(m) for m in messages)

    return "no detail given"
