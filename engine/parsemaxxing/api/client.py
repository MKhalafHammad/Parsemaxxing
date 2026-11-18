"""The CLI's client for the engine HTTP API (design 7.3: CLI mutating commands go through the
API, so they get the same role checks and audit as the UI). Standard library only.

Sends `Authorization: Bearer <pmxt_ token>` (never on a redirect, which is refused anyway, and
never through an environment proxy) and the custom CSRF header. An error answer becomes
ApiError with the envelope's message and request id; the token never appears in either.
"""

import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable

CSRF_HEADER = "X-Parsemaxxing"
TIMEOUT_S = 60.0
# (request, timeout) -> (status, body). Tests pass one backed by FastAPI's TestClient.
Send = Callable[[urllib.request.Request, float], tuple[int, bytes]]


class ApiError(Exception):
    def __init__(self, status: int, message: str, request_id: str = ""):
        super().__init__(message)
        self.status, self.message, self.request_id = status, message, request_id

    def __str__(self) -> str:
        return f"{self.message} (HTTP {self.status}, request {self.request_id or 'unknown'})"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # the engine never redirects
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def urlopen_send(request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    try:
        # The scheme is http(s) only (config.api_url).
        with _OPENER.open(request, timeout=timeout) as r:  # nosec B310
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise ApiError(0, f"cannot reach the engine API ({type(reason).__name__})") from None


def _printable(text: str) -> str:
    return "".join(c for c in text if c.isprintable())[:500]


class Api:
    def __init__(self, url: str, token: str, send: Send | None = None):
        self.url, self._token, self.send = url, token, send or urlopen_send

    def __repr__(self) -> str:
        return f"Api({self.url!r})"

    def call(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        fields: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes]] | None = None,
        timeout: float = TIMEOUT_S,
    ) -> dict:
        headers = {CSRF_HEADER: "1", "Accept": "application/json"}
        data = None
        if files is not None:
            data, headers["Content-Type"] = multipart(fields or {}, files)
        elif body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        request = urllib.request.Request(  # noqa: S310 - http(s) only (config.api_url)
            self.url + path, data=data, method=method, headers=headers
        )
        request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        status, raw = self.send(request, timeout)
        try:
            out = json.loads(raw) if raw else {}
        except ValueError:
            out = None
        if 200 <= status < 300 and isinstance(out, (dict, list)):
            return out
        error = out.get("error") if isinstance(out, dict) else None
        if isinstance(error, dict):
            raise ApiError(
                status,
                _printable(str(error.get("message", ""))) or "request refused",
                _printable(str(error.get("request_id", "")))[:64],
            )
        raise ApiError(status, "unexpected answer from the engine API")


def multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes]]) -> tuple[bytes, str]:
    """multipart/form-data. Names and file names are the CLI's own (file names already passed
    intake.safe_name), so they hold no quote or line break."""
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in fields.items()
    ]
    for k, (name, data) in files.items():
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        )
        parts.append(head.encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
