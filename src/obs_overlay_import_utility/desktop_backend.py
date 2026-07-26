"""Stdio JSON-lines backend for the Electron desktop shell.

This module implements a minimal, safe request/response protocol over
``stdin``/``stdout`` using newline-delimited JSON.  It exposes **only** two
commands:

* ``health``   — returns the backend liveness and process metadata.
* ``app_info`` — returns the application name and version.

Security design:

* There is **no** shell-command endpoint, **no** arbitrary file-read endpoint,
  and **no** generic function-call endpoint.
* Every request must carry a ``request_id`` (string) and a ``command``
  (string).  Malformed or unknown commands produce a structured ``error``
  response rather than raising.
* All output is flushed immediately so the Electron main process can read it
  line-by-line.

Protocol (one JSON object per line on stdout):

Request::

    {"request_id": "abc-1", "command": "health"}

Success response::

    {"request_id": "abc-1", "type": "result", "data": {"status": "ok", ...}}

Error response::

    {"request_id": "abc-1", "type": "error", "error": {"code": "unknown_command", "message": "..."}}
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from .constants import APP_TITLE, __version__

__all__ = ["Backend", "run"]


# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

#: Monotonic start time used for uptime reporting.
_START_TIME: float = time.monotonic()


@dataclass
class Request:
    """Parsed request envelope."""

    request_id: str
    command: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Response:
    """Serialisable response envelope."""

    request_id: str
    type: str  # "result" | "error"
    data: dict[str, Any] | None = None
    error: dict[str, str] | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "request_id": self.request_id,
                "type": self.type,
                **({"data": self.data} if self.data is not None else {}),
                **({"error": self.error} if self.error is not None else {}),
            },
            ensure_ascii=False,
        )


def _send(response: Response) -> None:
    """Write a single JSON line to stdout and flush."""
    sys.stdout.write(response.to_json() + "\n")
    sys.stdout.flush()


def _parse_request(line: str) -> Request | None:
    """Parse a raw line into a :class:`Request`.

    Returns ``None`` for blank lines.  Raises :class:`ValueError` for
    malformed JSON or structurally invalid requests.
    """
    stripped = line.strip()
    if not stripped:
        return None

    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc

    if not isinstance(obj, dict):
        raise ValueError("request must be a JSON object")

    request_id = obj.get("request_id")
    command = obj.get("command")

    if not isinstance(request_id, str) or not request_id:
        raise ValueError("request_id must be a non-empty string")
    if not isinstance(command, str) or not command:
        raise ValueError("command must be a non-empty string")

    params = obj.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("params must be a JSON object")

    return Request(request_id=request_id, command=command, params=params)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

#: Set of commands this backend is allowed to handle.
ALLOWED_COMMANDS: frozenset[str] = frozenset({"health", "app_info"})


class Backend:
    """Handles a single request and returns a :class:`Response`."""

    def handle(self, request: Request) -> Response:
        if request.command not in ALLOWED_COMMANDS:
            return Response(
                request_id=request.request_id,
                type="error",
                error={
                    "code": "unknown_command",
                    "message": f"Unknown command: {request.command!r}. "
                    f"Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}.",
                },
            )

        handler = getattr(self, f"_cmd_{request.command}", None)
        if handler is None:
            return Response(
                request_id=request.request_id,
                type="error",
                error={
                    "code": "unimplemented",
                    "message": f"Command {request.command!r} is not implemented.",
                },
            )
        return handler(request)

    # -- health ----------------------------------------------------------

    def _cmd_health(self, request: Request) -> Response:
        return Response(
            request_id=request.request_id,
            type="result",
            data={
                "status": "ok",
                "pid": os.getpid(),
                "uptime_seconds": round(time.monotonic() - _START_TIME, 3),
                "python_version": sys.version.split()[0],
            },
        )

    # -- app_info --------------------------------------------------------

    def _cmd_app_info(self, request: Request) -> Response:
        return Response(
            request_id=request.request_id,
            type="result",
            data={
                "name": APP_TITLE,
                "version": __version__,
            },
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    """Read requests from stdin, write responses to stdout.

    The loop exits cleanly on EOF (``stdin`` closed).
    """
    backend = Backend()
    for raw_line in sys.stdin:
        try:
            request = _parse_request(raw_line)
        except ValueError as exc:
            # We cannot echo back a request_id we could not parse, so emit
            # a generic error with a synthetic id.
            _send(
                Response(
                    request_id="__parse_error__",
                    type="error",
                    error={"code": "malformed_request", "message": str(exc)},
                )
            )
            continue

        if request is None:
            continue

        try:
            response = backend.handle(request)
        except Exception:  # noqa: BLE001 — never crash the backend
            response = Response(
                request_id=request.request_id,
                type="error",
                error={"code": "internal_error", "message": "Internal backend error"},
            )

        _send(response)


if __name__ == "__main__":
    run()
