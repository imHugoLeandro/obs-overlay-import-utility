"""Stdio JSON-lines backend for the Electron desktop shell.

This module implements a minimal, safe request/response protocol over
``stdin``/``stdout`` using newline-delimited JSON.  It exposes a finite
set of commands:

* ``health``            — returns the backend liveness and process metadata.
* ``app_info``          — returns the application name and version.
* ``scan_collections``  — scan a folder for OBS collections (path from
                          Electron main, never from the renderer).
* ``convert_collection``— run path-fix conversion on a collection (paths
                          from Electron main, never from the renderer).

Security design:

* There is **no** shell-command endpoint, **no** arbitrary file-read
  endpoint, and **no** generic function-call endpoint.
* Every request must carry a ``request_id`` (string) and a ``command``
  (string).  Malformed or unknown commands produce a structured
  ``error`` response rather than raising.
* All output is flushed immediately so the Electron main process can
  read it line-by-line.
* The renderer never sends paths to the backend — only Electron main
  does, over the trusted stdio channel.  The backend receives concrete
  folder and collection paths only from Electron main.
* Every request and operation payload is validated.
* Customer-safe ``UtilityError`` messages are used throughout;
  tracebacks are never returned.

Protocol (one JSON object per line on stdout):

Request::

    {"request_id": "abc-1", "command": "health"}

Success response::

    {"request_id": "abc-1", "type": "result", "data": {"status": "ok", ...}}

Error response::

    {"request_id": "abc-1", "type": "error", "error": {"code": "...", "message": "..."}}
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import APP_TITLE, __version__
from .core import find_scene_collections, convert_collection
from .models import UtilityError

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


def _err(code: str, message: str) -> dict[str, str]:
    """Build a safe error dict."""
    return {"code": code, "message": message}


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

#: Set of commands this backend is allowed to handle.
ALLOWED_COMMANDS: frozenset[str] = frozenset({
    "health",
    "app_info",
    "scan_collections",
    "convert_collection",
})


class Backend:
    """Handles a single request and returns a :class:`Response`.

    The backend does NOT own any selection store.  Electron main is the
    sole owner of selected absolute paths and opaque IDs.  The backend
    receives concrete folder and collection paths only from Electron
    main over the trusted stdio channel.
    """

    def handle(self, request: Request) -> Response:
        if request.command not in ALLOWED_COMMANDS:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err(
                    "unknown_command",
                    f"Unknown command: {request.command!r}. "
                    f"Allowed: {', '.join(sorted(ALLOWED_COMMANDS))}.",
                ),
            )

        handler = getattr(self, f"_cmd_{request.command}", None)
        if handler is None:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err(
                    "unimplemented",
                    f"Command {request.command!r} is not implemented.",
                ),
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

    # -- scan_collections ------------------------------------------------

    def _cmd_scan_collections(self, request: Request) -> Response:
        """Scan a folder for OBS scene collection JSON files.

        The folder path is provided by Electron main (not the renderer).
        Uses the existing ``find_scene_collections()`` engine.

        Returns a list of detected collections with safe relative labels
        (relative to the selected folder).  No raw absolute paths are
        returned to the renderer.
        """
        params = request.params
        folder_path = params.get("folder_path")

        if not isinstance(folder_path, str) or not folder_path.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "folder_path must be a non-empty string."),
            )

        try:
            folder = Path(folder_path).expanduser().resolve()
        except (OSError, ValueError):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_folder", "The selected path is not valid."),
            )

        if not folder.is_dir():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_folder", "Choose a valid overlay folder first."),
            )

        try:
            collections = find_scene_collections(folder)
        except UtilityError as exc:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("scan_failed", str(exc)),
            )

        # Build the scan result.  The canonical absolute ``path`` is sent
        # ONLY to Electron main (the trusted stdio channel).  The safe
        # relative ``label`` is the only field that may reach the renderer
        # (via Electron main, which converts it to an opaque collection ID).
        detected: list[dict[str, Any]] = []
        for collection_path in collections:
            try:
                rel = collection_path.relative_to(folder)
                label = str(rel)
            except ValueError:
                label = collection_path.name
            detected.append({
                "path": str(collection_path),
                "label": label,
            })

        return Response(
            request_id=request.request_id,
            type="result",
            data={
                "collections": detected,
                "count": len(detected),
            },
        )

    # -- convert_collection ----------------------------------------------

    def _cmd_convert_collection(self, request: Request) -> Response:
        """Run path-fix conversion on a collection.

        The folder and collection paths are provided by Electron main
        (not the renderer).  Uses the existing ``convert_collection()``
        engine.  The original collection is never modified.

        Retry semantics: a failed strict validation, missing file result,
        ambiguity result, or customer-safe UtilityError returns a result
        with ``success: false`` — the caller (Electron main) does NOT
        consume the selection, so the user can retry with different
        options.
        """
        params = request.params
        folder_path = params.get("folder_path")
        collection_path = params.get("collection_path")
        strict = params.get("strict", True)
        case_sensitive = params.get("case_sensitive", True)

        # Validate folder_path.
        if not isinstance(folder_path, str) or not folder_path.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "folder_path must be a non-empty string."),
            )

        # Validate collection_path.
        if not isinstance(collection_path, str) or not collection_path.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "collection_path must be a non-empty string."),
            )

        # Validate boolean options.
        if not isinstance(strict, bool):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "strict must be a boolean."),
            )
        if not isinstance(case_sensitive, bool):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "case_sensitive must be a boolean."),
            )

        # Resolve paths.
        try:
            folder = Path(folder_path).expanduser().resolve()
            collection = Path(collection_path).expanduser().resolve()
        except (OSError, ValueError):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_path", "The selected path is not valid."),
            )

        # Validate folder exists and is a directory.
        if not folder.is_dir():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_folder", "Choose a valid overlay folder first."),
            )

        # Validate collection exists and is a regular file.
        if not collection.exists() or not collection.is_file():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_collection",
                           "The selected collection is no longer available. Scan the folder again."),
            )

        # Validate collection is inside the folder (symlink/reparse-point escape).
        try:
            collection.relative_to(folder)
        except ValueError:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("collection_not_in_folder",
                           "The selected collection is not inside the chosen folder."),
            )

        try:
            result = convert_collection(
                collection,
                folder,
                strict=strict,
                case_sensitive=case_sensitive,
            )
        except UtilityError as exc:
            return Response(
                request_id=request.request_id,
                type="result",
                data={
                    "success": False,
                    "error": str(exc),
                    "changed": 0,
                    "unchanged": 0,
                    "missing": [],
                    "ambiguous": [],
                    "indexed_files": 0,
                    "candidate_paths": 0,
                },
            )

        # Build the response data from the ConversionResult.
        data: dict[str, Any] = {
            "success": result.success,
            "changed": result.changed,
            "unchanged": result.unchanged,
            "missing": list(result.missing),
            "indexed_files": result.indexed_files,
            "candidate_paths": result.candidate_paths,
        }

        # Ambiguous matches: return safe relative labels.
        ambiguous_list: list[dict[str, Any]] = []
        for match in result.ambiguous:
            candidates_rel: list[str] = []
            for candidate in match.candidates:
                try:
                    rel = Path(candidate).relative_to(folder)
                    candidates_rel.append(str(rel))
                except ValueError:
                    candidates_rel.append(Path(candidate).name)
            ambiguous_list.append({
                "source_name": match.source_name,
                "original_path": match.original_path,
                "candidates": candidates_rel,
            })
        data["ambiguous"] = ambiguous_list

        if result.error:
            data["error"] = result.error

        if result.output_path is not None:
            try:
                rel = result.output_path.relative_to(folder)
                data["output_path"] = str(rel)
                data["output_filename"] = rel.name
            except ValueError:
                data["output_filename"] = result.output_path.name

        return Response(
            request_id=request.request_id,
            type="result",
            data=data,
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
                    error=_err("malformed_request", str(exc)),
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
                error=_err("internal_error", "Internal backend error"),
            )

        _send(response)


if __name__ == "__main__":
    run()
