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
* ``import_streamlabs`` — import a Streamlabs ``.overlay`` archive (path
                          from Electron main).
* ``automatic_import``  — detect and import one supported package (path
                          from Electron main).
* ``device_requirements`` — list configurable device sources for an
                          installed collection (path from Electron main).
* ``device_candidates`` — list reusable local device settings (paths from
                          Electron main).
* ``apply_device_choices`` — apply selected device settings to a
                          collection (path from Electron main).
* ``obs_running``       — check whether OBS appears to be running.
* ``activate_collection`` — activate a collection in OBS via WebSocket
                          (password forwarded once, never persisted).
* ``list_export_collections`` — list OBS scene collections for export.
* ``build_export_plan`` — build a frozen, backend-held export plan.
* ``export_inventory``  — return a sanitized inventory view of a plan.
* ``confirm_export``    — execute a frozen export plan by opaque ID.

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
* OBS WebSocket passwords are accepted only for a single activation
  request, forwarded once, and never written anywhere.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .automatic import automatically_import_overlay
from .constants import APP_TITLE, __version__
from .core import find_scene_collections, convert_collection
from .device_setup import (
    DeviceCandidate,
    apply_device_choices,
    available_device_candidates,
    collection_device_requirements,
)
from .exporter import (
    DependencyReport,
    build_export_plan,
    export_inventory_from_plan,
    export_scene_collection,
    list_obs_scene_collections,
)
from .models import UtilityError
from .obs_live import (
    ObsAuthenticationRequired,
    ObsNotRunningError,
    ObsRequestError,
    is_obs_running,
    ObsWebSocketClient,
)
from .streamlabs import import_streamlabs_overlay

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


def _validate_path_param(
    request: Request, params: dict[str, Any], key: str, label: str
) -> Path | None:
    """Validate a path parameter; return a resolved Path or a Response error."""
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return Path(value).expanduser().resolve()
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Backend-held export plan store
# ---------------------------------------------------------------------------

@dataclass
class _ExportPlanRecord:
    """Backend-held record for a frozen export plan."""

    plan_id: str
    plan: Any  # ExportPlan
    created_at: float
    executed: bool = False


#: TTL for export plan IDs (15 minutes).
_EXPORT_PLAN_TTL_SECONDS = 15 * 60

#: In-memory store of frozen export plans, keyed by plan_id.
_export_plans: dict[str, _ExportPlanRecord] = {}


def _prune_export_plans() -> None:
    """Remove expired export plan records."""
    now = time.monotonic()
    expired = [
        pid for pid, rec in _export_plans.items()
        if now - rec.created_at > _EXPORT_PLAN_TTL_SECONDS
    ]
    for pid in expired:
        del _export_plans[pid]


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

#: Set of commands this backend is allowed to handle.
ALLOWED_COMMANDS: frozenset[str] = frozenset({
    "health",
    "app_info",
    "scan_collections",
    "convert_collection",
    "import_streamlabs",
    "automatic_import",
    "device_requirements",
    "device_candidates",
    "apply_device_choices",
    "obs_running",
    "activate_collection",
    "list_export_collections",
    "build_export_plan",
    "export_inventory",
    "confirm_export",
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
                error=_err(
                    "invalid_collection",
                    "The selected collection is no longer available. Scan the folder again.",
                ),
            )

        # Validate collection is inside the folder (symlink/reparse-point escape).
        try:
            collection.relative_to(folder)
        except ValueError:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err(
                    "collection_not_in_folder",
                    "The selected collection is not inside the chosen folder.",
                ),
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

    # -- import_streamlabs ------------------------------------------------

    def _cmd_import_streamlabs(self, request: Request) -> Response:
        """Import a Streamlabs ``.overlay`` archive.

        The archive path and OBS scenes directory are provided by Electron
        main (not the renderer).  Uses the existing
        ``import_streamlabs_overlay()`` engine.  The original archive is
        never modified.
        """
        params = request.params
        archive_path = params.get("archive_path")
        obs_scenes_directory = params.get("obs_scenes_directory")

        if not isinstance(archive_path, str) or not archive_path.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "archive_path must be a non-empty string."),
            )
        if not isinstance(obs_scenes_directory, str) or not obs_scenes_directory.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "obs_scenes_directory must be a non-empty string."),
            )

        try:
            archive = Path(archive_path).expanduser().resolve()
            scenes_dir = Path(obs_scenes_directory).expanduser().resolve()
        except (OSError, ValueError):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_path", "The selected path is not valid."),
            )

        if not archive.is_file():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_archive", "Choose a valid Streamlabs .overlay file."),
            )

        try:
            result = import_streamlabs_overlay(archive, scenes_dir)
        except UtilityError as exc:
            return Response(
                request_id=request.request_id,
                type="result",
                data={
                    "success": False,
                    "error": str(exc),
                    "collection_name": "",
                    "canvas_width": 2560,
                    "canvas_height": 1440,
                    "imported_sources": 0,
                    "skipped_sources": [],
                },
            )

        data: dict[str, Any] = {
            "success": result.success,
            "collection_name": result.collection_name,
            "canvas_width": result.canvas_width,
            "canvas_height": result.canvas_height,
            "imported_sources": result.imported_sources,
            "skipped_sources": list(result.skipped_sources),
        }
        if result.error:
            data["error"] = result.error
        if result.profile_name:
            data["profile_name"] = result.profile_name

        return Response(
            request_id=request.request_id,
            type="result",
            data=data,
        )

    # -- automatic_import -------------------------------------------------

    def _cmd_automatic_import(self, request: Request) -> Response:
        """Detect and import one supported package.

        The overlay root and OBS scenes directory are provided by Electron
        main (not the renderer).  Uses the existing
        ``automatically_import_overlay()`` engine.
        """
        params = request.params
        overlay_root = params.get("overlay_root")
        obs_scenes_directory = params.get("obs_scenes_directory")
        strict = params.get("strict", True)
        case_sensitive = params.get("case_sensitive", True)

        if not isinstance(overlay_root, str) or not overlay_root.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "overlay_root must be a non-empty string."),
            )
        if not isinstance(obs_scenes_directory, str) or not obs_scenes_directory.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "obs_scenes_directory must be a non-empty string."),
            )
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

        try:
            root = Path(overlay_root).expanduser().resolve()
            scenes_dir = Path(obs_scenes_directory).expanduser().resolve()
        except (OSError, ValueError):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_path", "The selected path is not valid."),
            )

        if not root.is_dir():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_folder", "Choose a valid overlay folder first."),
            )

        try:
            result = automatically_import_overlay(
                root,
                scenes_dir,
                strict=strict,
                case_sensitive=case_sensitive,
            )
        except UtilityError as exc:
            return Response(
                request_id=request.request_id,
                type="result",
                data={
                    "success": False,
                    "kind": "",
                    "error": str(exc),
                    "collection_name": "",
                    "canvas_width": None,
                    "canvas_height": None,
                    "profile_name": None,
                },
            )

        data: dict[str, Any] = {
            "success": result.success,
            "kind": result.kind,
            "collection_name": result.collection_name,
        }
        if result.error:
            data["error"] = result.error
        if result.canvas_width is not None:
            data["canvas_width"] = result.canvas_width
        if result.canvas_height is not None:
            data["canvas_height"] = result.canvas_height
        if result.profile_name:
            data["profile_name"] = result.profile_name

        # Include conversion details for OBS-type imports.
        if result.conversion is not None:
            conv = result.conversion
            data["conversion"] = {
                "success": conv.success,
                "changed": conv.changed,
                "unchanged": conv.unchanged,
                "missing": list(conv.missing),
                "indexed_files": conv.indexed_files,
                "candidate_paths": conv.candidate_paths,
            }
            if conv.error:
                data["conversion"]["error"] = conv.error

        return Response(
            request_id=request.request_id,
            type="result",
            data=data,
        )

    # -- device_requirements ---------------------------------------------

    def _cmd_device_requirements(self, request: Request) -> Response:
        """List configurable device sources for an installed collection.

        The collection path is provided by Electron main (not the
        renderer).  Returns requirement IDs, names, kinds, and source IDs
        — never raw paths or arbitrary settings objects.
        """
        params = request.params
        collection_path = params.get("collection_path")

        if not isinstance(collection_path, str) or not collection_path.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "collection_path must be a non-empty string."),
            )

        try:
            collection = Path(collection_path).expanduser().resolve()
        except (OSError, ValueError):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_path", "The selected path is not valid."),
            )

        if not collection.is_file():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err(
                    "invalid_collection",
                    "The installed collection is no longer available.",
                ),
            )

        try:
            requirements = collection_device_requirements(collection)
        except UtilityError as exc:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("device_setup_failed", str(exc)),
            )

        return Response(
            request_id=request.request_id,
            type="result",
            data={
                "requirements": [
                    {
                        "key": req.key,
                        "name": req.name,
                        "source_id": req.source_id,
                        "kind": req.kind,
                    }
                    for req in requirements
                ],
                "count": len(requirements),
            },
        )

    # -- device_candidates -----------------------------------------------

    def _cmd_device_candidates(self, request: Request) -> Response:
        """List reusable local device settings.

        The OBS scenes directory is provided by Electron main (not the
        renderer).  Returns safe candidate labels and opaque candidate IDs
        — never raw paths or arbitrary settings objects.
        """
        params = request.params
        obs_scenes_directory = params.get("obs_scenes_directory")
        exclude_collection = params.get("exclude_collection")

        if not isinstance(obs_scenes_directory, str) or not obs_scenes_directory.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "obs_scenes_directory must be a non-empty string."),
            )

        try:
            scenes_dir = Path(obs_scenes_directory).expanduser().resolve()
        except (OSError, ValueError):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_path", "The selected path is not valid."),
            )

        if not scenes_dir.is_dir():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_folder", "Choose a valid OBS scenes folder."),
            )

        exclude = None
        if isinstance(exclude_collection, str) and exclude_collection.strip():
            try:
                exclude = Path(exclude_collection).expanduser().resolve()
            except (OSError, ValueError):
                exclude = None

        try:
            candidates = available_device_candidates(scenes_dir, exclude_collection=exclude)
        except UtilityError as exc:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("device_setup_failed", str(exc)),
            )

        # Build a flat list with opaque candidate IDs.  Each candidate gets
        # a unique ID that Electron main can map back to the source_id +
        # index.  The renderer receives only the ID, label, kind, and
        # source_id — never the raw settings.
        candidate_list: list[dict[str, Any]] = []
        for source_id_key, entries in sorted(candidates.items()):
            for idx, candidate in enumerate(entries):
                candidate_id = f"dev-{source_id_key}-{idx}"
                candidate_list.append({
                    "candidate_id": candidate_id,
                    "source_id": candidate.source_id,
                    "label": candidate.label,
                    "kind": candidate.kind,
                })

        return Response(
            request_id=request.request_id,
            type="result",
            data={
                "candidates": candidate_list,
                "count": len(candidate_list),
            },
        )

    # -- apply_device_choices --------------------------------------------

    def _cmd_apply_device_choices(self, request: Request) -> Response:
        """Apply selected device settings to an imported collection.

        The collection path is provided by Electron main (not the
        renderer).  The choices are opaque candidate IDs or "disable".
        Electron main maps these to the actual DeviceCandidate objects
        or "disable" before forwarding.  The backend validates and
        applies choices atomically through the existing engine.
        """
        params = request.params
        collection_path = params.get("collection_path")
        choices = params.get("choices")

        if not isinstance(collection_path, str) or not collection_path.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "collection_path must be a non-empty string."),
            )
        if not isinstance(choices, dict):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "choices must be a JSON object."),
            )

        try:
            collection = Path(collection_path).expanduser().resolve()
        except (OSError, ValueError):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_path", "The selected path is not valid."),
            )

        if not collection.is_file():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err(
                    "invalid_collection",
                    "The installed collection is no longer available.",
                ),
            )

        # The choices dict maps requirement keys to either "disable" or
        # a dict with candidate settings (already resolved by Electron
        # main from the opaque candidate IDs).  We reconstruct the
        # DeviceCandidate objects from the resolved settings.
        resolved_choices: dict[str, Any] = {}
        for key, value in choices.items():
            if value == "disable":
                resolved_choices[key] = "disable"
            elif isinstance(value, dict):
                # Reconstruct a DeviceCandidate from the resolved settings.
                resolved_choices[key] = DeviceCandidate(
                    label=value.get("label", ""),
                    source_id=value.get("source_id", ""),
                    kind=value.get("kind", ""),
                    settings=value.get("settings", {}),
                )
            else:
                return Response(
                    request_id=request.request_id,
                    type="error",
                    error=_err("invalid_params", f"Invalid choice for key {key!r}."),
                )

        try:
            error = apply_device_choices(collection, resolved_choices)
        except Exception:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("internal_error", "Internal backend error"),
            )

        if error:
            return Response(
                request_id=request.request_id,
                type="result",
                data={"success": False, "error": error},
            )

        return Response(
            request_id=request.request_id,
            type="result",
            data={"success": True},
        )

    # -- obs_running ------------------------------------------------------

    def _cmd_obs_running(self, request: Request) -> Response:
        """Check whether OBS appears to be running."""
        running = is_obs_running()
        return Response(
            request_id=request.request_id,
            type="result",
            data={"running": running},
        )

    # -- activate_collection ---------------------------------------------

    def _cmd_activate_collection(self, request: Request) -> Response:
        """Activate a collection in OBS via WebSocket.

        The collection name is provided by Electron main (not the
        renderer).  The OBS WebSocket password is accepted only for this
        one activation request, forwarded once, and never written
        anywhere.  If OBS requires a password, it must be provided in
        the request params — the backend uses it once and discards it.
        """
        params = request.params
        collection_name = params.get("collection_name")
        password = params.get("password")

        if not isinstance(collection_name, str) or not collection_name.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "collection_name must be a non-empty string."),
            )
        # Password is optional (only required if OBS requires auth).
        if password is not None and not isinstance(password, str):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "password must be a string if provided."),
            )

        try:
            client = ObsWebSocketClient(password=password if password else None)
            with client:
                client.activate_scene_collection(collection_name)
        except ObsNotRunningError as exc:
            return Response(
                request_id=request.request_id,
                type="result",
                data={"success": False, "error": str(exc)},
            )
        except ObsAuthenticationRequired as exc:
            return Response(
                request_id=request.request_id,
                type="result",
                data={"success": False, "error": str(exc)},
            )
        except ObsRequestError as exc:
            return Response(
                request_id=request.request_id,
                type="result",
                data={"success": False, "error": str(exc)},
            )
        except Exception:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("internal_error", "Internal backend error"),
            )

        return Response(
            request_id=request.request_id,
            type="result",
            data={"success": True},
        )

    # -- list_export_collections -----------------------------------------

    def _cmd_list_export_collections(self, request: Request) -> Response:
        """List OBS scene collections available for export.

        The OBS scenes directory is provided by Electron main (not the
        renderer).  Returns safe collection labels — never raw paths.
        """
        params = request.params
        obs_scenes_directory = params.get("obs_scenes_directory")

        if not isinstance(obs_scenes_directory, str) or not obs_scenes_directory.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "obs_scenes_directory must be a non-empty string."),
            )

        try:
            scenes_dir = Path(obs_scenes_directory).expanduser().resolve()
        except (OSError, ValueError):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_path", "The selected path is not valid."),
            )

        if not scenes_dir.is_dir():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_folder", "Choose a valid OBS scenes folder."),
            )

        try:
            collections = list_obs_scene_collections(scenes_dir)
        except UtilityError as exc:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("list_failed", str(exc)),
            )

        # Return safe labels only — the path stays with Electron main.
        collection_list: list[dict[str, Any]] = []
        for label, path in sorted(collections.items()):
            collection_list.append({
                "label": label,
                "path": str(path),  # sent to Electron main only
            })

        return Response(
            request_id=request.request_id,
            type="result",
            data={
                "collections": collection_list,
                "count": len(collection_list),
            },
        )

    # -- build_export_plan -----------------------------------------------

    def _cmd_build_export_plan(self, request: Request) -> Response:
        """Build a frozen, backend-held export plan.

        The collection path and destination are provided by Electron main
        (not the renderer).  Creates an opaque plan ID with a real TTL.
        The renderer receives only a sanitized inventory view.
        """
        params = request.params
        collection_path = params.get("collection_path")
        destination = params.get("destination")
        compressed = params.get("compressed", False)

        if not isinstance(collection_path, str) or not collection_path.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "collection_path must be a non-empty string."),
            )
        if not isinstance(destination, str) or not destination.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "destination must be a non-empty string."),
            )
        if not isinstance(compressed, bool):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "compressed must be a boolean."),
            )

        try:
            coll_path = Path(collection_path).expanduser().resolve()
            dest_path = Path(destination).expanduser().resolve()
        except (OSError, ValueError):
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_path", "The selected path is not valid."),
            )

        if not coll_path.is_file():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_collection", "The selected collection is not available."),
            )

        if not dest_path.is_dir():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_destination", "Choose a valid export destination folder."),
            )

        try:
            plan = build_export_plan(coll_path, dest_path, compressed=compressed)
        except UtilityError as exc:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("plan_failed", str(exc)),
            )

        # Create an opaque plan ID with a real TTL.
        _prune_export_plans()
        plan_id = str(uuid.uuid4())
        _export_plans[plan_id] = _ExportPlanRecord(
            plan_id=plan_id,
            plan=plan,
            created_at=time.monotonic(),
            executed=False,
        )

        # Build a sanitized inventory for the renderer.
        inventory = export_inventory_from_plan(plan)
        dep_report = inventory.dependency_report or DependencyReport()
        sanitized: dict[str, Any] = {
            "plan_id": plan_id,
            "collection_label": plan.collection_name,
            "collection_stem": plan.collection_stem,
            "compressed": plan.compressed,
            "source_references": inventory.source_references,
            "total_bytes": inventory.total_bytes,
            "scene_count": inventory.scene_count,
            "source_count": inventory.source_count,
            "browser_files": inventory.browser_files,
            "canvas_width": inventory.canvas_width,
            "canvas_height": inventory.canvas_height,
            "missing_references": list(inventory.missing_references),
            "dependency_report": {
                "fonts": list(dep_report.fonts),
                "devices": list(dep_report.devices),
                "remote_resources": [
                    {"host": r["host"], "sensitive": r["sensitive"]}
                    for r in dep_report.remote_resources
                ],
                "plugin_source_ids": list(dep_report.plugin_source_ids),
                "plugin_filter_ids": list(dep_report.plugin_filter_ids),
            },
            "items": [
                {
                    "category": item.category,
                    "size": item.size,
                    "source_name": item.source_name,
                }
                for item in inventory.items
            ],
        }

        return Response(
            request_id=request.request_id,
            type="result",
            data=sanitized,
        )

    # -- export_inventory -------------------------------------------------

    def _cmd_export_inventory(self, request: Request) -> Response:
        """Return a sanitized inventory view for an existing plan.

        The plan ID is opaque.  Electron main forwards it from the
        renderer.  Expired or unknown plan IDs fail safely.
        """
        params = request.params
        plan_id = params.get("plan_id")

        if not isinstance(plan_id, str) or not plan_id.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "plan_id must be a non-empty string."),
            )

        _prune_export_plans()
        record = _export_plans.get(plan_id)
        if record is None:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err(
                    "unknown_plan",
                    "This export plan is no longer available. Build a new inventory.",
                ),
            )

        if time.monotonic() - record.created_at > _EXPORT_PLAN_TTL_SECONDS:
            del _export_plans[plan_id]
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err(
                    "expired_plan",
                    "This export plan has expired. Build a new inventory.",
                ),
            )

        inventory = export_inventory_from_plan(record.plan)
        sanitized: dict[str, Any] = {
            "plan_id": plan_id,
            "collection_label": record.plan.collection_name,
            "collection_stem": record.plan.collection_stem,
            "compressed": record.plan.compressed,
            "source_references": inventory.source_references,
            "total_bytes": inventory.total_bytes,
            "scene_count": inventory.scene_count,
            "source_count": inventory.source_count,
            "browser_files": inventory.browser_files,
            "canvas_width": inventory.canvas_width,
            "canvas_height": inventory.canvas_height,
            "missing_references": list(inventory.missing_references),
            "items": [
                {
                    "category": item.category,
                    "size": item.size,
                    "source_name": item.source_name,
                }
                for item in inventory.items
            ],
        }

        return Response(
            request_id=request.request_id,
            type="result",
            data=sanitized,
        )

    # -- confirm_export ---------------------------------------------------

    def _cmd_confirm_export(self, request: Request) -> Response:
        """Execute a frozen export plan by opaque ID.

        The plan ID is opaque.  Electron main forwards it from the
        renderer.  The backend revalidates and executes the exact frozen
        plan.  Unknown, expired, already-executed, or altered plans fail
        safely.  Successful plans become idempotent.
        """
        params = request.params
        plan_id = params.get("plan_id")

        if not isinstance(plan_id, str) or not plan_id.strip():
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("invalid_params", "plan_id must be a non-empty string."),
            )

        _prune_export_plans()
        record = _export_plans.get(plan_id)
        if record is None:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err(
                    "unknown_plan",
                    "This export plan is no longer available. Build a new inventory.",
                ),
            )

        if time.monotonic() - record.created_at > _EXPORT_PLAN_TTL_SECONDS:
            del _export_plans[plan_id]
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err(
                    "expired_plan",
                    "This export plan has expired. Build a new inventory.",
                ),
            )

        if record.executed:
            return Response(
                request_id=request.request_id,
                type="result",
                data={
                    "success": True,
                    "already_executed": True,
                    "message": "This export has already been completed.",
                },
            )

        try:
            result = export_scene_collection(
                record.plan.collection_path,
                record.plan.destination,
                compressed=record.plan.compressed,
                plan=record.plan,
            )
        except Exception:
            return Response(
                request_id=request.request_id,
                type="error",
                error=_err("internal_error", "Internal backend error"),
            )

        record.executed = True

        data: dict[str, Any] = {
            "success": result.success,
            "copied_files": result.copied_files,
            "uncompressed_bytes": result.uncompressed_bytes,
            "source_references": result.source_references,
        }

        if result.error:
            data["error"] = result.error

        if result.skipped_references:
            data["skipped_references"] = list(result.skipped_references)

        if result.verification is not None:
            data["verification"] = {
                "ok": result.verification.ok,
                "errors": list(result.verification.errors),
            }

        # Safe output label — never expose the raw destination path.
        if result.output_path is not None:
            data["output_label"] = result.output_path.name

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
