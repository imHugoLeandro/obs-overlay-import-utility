"""Stdio JSON-lines backend for the Electron desktop shell.

This module implements a minimal, safe request/response protocol over
``stdin``/``stdout`` using newline-delimited JSON.  It exposes a finite
set of commands:

* ``health``            — returns the backend liveness and process metadata.
* ``app_info``          — returns the application name and version.
* ``choose_folder``     — store an overlay folder path; return an opaque ID.
* ``scan_collections``  — scan the selected folder for OBS collections.
* ``choose_collection`` — select one detected collection by index.
* ``convert_collection``— run path-fix conversion on the selected collection.

Security design:

* There is **no** shell-command endpoint, **no** arbitrary file-read endpoint,
  and **no** generic function-call endpoint.
* Every request must carry a ``request_id`` (string) and a ``command``
  (string).  Malformed or unknown commands produce a structured ``error``
  response rather than raising.
* All output is flushed immediately so the Electron main process can read it
  line-by-line.
* Selected absolute paths are held in an in-memory, session-only selection
  store.  The renderer receives opaque selection IDs plus safe display labels
  only — never raw absolute paths.
* Every request and operation payload is validated.  Expired, unknown,
  mismatched, or reused-invalid selection IDs are rejected with a structured
  safe error.
* The Python backend receives actual paths only after the main process
  resolves the opaque IDs (the main process is responsible for the folder
  dialog and passes the resolved path to ``choose_folder``).
* Customer-safe ``UtilityError`` messages are used throughout; tracebacks
  are never returned.

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
import secrets
import sys
import time
import uuid
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
# Selection store — in-memory, session-only, opaque IDs
# ---------------------------------------------------------------------------

@dataclass
class _Selection:
    """Internal record for a single user selection."""

    selection_id: str
    folder_path: str  # absolute path to the selected overlay folder
    folder_label: str  # safe relative display label (never the raw path)
    collections: list[dict[str, Any]] = field(default_factory=list)
    collection_index: int | None = None  # which collection the user chose


class SelectionStore:
    """In-memory, session-only store for opaque selection IDs.

    The store holds absolute paths that the renderer never sees.  Only
    opaque selection IDs and safe display labels are returned to the
    renderer.  Selection IDs are cryptographically random and expire after
    a single use for ``convert_collection`` to prevent replay.
    """

    def __init__(self) -> None:
        self._store: dict[str, _Selection] = {}

    def add_folder(self, folder_path: str) -> tuple[str, str]:
        """Register a folder and return (selection_id, folder_label).

        The label is the folder basename — a safe, human-readable string
        that does not reveal the absolute path.
        """
        folder = Path(folder_path).expanduser().resolve()
        label = folder.name if folder.name else str(folder)
        selection_id = secrets.token_urlsafe(16)
        self._store[selection_id] = _Selection(
            selection_id=selection_id,
            folder_path=str(folder),
            folder_label=label,
        )
        return selection_id, label

    def get(self, selection_id: str) -> _Selection | None:
        """Return the selection for the given ID, or None if unknown/expired."""
        return self._store.get(selection_id)

    def consume(self, selection_id: str) -> _Selection | None:
        """Return and remove the selection (single-use for conversion)."""
        return self._store.pop(selection_id, None)

    def clear(self) -> None:
        """Clear all selections (used on backend shutdown)."""
        self._store.clear()


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

#: Set of commands this backend is allowed to handle.
ALLOWED_COMMANDS: frozenset[str] = frozenset({
    "health",
    "app_info",
    "choose_folder",
    "scan_collections",
    "choose_collection",
    "convert_collection",
})


class Backend:
    """Handles a single request and returns a :class:`Response`."""

    def __init__(self) -> None:
        self._selections = SelectionStore()

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

    # -- choose_folder ---------------------------------------------------

    def _cmd_choose_folder(self, request: Request) -> Response:
        """Store an overlay folder path and return an opaque selection ID.

        The main process resolves the folder dialog and passes the absolute
        path here.  We validate it, store it, and return only an opaque ID
        plus a safe display label (the folder basename).
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

        selection_id, label = self._selections.add_folder(str(folder))
        return Response(
            request_id=request.request_id,
            type="result",
            data={
                "selection_id": selection_id,
                "folder_label": label,
            },
        )

    # -- scan_collections ------------------------------------------------

    def _cmd_scan_collections(self, request: Request) -> Response:
        """Scan the selected folder for OBS scene collection JSON files.

        Returns a list of detected collections with safe relative labels
        (relative to the selected folder).  No raw absolute paths are
        returned.
        """
        params = request.params
        selection_id = params.get("selection_id")

        if not isinstance(selection_id, str) or not selection_id:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "selection_id must be a non-empty string."),
            )

        selection = self._selections.get(selection_id)
        if selection is None:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("expired_or_unknown_selection",
                           "This selection is no longer valid. Choose a folder again."),
            )

        folder = Path(selection.folder_path)
        try:
            collections = find_scene_collections(folder)
        except UtilityError as exc:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("scan_failed", str(exc)),
            )

        # Build safe relative labels for each collection.
        detected: list[dict[str, Any]] = []
        for index, collection_path in enumerate(collections):
            try:
                rel = collection_path.relative_to(folder)
                label = str(rel)
            except ValueError:
                label = collection_path.name
            detected.append({
                "index": index,
                "label": label,
            })

        # Cache the collection paths on the selection for later use.
        selection.collections = detected
        selection.collection_index = None

        return Response(
            request_id=request.request_id,
            type="result",
            data={
                "selection_id": selection_id,
                "folder_label": selection.folder_label,
                "collections": detected,
                "count": len(detected),
            },
        )

    # -- choose_collection ------------------------------------------------

    def _cmd_choose_collection(self, request: Request) -> Response:
        """Select one detected collection by its index.

        Validates that the index is within range and that the collection
        path is inside the selected folder.  Stores the chosen collection
        path internally for the subsequent convert step.
        """
        params = request.params
        selection_id = params.get("selection_id")
        collection_index = params.get("collection_index")

        if not isinstance(selection_id, str) or not selection_id:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "selection_id must be a non-empty string."),
            )

        if not isinstance(collection_index, int) or isinstance(collection_index, bool):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "collection_index must be an integer."),
            )

        selection = self._selections.get(selection_id)
        if selection is None:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("expired_or_unknown_selection",
                           "This selection is no longer valid. Choose a folder again."),
            )

        if not selection.collections:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("no_collections", "No collections have been scanned yet."),
            )

        if collection_index < 0 or collection_index >= len(selection.collections):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_collection_index",
                           "The selected collection is out of range."),
            )

        # Re-resolve the collection path from the folder + stored index.
        folder = Path(selection.folder_path)
        try:
            collections = find_scene_collections(folder)
        except UtilityError as exc:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("scan_failed", str(exc)),
            )

        if collection_index >= len(collections):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_collection_index",
                           "The selected collection is out of range."),
            )

        collection_path = collections[collection_index]

        # Verify the collection is inside the selected folder.
        try:
            collection_path.relative_to(folder)
        except ValueError:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("collection_not_in_folder",
                           "The selected collection is not inside the chosen folder."),
            )

        selection.collection_index = collection_index

        # Return a safe label only.
        try:
            rel = collection_path.relative_to(folder)
            label = str(rel)
        except ValueError:
            label = collection_path.name

        return Response(
            request_id=request.request_id,
            type="result",
            data={
                "selection_id": selection_id,
                "collection_label": label,
            },
        )

    # -- convert_collection ----------------------------------------------

    def _cmd_convert_collection(self, request: Request) -> Response:
        """Run path-fix conversion on the selected collection.

        Calls the existing ``convert_collection()`` with the selected
        folder, selected collection, strict option, and case-sensitive
        option.  Returns a structured result with success/failure details.
        The original collection is never modified.
        """
        params = request.params
        selection_id = params.get("selection_id")
        strict = params.get("strict", True)
        case_sensitive = params.get("case_sensitive", True)

        if not isinstance(selection_id, str) or not selection_id:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "selection_id must be a non-empty string."),
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

        # Consume the selection (single-use to prevent replay).
        selection = self._selections.consume(selection_id)
        if selection is None:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("expired_or_unknown_selection",
                           "This selection is no longer valid. Choose a folder and collection again."),
            )

        if selection.collection_index is None:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("no_collection_selected",
                           "No collection has been selected. Choose one first."),
            )

        folder = Path(selection.folder_path)
        try:
            collections = find_scene_collections(folder)
        except UtilityError as exc:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("scan_failed", str(exc)),
            )

        if selection.collection_index >= len(collections):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_collection_index",
                           "The selected collection is out of range."),
            )

        collection_path = collections[selection.collection_index]

        # Verify the collection is inside the selected folder.
        try:
            collection_path.relative_to(folder)
        except ValueError:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("collection_not_in_folder",
                           "The selected collection is not inside the chosen folder."),
            )

        try:
            result = convert_collection(
                collection_path,
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

    # Clean up the selection store on exit.
    backend._selections.clear()


if __name__ == "__main__":
    run()
