"""Export OBS scene collections as truly portable, self-verifying overlay packages.

Produces either a folder or a verified ZIP archive containing:

    <Name>-Portable/
    ├── collection/     Portable collection JSON with collection-relative paths
    ├── assets/         images, videos, audio, other
    ├── browser/        Local browser-overlay projects
    ├── manifest.json   Versioned package metadata and SHA-256 hashes
    └── Import Instructions.txt
"""

from __future__ import annotations

import configparser
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from .constants import __version__
from .core import (
    atomic_write_json,
    is_obs_scene_collection_data,
    load_json,
    next_obs_collection_path,
)
from .models import PathReference, UtilityError
from .paths import looks_absolute_local_path, normalized_output_path


IMAGE_EXTENSIONS = frozenset(
    {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp"}
)
VIDEO_EXTENSIONS = frozenset(
    {".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm"}
)
AUDIO_EXTENSIONS = frozenset(
    {".aac", ".aif", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".wma"}
)
ALREADY_COMPRESSED_EXTENSIONS = frozenset(
    {".zip", ".7z", ".rar", ".gz", ".bz2", ".xz", ".png", ".jpg", ".jpeg",
     ".gif", ".webp", ".mp3", ".aac", ".ogg", ".opus", ".flac",
     ".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".m4v", ".mpg", ".mpeg", ".ts",
     ".wav", ".wma", ".aif", ".aiff"}
)

MAX_BROWSER_FILES = 10_000
MAX_BROWSER_BYTES = 2 * 1024 * 1024 * 1024
INVALID_WINDOWS_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)

BUILTIN_SOURCE_IDS = frozenset({
    "scene", "group",
    "image_source", "color_source", "color_source_v2", "color_source_v3",
    "slideshow", "browser_source",
    "ffmpeg_source", "vlc_source", "media_source",
    "text_gdiplus", "text_ft2_source",
    "monitor_capture", "window_capture", "game_capture",
    "dshow_input", "wasapi_input_capture", "wasapi_output_capture",
    "coreaudio_input_capture", "coreaudio_output_capture",
    "pulse_input_capture", "pulse_output_capture",
    "alsa_input_capture",
    "spout_capture", "ndi_source",
})
BUILTIN_FILTER_IDS = frozenset({
    "color_filter", "color_key_filter", "chroma_key_filter",
    "crop_filter", "gpu_delay", "scroll_filter",
    "sharpness_filter", "mask_filter", "mask_filter_v2",
    "scale_filter", "luma_key_filter",
    "noise_suppress_filter", "noise_gate_filter", "compressor_filter",
    "expand_filter", "limiter_filter", "gain_filter",
    "invert_polarity_filter", "upward_compressor_filter",
    "hdr_tone_mapping_filter",
    "obs_stinger_transition",
})

REMOTE_URL_RE = re.compile(r'^(https?|wss?)://', re.IGNORECASE)
SENSITIVE_URL_RE = re.compile(r'[?&](token|key|secret|password|auth|api_key|access_token)', re.IGNORECASE)

MANIFEST_SCHEMA = "obs-overlay-portable-package"
MANIFEST_VERSION = 1
MISSING_PLACEHOLDER_PREFIX = "../missing/"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlannedFile:
    source_path: Path
    package_path: str
    category: str
    size: int
    source_names: tuple[str, ...]
    digest: str = ""


@dataclass
class DependencyReport:
    fonts: list[str] = field(default_factory=list)
    devices: list[dict[str, str]] = field(default_factory=list)
    remote_resources: list[dict[str, str]] = field(default_factory=list)
    has_sensitive_urls: bool = False
    plugin_source_ids: list[dict[str, str]] = field(default_factory=list)
    plugin_filter_ids: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ExportPlan:
    collection_path: Path
    collection_digest: str
    collection_name: str
    collection_stem: str
    destination: Path
    output_path: Path
    compressed: bool
    portable_collection: dict[str, Any]
    files: list[PlannedFile]
    missing_references: list[dict[str, str]]
    dependency_report: DependencyReport
    scene_count: int = 0
    source_count: int = 0
    canvas_width: int | None = None
    canvas_height: int | None = None
    total_bytes: int = 0
    browser_projects: list[str] = field(default_factory=list)
    preview_files: list[str] = field(default_factory=list)


@dataclass
class PackageVerification:
    ok: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class ExportResult:
    success: bool = False
    package_path: Path | None = None
    collection_path: Path | None = None
    output_path: Path | None = None
    archive_path: Path | None = None
    compressed: bool = False
    archive_bytes: int = 0
    uncompressed_bytes: int = 0
    copied_files: int = 0
    source_references: int = 0
    skipped_references: list[str] = field(default_factory=list)
    verification: PackageVerification | None = None
    error: str | None = None


@dataclass
class ExportInventory:
    success: bool = False
    collection_path: Path | None = None
    destination: Path | None = None
    package_path: Path | None = None
    compressed: bool = False
    source_references: int = 0
    total_bytes: int = 0
    scene_count: int = 0
    source_count: int = 0
    browser_files: int = 0
    items: list[ExportInventoryItem] = field(default_factory=list)
    missing_references: list[str] = field(default_factory=list)
    dependency_report: DependencyReport | None = None
    canvas_width: int | None = None
    canvas_height: int | None = None
    error: str | None = None
    plan: ExportPlan | None = None


@dataclass(frozen=True)
class ExportInventoryItem:
    path: Path
    category: str
    size: int
    source_name: str
    package_path: str = ""


# ---------------------------------------------------------------------------
# Collection discovery
# ---------------------------------------------------------------------------

def list_obs_scene_collections(obs_scenes_directory: Path) -> dict[str, Path]:
    directory = obs_scenes_directory.expanduser().resolve()
    if not directory.is_dir():
        return {}
    collections: dict[str, Path] = {}
    for path in sorted(directory.glob("*.json"), key=lambda item: item.name.casefold()):
        try:
            data = load_json(path)
        except UtilityError:
            continue
        if not is_obs_scene_collection_data(data):
            continue
        name = data.get("name") if isinstance(data.get("name"), str) else path.stem
        label = name
        number = 2
        while label in collections:
            label = f"{name} ({number})"
            number += 1
        collections[label] = path
    return collections


def active_obs_scene_collection(obs_scenes_directory: Path) -> Path | None:
    scenes_directory = obs_scenes_directory.expanduser().resolve()
    user_ini = scenes_directory.parent.parent / "user.ini"
    if not user_ini.is_file():
        return None
    config = configparser.RawConfigParser(interpolation=None)
    try:
        config.read(user_ini, encoding="utf-8")
        filename = config.get("Basic", "SceneCollectionFile", fallback="").strip()
    except (configparser.Error, OSError, UnicodeError):
        return None
    if (
        not filename
        or Path(filename).name != filename
        or Path(filename).suffix.casefold() != ".json"
    ):
        return None
    candidate = (scenes_directory / filename).resolve()
    try:
        candidate.relative_to(scenes_directory)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


# ---------------------------------------------------------------------------
# Path scanning helpers
# ---------------------------------------------------------------------------

def _iter_local_path_references(
    value: Any, *, source_name: str = "Scene collection"
) -> Iterator[PathReference]:
    if isinstance(value, dict):
        current_source = (
            value.get("name") if isinstance(value.get("name"), str) else source_name
        )
        for key, child in value.items():
            if isinstance(child, str) and looks_absolute_local_path(child):
                yield PathReference(value, key, key, child, current_source)
            elif isinstance(child, (dict, list)):
                yield from _iter_local_path_references(
                    child, source_name=current_source
                )
    elif isinstance(value, list):
        for position, child in enumerate(value):
            if isinstance(child, str) and looks_absolute_local_path(child):
                yield PathReference(
                    value, position, position, child, source_name
                )
            elif isinstance(child, (dict, list)):
                yield from _iter_local_path_references(child, source_name=source_name)


def _resource_folder(path: Path) -> str:
    extension = path.suffix.casefold()
    if extension in IMAGE_EXTENSIONS:
        return "images"
    if extension in VIDEO_EXTENSIONS:
        return "videos"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    return "other"


def _category_for(path: Path) -> str:
    extension = path.suffix.casefold()
    if extension in IMAGE_EXTENSIONS:
        return "images"
    if extension in VIDEO_EXTENSIONS:
        return "videos"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    return "other"


# ---------------------------------------------------------------------------
# Portable path contract
# ---------------------------------------------------------------------------

def portable_package_path(category: str, filename: str) -> str:
    return f"../assets/{category}/{filename}"


def portable_browser_path(project_dir_name: str, relative: str) -> str:
    rel = relative.replace("\\", "/")
    return f"../browser/{project_dir_name}/{rel}"


def is_safe_portable_path(path: str) -> bool:
    """True for a relative portable package path that does not escape root.

    Accepts paths like ``../assets/images/bg.png`` (valid portable reference)
    but rejects ``assets//images/bg.png`` (empty segment), ``assets/../../outside``
    (escapes root), absolute paths, UNC paths, and drive-qualified paths.
    """
    if not path or path.startswith("\\\\"):
        return False
    if len(path) >= 2 and path[1] == ":":
        return False
    normalized = path.replace("\\", "/")
    if normalized.startswith("/"):
        return False
    depth = 0
    for part in normalized.split("/"):
        if not part:
            return False
        if part == "..":
            depth -= 1
        elif part != ".":
            depth += 1
    return depth >= 0


def _sha256_chunked(path: Path, *, chunk_size: int = 1 << 20) -> str:
    """Hash a file in fixed-size chunks so large media never loads fully into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_chunked_zip(zf: zipfile.ZipFile, name: str, *, chunk_size: int = 1 << 20) -> str:
    """Hash a ZIP member in chunks without reading the whole entry into memory."""
    digest = hashlib.sha256()
    with zf.open(name) as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_file_path_is_safe(raw_path: Any) -> bool:
    """True only for a relative, contained package path with no traversal or
    dot-segments.

    Every ``..`` and ``.`` segment is rejected so that aliases such as
    ``assets/../collection/C.json`` and ``collection/C.json`` cannot both
    pass validation and collide after normalization.
    """
    if not isinstance(raw_path, str) or not raw_path:
        return False
    normalized = raw_path.replace("\\", "/")
    if normalized.startswith("/"):
        return False
    if len(normalized) >= 2 and normalized[1] == ":":
        return False
    if normalized.startswith("//"):
        return False
    if normalized.startswith("\\\\"):
        return False
    depth = 0
    for part in normalized.split("/"):
        if not part:
            return False
        if part == ".." or part == ".":
            return False
        depth += 1
    return depth >= 0


def _allocate_browser_project_dir(folder_name: str, used: set[str]) -> str:
    """Allocate a deterministic, unique browser project directory name.

    Distinct source roots that share a folder name receive ``overlay`` then
    ``overlay 2`` and so on, so their packaged content never collides.
    """
    base = _sanitise_name(folder_name) or "browser overlay"
    candidate = base
    number = 2
    while candidate.casefold() in {entry.casefold() for entry in used}:
        candidate = f"{base} {number}"
        number += 1
    used.add(candidate)
    return candidate


def _reject_duplicate_package_paths(planned: list[PlannedFile]) -> None:
    """Defensively reject two planned files that normalize to the same package path."""
    seen: set[str] = set()
    for pf in planned:
        normalized = pf.package_path.casefold()
        if normalized in seen:
            raise UtilityError(
                f"Two source files would write to the same package path: {pf.package_path}"
            )
        seen.add(normalized)


# ---------------------------------------------------------------------------
# Dependency analysis
# ---------------------------------------------------------------------------

def _detect_device_kind(source_id: str, settings: Any) -> str | None:
    sid = source_id.casefold()
    if sid in {"av_capture_input", "dshow_input", "decklink-input", "v4l2_input"}:
        return "Camera or capture device"
    if sid in {
        "wasapi_input_capture", "wasapi_output_capture",
        "coreaudio_input_capture", "coreaudio_output_capture",
        "pulse_input_capture", "pulse_output_capture",
        "jack_input_capture",
    }:
        return "Audio device"
    if sid in {
        "monitor_capture", "display_capture", "window_capture",
        "game_capture", "macos_screen_capture", "xshm_input",
    }:
        return "Display, window, or game capture"
    if isinstance(settings, dict):
        device_keys = {
            "audio_device_id", "capture_window", "device", "device_hash",
            "device_id", "device_name", "display", "display_uuid",
            "input_device_id", "monitor", "monitor_id",
            "output_device_id", "screen", "screen_id",
            "video_device_id", "window", "window_id",
        }
        if any(key in settings for key in device_keys):
            return "Other device source"
    return None


def _analyse_dependencies(data: dict[str, Any]) -> DependencyReport:
    report = DependencyReport()
    seen_fonts: set[str] = set()
    seen_devices: set[tuple[str, str, str]] = set()
    seen_remote: set[tuple[str, str, str]] = set()
    seen_plugin_src: set[tuple[str, str]] = set()
    seen_plugin_flt: set[tuple[str, str]] = set()
    source_ids_seen: set[str] = set()
    filter_ids_seen: set[str] = set()

    def _collect_ids(value: Any, *, in_sources: bool = False, in_filters: bool = False) -> None:
        if isinstance(value, dict):
            sid = value.get("id")
            if isinstance(sid, str):
                if in_sources and not in_filters:
                    source_ids_seen.add(sid)
                elif in_filters:
                    filter_ids_seen.add(sid)

            name = value.get("name", "")
            if not isinstance(name, str):
                name = ""

            settings = value.get("settings")

            kind = _detect_device_kind(str(sid) if isinstance(sid, str) else "", settings)
            if kind:
                seen_devices.add((str(name), str(sid) if isinstance(sid, str) else "", kind))

            for key, child in value.items():
                if key == "font" and isinstance(child, dict) and isinstance(child.get("face"), str):
                    seen_fonts.add(child["face"])
                elif key == "font" and isinstance(child, str):
                    seen_fonts.add(child)

                if isinstance(child, str) and REMOTE_URL_RE.match(child):
                    sensitive = bool(SENSITIVE_URL_RE.search(child))
                    host = ""
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(child)
                        host = parsed.netloc
                    except Exception:
                        pass
                    seen_remote.add((
                        child.split("?")[0] if sensitive else child,
                        host,
                        "yes" if sensitive else "no",
                    ))

                next_sources = in_sources
                next_filters = in_filters
                if key == "sources":
                    next_sources = True
                    next_filters = False
                if key == "filters":
                    next_sources = False
                    next_filters = True

                if isinstance(child, (dict, list)):
                    _collect_ids(child, in_sources=next_sources, in_filters=next_filters)

            if isinstance(sid, str) and sid not in BUILTIN_SOURCE_IDS:
                seen_plugin_src.add((sid, str(name)))
            if isinstance(sid, str) and sid not in BUILTIN_FILTER_IDS and in_filters:
                seen_plugin_flt.add((sid, str(name)))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    _collect_ids(item, in_sources=in_sources, in_filters=in_filters)

    _collect_ids(data, in_sources=True, in_filters=False)

    report.fonts = sorted(seen_fonts)
    for item in sorted(seen_devices):
        report.devices.append({
            "source_name": item[0],
            "source_id": item[1],
            "kind": item[2],
        })
    for item in sorted(seen_remote):
        report.remote_resources.append({
            "url": item[0],
            "host": item[1],
            "sensitive": item[2],
        })
    report.has_sensitive_urls = any(r["sensitive"] == "yes" for r in report.remote_resources)
    for item in sorted(seen_plugin_src):
        report.plugin_source_ids.append({"id": item[0], "name": item[1]})
    for item in sorted(seen_plugin_flt):
        report.plugin_filter_ids.append({"id": item[0], "name": item[1]})
    return report


# ---------------------------------------------------------------------------
# Scene and source counting
# ---------------------------------------------------------------------------

def _count_scenes_and_sources(data: dict[str, Any]) -> tuple[int, int, int | None, int | None]:
    scene_order = data.get("scene_order", [])
    scene_count = len(scene_order) if isinstance(scene_order, list) else 0
    sources = data.get("sources", [])
    non_scene = 0
    if isinstance(sources, list):
        for src in sources:
            if isinstance(src, dict) and src.get("id") != "scene":
                non_scene += 1
    resolution = data.get("resolution")
    canvas_w = None
    canvas_h = None
    if isinstance(resolution, dict):
        x = resolution.get("x")
        y = resolution.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            canvas_w = int(x)
            canvas_h = int(y)
    return scene_count, non_scene, canvas_w, canvas_h


# ---------------------------------------------------------------------------
# Package naming (deterministic, non-overwriting)
# ---------------------------------------------------------------------------

def _sanitise_name(name: str) -> str:
    cleaned = INVALID_WINDOWS_NAME_RE.sub("_", " ".join(name.split())).strip().rstrip(". ")
    cleaned = cleaned or "OBS Overlay"
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def _next_package_path(destination: Path, collection_name: str, compressed: bool) -> Path:
    base = _sanitise_name(collection_name) + "-Portable"
    suffix = ".zip" if compressed else ""
    candidate = destination / f"{base}{suffix}"
    number = 1
    while candidate.exists():
        candidate = destination / f"{base} {number}{suffix}"
        number += 1
    return candidate


# ---------------------------------------------------------------------------
# Browser overlay helpers
# ---------------------------------------------------------------------------

def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _is_link_or_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _unsafe_browser_roots() -> set[Path]:
    home = Path.home().resolve()
    roots = {
        Path(home.anchor).resolve(),
        home,
        home.parent,
        *(home / name for name in ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos")),
    }
    for variable in ("APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "SYSTEMROOT", "USERPROFILE"):
        value = os.environ.get(variable)
        if value:
            roots.add(Path(value).expanduser().resolve())
    return roots


def _browser_inventory(source_root: Path, export_destination: Path) -> list[Path]:
    if source_root in _unsafe_browser_roots():
        raise UtilityError(
            "The browser source is stored in a broad personal or system folder. "
            "Move it into a dedicated overlay project folder before exporting."
        )
    if _is_within(export_destination, source_root):
        raise UtilityError(
            "The export destination cannot be inside the browser overlay folder."
        )
    inventory: list[Path] = []
    total_bytes = 0
    for current, directories, files in os.walk(source_root, followlinks=False):
        directories[:] = [
            name for name in directories
            if not _is_link_or_reparse_point(Path(current, name))
        ]
        for filename in files:
            source = Path(current, filename)
            if _is_link_or_reparse_point(source):
                continue
            total_bytes += source.stat().st_size
            inventory.append(source)
            if len(inventory) > MAX_BROWSER_FILES:
                raise UtilityError(f"The browser overlay contains more than {MAX_BROWSER_FILES:,} files.")
            if total_bytes > MAX_BROWSER_BYTES:
                raise UtilityError("The browser overlay is larger than the safe 2 GB export limit.")
    return inventory


def _next_browser_directory(parent: Path, source_directory: Path) -> Path:
    base_name = " ".join(source_directory.name.split()).strip() or "browser overlay"
    candidate = parent / base_name
    number = 2
    while candidate.exists():
        candidate = parent / f"{base_name} {number}"
        number += 1
    return candidate


# ---------------------------------------------------------------------------
# Collision-safe filename for asset packaging
# ---------------------------------------------------------------------------

def _unique_asset_filename(proposed: str, used_names: set[str]) -> str:
    """Return *proposed* or a deterministic unique variant within *used_names*."""
    lower_proposed = proposed.casefold()
    if lower_proposed not in {n.casefold() for n in used_names}:
        used_names.add(proposed)
        return proposed
    base, ext = os.path.splitext(proposed)
    number = 2
    while True:
        candidate = f"{base} {number}{ext}"
        if candidate.casefold() not in {n.casefold() for n in used_names}:
            used_names.add(candidate)
            return candidate
        number += 1


# ---------------------------------------------------------------------------
# build_export_plan: frozen inventory + plan
# ---------------------------------------------------------------------------

def build_export_plan(
    collection_path: Path,
    destination: Path,
    compressed: bool = True,
) -> ExportPlan:
    collection_path = collection_path.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not collection_path.is_file():
        raise UtilityError("The selected OBS scene collection no longer exists.")
    if not destination.is_dir():
        raise UtilityError("Choose a valid export destination folder.")

    original = load_json(collection_path)
    if not is_obs_scene_collection_data(original):
        raise UtilityError("The selected JSON is not a recognized OBS scene collection.")

    collection_name = (
        original.get("name") if isinstance(original.get("name"), str)
        else collection_path.stem
    )
    collection_stem = collection_path.stem
    collection_digest = hashlib.sha256(
        json.dumps(original, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()

    output_path = _next_package_path(destination, collection_name, compressed)
    portable = copy.deepcopy(original)
    dep_report = _analyse_dependencies(portable)

    scene_count, source_count, canvas_w, canvas_h = _count_scenes_and_sources(portable)

    planned: list[PlannedFile] = []
    missing: list[dict[str, str]] = []
    seen_sources: dict[Path, set[str]] = {}
    used_asset_names: dict[str, set[str]] = {}
    browser_roots_scanned: set[Path] = set()
    browser_project_dirs: list[str] = []
    browser_project_dirs_used: set[str] = set()

    for reference in _iter_local_path_references(portable):
        source = Path(normalized_output_path(reference.value)).resolve()
        if not source.is_file():
            missing.append({
                "source": reference.source_name,
                "setting": str(reference.detection_key),
                "basename": source.name,
                "path": str(source),
                "reason": "File not found",
            })
            continue

        if source.suffix.casefold() in {".htm", ".html"}:
            source_root = source.parent.resolve()
            if source_root not in browser_roots_scanned:
                browser_roots_scanned.add(source_root)
                project_dir = _allocate_browser_project_dir(source_root.name, browser_project_dirs_used)
                for browser_file in _browser_inventory(source_root, destination):
                    resolved = browser_file.resolve()
                    rel = str(browser_file.relative_to(source_root)).replace("\\", "/")
                    pkg = f"../browser/{project_dir}/{rel}"
                    if resolved not in seen_sources:
                        seen_sources[resolved] = {reference.source_name}
                        planned.append(PlannedFile(
                            source_path=resolved,
                            package_path=pkg,
                            category="browser",
                            size=browser_file.stat().st_size,
                            source_names=(reference.source_name,),
                            digest=_sha256_chunked(resolved),
                        ))
                    else:
                        seen_sources[resolved].add(reference.source_name)
                if project_dir not in browser_project_dirs:
                    browser_project_dirs.append(project_dir)
            continue

        cat = _category_for(source)
        if source not in seen_sources:
            seen_sources[source] = {reference.source_name}
            used_asset_names.setdefault(cat, set())
            filename = _unique_asset_filename(source.name, used_asset_names[cat])
            pkg = portable_package_path(cat, filename)
            planned.append(PlannedFile(
                source_path=source,
                package_path=pkg,
                category=cat,
                size=source.stat().st_size,
                source_names=(reference.source_name,),
                digest=_sha256_chunked(source),
            ))
        else:
            seen_sources[source].add(reference.source_name)

    # Reject two planned files that would resolve to the same package path.
    _reject_duplicate_package_paths(planned)

    planned = [
        replace(pf, source_names=tuple(sorted(seen_sources.get(pf.source_path, {pf.source_names[0]}))))
        for pf in planned
    ]
    planned = sorted(planned, key=lambda p: (p.category, p.package_path))
    total_bytes = sum(pf.size for pf in planned)

    return ExportPlan(
        collection_path=collection_path,
        collection_digest=collection_digest,
        collection_name=collection_name,
        collection_stem=collection_stem,
        destination=destination,
        output_path=output_path,
        compressed=compressed,
        portable_collection=portable,
        files=planned,
        missing_references=missing,
        dependency_report=dep_report,
        scene_count=scene_count,
        source_count=source_count,
        canvas_width=canvas_w,
        canvas_height=canvas_h,
        total_bytes=total_bytes,
        browser_projects=browser_project_dirs,
    )


# ---------------------------------------------------------------------------
# export_inventory_from_plan: read-only view of a frozen plan
# ---------------------------------------------------------------------------

def export_inventory_from_plan(plan: ExportPlan) -> ExportInventory:
    """Build an ExportInventory read-only view from a frozen ExportPlan."""
    inventory = ExportInventory()
    inventory.success = True
    inventory.collection_path = plan.collection_path
    inventory.destination = plan.destination
    inventory.package_path = plan.output_path
    inventory.compressed = plan.compressed
    inventory.source_references = len(plan.files) + len(plan.missing_references)
    inventory.total_bytes = plan.total_bytes
    inventory.scene_count = plan.scene_count
    inventory.source_count = plan.source_count
    inventory.browser_files = sum(1 for pf in plan.files if pf.category == "browser")
    inventory.canvas_width = plan.canvas_width
    inventory.canvas_height = plan.canvas_height
    inventory.items = [
        ExportInventoryItem(
            path=pf.source_path,
            category=pf.category,
            size=pf.size,
            source_name=", ".join(pf.source_names),
            package_path=pf.package_path,
        )
        for pf in plan.files
    ]
    inventory.missing_references = [
        f"{m['source']}: {m.get('basename', '')}" for m in plan.missing_references
    ]
    inventory.dependency_report = plan.dependency_report
    inventory.plan = plan
    return inventory


# ---------------------------------------------------------------------------
# build_export_inventory (compatibility wrapper)
# ---------------------------------------------------------------------------

def build_export_inventory(
    collection_path: Path,
    destination: Path,
) -> ExportInventory:
    """Build a folder-mode inventory. Prefer ``export_inventory_from_plan`` after ``build_export_plan``."""
    result = ExportInventory()
    try:
        plan = build_export_plan(collection_path, destination, compressed=False)
        result = export_inventory_from_plan(plan)
    except (OSError, UtilityError) as exc:
        result.error = str(exc) if isinstance(exc, UtilityError) else f"Could not inspect the scene collection for export: {exc}"
    return result


# ---------------------------------------------------------------------------
# manifest.json generation
# ---------------------------------------------------------------------------

def _sanitise_missing_reference(original_path: str) -> str:
    basename = os.path.basename(original_path.replace("\\", "/"))
    safe = INVALID_WINDOWS_NAME_RE.sub("_", basename).strip().rstrip(". ")
    safe = safe or "unresolved"
    return f"{MISSING_PLACEHOLDER_PREFIX}{safe}"


def _build_manifest(plan: ExportPlan, package_root_name: str) -> dict[str, Any]:
    files = []
    for pf in plan.files:
        files.append({
            "path": pf.package_path.replace("../", ""),
            "category": pf.category,
            "size": pf.size,
            "sha256": pf.digest,
            "used_by": sorted(pf.source_names),
        })

    return {
        "schema": MANIFEST_SCHEMA,
        "schema_version": MANIFEST_VERSION,
        "package_id": str(uuid.uuid4()),
        "name": plan.collection_name,
        "package_root": package_root_name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "created_by": {
            "application": "OBS Overlay Import Utility",
            "version": __version__,
        },
        "collection": {
            "name": plan.collection_name,
            "path": f"collection/{plan.collection_stem}.json",
            "path_mode": "collection-relative",
            "scene_count": plan.scene_count,
            "source_count": plan.source_count,
            "canvas_width": plan.canvas_width,
            "canvas_height": plan.canvas_height,
        },
        "files": files,
        "browser_projects": plan.browser_projects,
        "requirements": {
            "fonts": plan.dependency_report.fonts,
            "devices": plan.dependency_report.devices,
            "remote_resources": [
                {"host": r["host"], "sensitive": r["sensitive"]}
                for r in plan.dependency_report.remote_resources
            ],
            "plugin_or_unknown_source_ids": plan.dependency_report.plugin_source_ids,
            "plugin_or_unknown_filter_ids": plan.dependency_report.plugin_filter_ids,
        },
        "missing_resources": [
            {
                "setting": m["setting"],
                "basename": m["basename"],
                "reason": m["reason"],
                "portable_placeholder": _sanitise_missing_reference(m["path"]),
            }
            for m in plan.missing_references
        ],
        "previews": plan.preview_files,
    }


def _build_instructions(plan: ExportPlan) -> str:
    lines = [
        "OBS Overlay Import Utility \u2014 Portable Package",
        "=" * 50,
        "",
        "How to use this package:",
        "",
        "1. If this is a ZIP file, extract it completely before proceeding.",
        "2. Keep the extracted folder together \u2014 do not move individual files.",
        "3. Open OBS Overlay Import Utility.",
        "4. Select Automatic Scene Collection.",
        "5. Choose the extracted package folder.",
        "6. Review missing plugins, fonts, devices, and remote services below.",
        "7. Complete the device setup wizard when prompted.",
        "8. Open OBS and verify each scene before going live.",
        "",
        "Requirements:",
    ]
    if plan.dependency_report.plugin_source_ids:
        lines.append("OBS Plugins (source types):")
        for p in plan.dependency_report.plugin_source_ids:
            lines.append(f"  - {p['name']} ({p['id']})")
    if plan.dependency_report.plugin_filter_ids:
        lines.append("OBS Plugins (filter types):")
        for p in plan.dependency_report.plugin_filter_ids:
            lines.append(f"  - {p['name']} ({p['id']})")
    if plan.dependency_report.fonts:
        lines.append("Fonts:")
        for f in plan.dependency_report.fonts:
            lines.append(f"  - {f}")
    if plan.dependency_report.devices:
        lines.append("Devices (must be re-selected after import):")
        for d in plan.dependency_report.devices:
            lines.append(f"  - {d['source_name']} ({d['source_id']}) [{d.get('kind', '')}]")
    if plan.dependency_report.remote_resources:
        lines.append("Remote resources (require internet):")
        for r in plan.dependency_report.remote_resources:
            lines.append(f"  - {r['host']}")
    if plan.missing_references:
        lines.append("Missing files (must be resolved manually):")
        for m in plan.missing_references:
            lines.append(f"  - {m['basename']} ({m['setting']})")
    lines.extend([
        "",
        "Note: Plugin binaries, fonts, devices, credentials, and remote services",
        "are NOT included in this package. Install them separately.",
    ])
    return "\r\n".join(lines)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _verify_folder_package(package_path: Path, plan: ExportPlan, package_root_name: str) -> PackageVerification:
    errors: list[str] = []
    manifest_path = package_path / "manifest.json"
    collection_path = package_path / "collection" / f"{plan.collection_stem}.json"

    if not manifest_path.is_file():
        errors.append("manifest.json missing")
        return PackageVerification(ok=False, errors=errors)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != MANIFEST_SCHEMA:
            errors.append(f"Unknown manifest schema: {manifest.get('schema')}")
        if manifest.get("schema_version") != MANIFEST_VERSION:
            errors.append(f"Unsupported manifest version: {manifest.get('schema_version')}")
        for f in manifest.get("files", []):
            fp = package_path / f["path"]
            if not fp.is_file():
                errors.append(f"Manifest file missing: {f['path']}")
            else:
                actual_size = fp.stat().st_size
                if actual_size != f["size"]:
                    errors.append(f"Size mismatch: {f['path']} (expected {f['size']}, got {actual_size})")
                actual_sha = _sha256_chunked(fp)
                if actual_sha != f["sha256"]:
                    errors.append(f"SHA-256 mismatch: {f['path']}")
        missing_declared = {m.get("basename", "") for m in manifest.get("missing_resources", [])}
        for mr in plan.missing_references:
            if mr["basename"] not in missing_declared:
                errors.append(f"Missing resource not declared in manifest: {mr['basename']}")
    except Exception as exc:
        errors.append(f"Manifest verification failed: {exc}")

    if not collection_path.is_file():
        errors.append("Collection JSON missing")
        return PackageVerification(ok=len(errors) == 0, errors=errors)

    try:
        data = load_json(collection_path)
        if not is_obs_scene_collection_data(data):
            errors.append("Collection JSON not a valid OBS scene collection")
        for ref in _iter_local_path_references(data):
            val = ref.value
            if looks_absolute_local_path(val) and not val.startswith("../") and not val.startswith(MISSING_PLACEHOLDER_PREFIX):
                errors.append(f"Absolute path found in collection: {val}")
    except Exception as exc:
        errors.append(f"Collection verification failed: {exc}")

    for pf in plan.files:
        fp = package_path / pf.package_path.replace("../", "")
        if not fp.is_file():
            errors.append(f"Planned file missing: {pf.package_path}")

    manifest_files = {f["path"] for f in manifest.get("files", [])}
    for current, dirs, files in os.walk(package_path):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            rel = str(Path(current, f).relative_to(package_path)).replace("\\", "/")
            if rel in ("manifest.json", "Import Instructions.txt") or rel.startswith("collection/"):
                continue
            if rel not in manifest_files and not rel.startswith(("assets/", "browser/")):
                errors.append(f"Unexpected file in package: {rel}")
            elif rel.startswith(("assets/", "browser/")) and rel not in manifest_files:
                errors.append(f"File not declared in manifest: {rel}")

    return PackageVerification(ok=len(errors) == 0, errors=errors)


def _verify_zip_package(zip_path: Path, plan: ExportPlan, package_root_name: str) -> PackageVerification:
    errors: list[str] = []

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad:
                errors.append(f"ZIP CRC error in: {bad}")

            names = zf.namelist()
            seen_normalized: set[str] = set()
            roots: set[str] = set()

            for name in names:
                normalized = name.replace("\\", "/").casefold()
                if normalized in seen_normalized:
                    errors.append(f"Duplicate normalized ZIP entry: {name}")
                    continue
                seen_normalized.add(normalized)

                clean = name.replace("\\", "/")
                if clean.startswith("/") or ".." in clean.split("/"):
                    errors.append(f"Unsafe ZIP entry: {name}")
                    continue
                if len(clean) >= 2 and clean[1] == ":":
                    errors.append(f"Unsafe ZIP entry (drive-qualified): {name}")
                    continue
                if clean.startswith("//"):
                    errors.append(f"Unsafe ZIP entry (UNC): {name}")
                    continue

                top = clean.split("/")[0] if "/" in clean else clean
                roots.add(top)

            if len(roots) != 1:
                errors.append(f"ZIP must have exactly one top-level directory, got {sorted(roots)}")
            else:
                root = next(iter(roots))
                manifest_zip_path = f"{root}/manifest.json"
                if manifest_zip_path not in names:
                    errors.append("manifest.json missing from ZIP")
                else:
                    manifest_data = json.loads(zf.read(manifest_zip_path))
                    if manifest_data.get("schema") != MANIFEST_SCHEMA:
                        errors.append(f"Unknown manifest schema in ZIP: {manifest_data.get('schema')}")
                    if manifest_data.get("schema_version") != MANIFEST_VERSION:
                        errors.append(f"Unsupported manifest version in ZIP: {manifest_data.get('schema_version')}")

                    for f in manifest_data.get("files", []):
                        zip_fp = f"{root}/{f['path']}"
                        if zip_fp not in names:
                            errors.append(f"Manifest file not in ZIP: {f['path']}")
                        else:
                            info = zf.getinfo(zip_fp)
                            if info.file_size != f["size"]:
                                errors.append(f"ZIP size mismatch: {f['path']} (expected {f['size']}, got {info.file_size})")
                            try:
                                actual_sha = _sha256_chunked_zip(zf, zip_fp)
                            except (OSError, zipfile.BadZipFile) as exc:
                                errors.append(f"Could not hash ZIP member {f['path']}: {exc}")
                                continue
                            if actual_sha != f["sha256"]:
                                errors.append(f"ZIP SHA-256 mismatch: {f['path']}")

                    coll_zip_path = f"{root}/{manifest_data.get('collection', {}).get('path', '')}"
                    if coll_zip_path not in names:
                        errors.append("Collection JSON missing from ZIP")
                    else:
                        try:
                            coll_data = json.loads(zf.read(coll_zip_path))
                            if not is_obs_scene_collection_data(coll_data):
                                errors.append("ZIP collection is not valid OBS data")
                            for ref in _iter_local_path_references(coll_data):
                                val = ref.value
                                if looks_absolute_local_path(val) and not val.startswith("../") and not val.startswith(MISSING_PLACEHOLDER_PREFIX):
                                    errors.append(f"Absolute path in ZIP collection: {val}")
                        except Exception as exc:
                            errors.append(f"ZIP collection verification failed: {exc}")

    except Exception as exc:
        errors.append(f"ZIP verification failed: {exc}")

    return PackageVerification(ok=len(errors) == 0, errors=errors)


# ---------------------------------------------------------------------------
# Revalidation after freeze
# ---------------------------------------------------------------------------

def _revalidate_plan(plan: ExportPlan) -> None:
    if not plan.collection_path.is_file():
        raise UtilityError("The collection file was moved or deleted.")
    current_digest = hashlib.sha256(
        json.dumps(load_json(plan.collection_path), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    if current_digest != plan.collection_digest:
        raise UtilityError("The scene collection changed since the inventory was built. Run the inventory again.")

    for pf in plan.files:
        if not pf.source_path.is_file():
            raise UtilityError(f"Source file no longer exists: {pf.source_path}")
        try:
            stat_info = pf.source_path.stat()
            current_size = stat_info.st_size
        except OSError:
            raise UtilityError(f"Cannot read source file attributes: {pf.source_path}")
        if current_size != pf.size:
            raise UtilityError(f"Source file size changed: {pf.source_path}")
        if _is_link_or_reparse_point(pf.source_path):
            raise UtilityError(f"Source file is a link or reparse point: {pf.source_path}")
        # Recompute the digest immediately before publishing. A same-size
        # content mutation (e.g. AAAA -> BBBB) changes the digest and fails here.
        current_digest = _sha256_chunked(pf.source_path)
        if current_digest != pf.digest:
            raise UtilityError(f"Source file changed since the inventory was built: {pf.source_path}")

    if plan.output_path.exists():
        raise UtilityError("Output path already exists. Run the inventory again.")


# ---------------------------------------------------------------------------
# ZIP compression mode selection
# ---------------------------------------------------------------------------

def _zip_compress_type(filename: str) -> int:
    ext = os.path.splitext(filename)[1].casefold()
    if ext in ALREADY_COMPRESSED_EXTENSIONS:
        return zipfile.ZIP_STORED
    return zipfile.ZIP_DEFLATED


# ---------------------------------------------------------------------------
# Folder publication
# ---------------------------------------------------------------------------

def _publish_folder(plan: ExportPlan, staging_path: Path, package_root_name: str) -> Path:
    root = staging_path / package_root_name
    root.mkdir()
    coll_dir = root / "collection"
    coll_dir.mkdir()
    assets_dir = root / "assets"
    assets_dir.mkdir()
    for sub in ("images", "videos", "audio", "other"):
        (assets_dir / sub).mkdir()

    copied_paths: dict[Path, Path] = {}
    browser_dirs: dict[str, Path] = {}

    for pf in plan.files:
        if pf.category == "browser":
            parts = pf.package_path.replace("../browser/", "").split("/", 1)
            proj_name = parts[0]
            rel = parts[1] if len(parts) > 1 else ""
            if proj_name not in browser_dirs:
                proj_root = root / "browser" / proj_name
                proj_root.mkdir(parents=True, exist_ok=True)
                browser_dirs[proj_name] = proj_root
            dest = root / "browser" / proj_name / rel
        else:
            dest = root / pf.package_path.replace("../", "")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pf.source_path, dest)
        copied_paths[pf.source_path] = dest

    portable = copy.deepcopy(plan.portable_collection)
    for ref in _iter_local_path_references(portable):
        source = Path(normalized_output_path(ref.value)).resolve()
        if not source.is_file():
            for mr in plan.missing_references:
                # Compare resolved paths so Windows 8.3 short-name forms
                # (RUNNER~1 vs runneradmin) do not cause mismatches.
                if mr["path"] == str(source):
                    ref.parent[ref.key] = _sanitise_missing_reference(ref.value)
                    break
            continue
        if source in copied_paths:
            rel_path = os.path.relpath(copied_paths[source], coll_dir).replace("\\", "/")
            if not rel_path.startswith(".."):
                rel_path = "../" + rel_path
            ref.parent[ref.key] = rel_path

    atomic_write_json(coll_dir / f"{plan.collection_stem}.json", portable)

    manifest = _build_manifest(plan, package_root_name)
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    instructions = _build_instructions(plan)
    (root / "Import Instructions.txt").write_text(instructions, encoding="utf-8")

    return root


# ---------------------------------------------------------------------------
# ZIP publication (direct-to-ZIP, no folder)
# ---------------------------------------------------------------------------

def _publish_zip(plan: ExportPlan, package_root_name: str) -> tuple[Path, int]:
    temp_dir = Path(tempfile.mkdtemp(prefix=".export-zip-", dir=plan.destination))
    temp_zip = temp_dir / f"{package_root_name}.zip"
    try:
        with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for pf in plan.files:
                if pf.category == "browser":
                    parts = pf.package_path.replace("../browser/", "").split("/", 1)
                    proj_name = parts[0]
                    rel = parts[1] if len(parts) > 1 else ""
                    zip_path = f"{package_root_name}/browser/{proj_name}/{rel}"
                else:
                    zip_path = f"{package_root_name}/{pf.package_path.replace('../', '')}"
                comp_type = _zip_compress_type(pf.source_path.name)
                zf.write(pf.source_path, zip_path, compress_type=comp_type)

            coll_dir = "collection"
            coll_path = f"{package_root_name}/{coll_dir}/{plan.collection_stem}.json"

            portable = copy.deepcopy(plan.portable_collection)
            copied_sources: dict[Path, str] = {}
            for pf in plan.files:
                if pf.category == "browser":
                    parts = pf.package_path.replace("../browser/", "").split("/", 1)
                    proj_name = parts[0]
                    rel = parts[1] if len(parts) > 1 else ""
                    copied_sources[pf.source_path] = f"../browser/{proj_name}/{rel}"
                else:
                    copied_sources[pf.source_path] = pf.package_path

            for ref in _iter_local_path_references(portable):
                source = Path(normalized_output_path(ref.value)).resolve()
                if source in copied_sources:
                    ref.parent[ref.key] = copied_sources[source]
                elif not source.is_file():
                    for mr in plan.missing_references:
                        # Compare resolved paths so Windows 8.3 short-name forms
                        # (RUNNER~1 vs runneradmin) do not cause mismatches.
                        if mr["path"] == str(source):
                            ref.parent[ref.key] = _sanitise_missing_reference(ref.value)
                            break

            zf.writestr(coll_path, json.dumps(portable, indent=2, ensure_ascii=False),
                        compress_type=zipfile.ZIP_DEFLATED)

            manifest = _build_manifest(plan, package_root_name)
            zf.writestr(f"{package_root_name}/manifest.json",
                        json.dumps(manifest, indent=2, ensure_ascii=False),
                        compress_type=zipfile.ZIP_DEFLATED)

            instructions = _build_instructions(plan)
            zf.writestr(f"{package_root_name}/Import Instructions.txt",
                        instructions, compress_type=zipfile.ZIP_DEFLATED)

        verify = _verify_zip_package(temp_zip, plan, package_root_name)
        if not verify.ok:
            raise UtilityError(f"ZIP verification failed: {'; '.join(verify.errors)}")

        os.replace(str(temp_zip), str(plan.output_path))
        archive_bytes = plan.output_path.stat().st_size
        shutil.rmtree(temp_dir, ignore_errors=True)
        return plan.output_path, archive_bytes
    except Exception:
        if temp_zip.exists():
            temp_zip.unlink(missing_ok=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


# ---------------------------------------------------------------------------
# export_scene_collection (orchestrator)
# ---------------------------------------------------------------------------

def export_scene_collection(
    collection_path: Path,
    destination: Path,
    *,
    compressed: bool = False,
    plan: ExportPlan | None = None,
) -> ExportResult:
    result = ExportResult(compressed=compressed)
    staging_path: Path | None = None
    try:
        if plan is None:
            plan = build_export_plan(collection_path, destination, compressed=compressed)

        _revalidate_plan(plan)

        package_root_name = plan.output_path.name.replace(".zip", "")

        if compressed:
            archive_path, archive_bytes = _publish_zip(plan, package_root_name)
            verify = _verify_zip_package(archive_path, plan, package_root_name)
            result.success = verify.ok
            result.archive_path = archive_path
            result.archive_bytes = archive_bytes
            result.output_path = archive_path
            result.verification = verify
        else:
            staging_path = Path(
                tempfile.mkdtemp(prefix=f".{package_root_name}-", dir=destination)
            )
            _publish_folder(plan, staging_path, package_root_name)
            verify = _verify_folder_package(staging_path / package_root_name, plan, package_root_name)
            if not verify.ok:
                raise UtilityError(f"Package verification failed: {'; '.join(verify.errors)}")

            final_path = plan.output_path
            os.replace(staging_path / package_root_name, final_path)
            staging_path = None

            result.success = True
            result.package_path = final_path
            result.collection_path = final_path / "collection" / f"{plan.collection_stem}.json"
            result.output_path = final_path
            result.verification = verify

        result.copied_files = len(plan.files)
        result.uncompressed_bytes = plan.total_bytes
        result.source_references = len(plan.files) + len(plan.missing_references)
        if plan.missing_references:
            result.skipped_references = [
                f"{m['source']}: {m.get('basename', '')}" for m in plan.missing_references
            ]
    except (OSError, UtilityError) as exc:
        result.error = str(exc) if isinstance(exc, UtilityError) else f"Could not export the scene collection: {exc}"
    finally:
        if staging_path is not None:
            shutil.rmtree(staging_path, ignore_errors=True)
    return result


# ---------------------------------------------------------------------------
# Manifest-aware package detection (for import)
# ---------------------------------------------------------------------------

def detect_portable_package(root: Path) -> Path | None:
    """Return the manifest path if *root* contains a valid portable package.

    Returns ``None`` when no ``manifest.json`` exists.  Raises ``UtilityError``
    when a manifest file is present but unreadable, does not match our schema,
    or uses an unsupported version.
    """
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        raw = manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UtilityError(
            "This folder contains a manifest.json that could not be read. "
            "The package may be corrupted."
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UtilityError(
            "This folder contains a manifest.json that is not valid JSON. "
            "The package may be corrupted."
        ) from exc
    if not isinstance(data, dict):
        raise UtilityError("This package's manifest.json is not a JSON object.")
    if data.get("schema") != MANIFEST_SCHEMA:
        raise UtilityError(
            "The manifest.json in this folder is not a recognized OBS overlay portable package."
        )
    version = data.get("schema_version")
    if not isinstance(version, int) or version != MANIFEST_VERSION:
        raise UtilityError(
            f"This package was created by a newer version of the utility "
            f"(manifest version {version}). Please update OBS Overlay Import Utility."
        )
    return manifest


def validate_portable_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UtilityError(f"Could not read the package manifest: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UtilityError("The package manifest is not valid JSON.") from exc

    if not isinstance(data, dict):
        raise UtilityError("The package manifest is not a JSON object.")

    if data.get("schema") != MANIFEST_SCHEMA:
        raise UtilityError("Not a recognized OBS overlay portable package manifest.")
    version = data.get("schema_version")
    if not isinstance(version, int) or version != MANIFEST_VERSION:
        raise UtilityError(
            f"This package requires manifest version {version}. Update OBS Overlay Import Utility."
        )

    # Validate the collection descriptor before it is ever used.
    coll_info = data.get("collection", {})
    if not isinstance(coll_info, dict):
        raise UtilityError("Manifest is missing collection information.")
    coll_path = coll_info.get("path")
    if not isinstance(coll_path, str) or not coll_path:
        raise UtilityError("Manifest collection path is missing or invalid.")
    if not _manifest_file_path_is_safe(coll_path):
        raise UtilityError(f"Manifest collection path is unsafe: {coll_path}")

    # Validate every declared file: required fields, types, and contained paths.
    files = data.get("files", [])
    if not isinstance(files, list):
        raise UtilityError("Manifest files list is malformed.")
    seen_paths: set[str] = set()
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            raise UtilityError(f"Manifest file entry {index + 1} is not an object.")
        entry_path = entry.get("path")
        if not isinstance(entry_path, str) or not entry_path:
            raise UtilityError(f"Manifest file entry {index + 1} has a missing or invalid path.")
        if not _manifest_file_path_is_safe(entry_path):
            raise UtilityError(f"Manifest file path is unsafe: {entry_path}")
        # Normalize separators before duplicate detection so that
        # ``assets/images/bg.png`` and ``assets\images\bg.png`` cannot both
        # pass validation.
        normalized_key = entry_path.replace("\\", "/").casefold()
        if normalized_key in seen_paths:
            raise UtilityError(f"Duplicate manifest file path: {entry_path}")
        seen_paths.add(normalized_key)
        if not isinstance(entry.get("size"), int) or isinstance(entry.get("size"), bool):
            raise UtilityError(f"Manifest file {entry_path} has a missing or invalid size.")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise UtilityError(f"Manifest file {entry_path} has a missing or invalid sha256 digest.")
        category = entry.get("category")
        if not isinstance(category, str):
            raise UtilityError(f"Manifest file {entry_path} has a missing or invalid category.")

    return data


def materialize_portable_collection(manifest_path: Path, target_collections_dir: Path) -> Path:
    verify_result = verify_portable_package(manifest_path.parent)
    if not verify_result.ok:
        raise UtilityError(f"Package verification failed before import: {'; '.join(verify_result.errors[:3])}")

    target_collections_dir = target_collections_dir.expanduser().resolve()
    target_collections_dir.mkdir(parents=True, exist_ok=True)

    package_root = manifest_path.parent.resolve()
    manifest_data = validate_portable_manifest(manifest_path)

    coll_rel = manifest_data["collection"]["path"]
    coll_src = (package_root / coll_rel).resolve()
    if not coll_src.is_file():
        raise UtilityError(f"Collection file not found in package: {coll_rel}")
    try:
        coll_src.relative_to(package_root)
    except ValueError:
        raise UtilityError(f"Collection path escapes package root: {coll_rel}")

    data = load_json(coll_src)

    def _rewrite(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str) and (child.startswith("../") or child.startswith(MISSING_PLACEHOLDER_PREFIX)):
                    resolved = (coll_src.parent / child).resolve()
                    try:
                        resolved.relative_to(package_root)
                        value[key] = str(resolved)
                    except ValueError:
                        raise UtilityError(f"Portable path escapes package root: {child}")
                elif isinstance(child, (dict, list)):
                    _rewrite(child)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    _rewrite(item)

    _rewrite(data)

    # Never build the output name from untrusted collection JSON. Use the
    # project's safe unique OBS collection-name helper, then verify the final
    # resolved path stays inside the selected OBS scenes directory.
    proposed_name = data.get("name") if isinstance(data.get("name"), str) else coll_src.stem
    _collection_name, out = next_obs_collection_path(target_collections_dir, proposed_name)
    out = out.resolve()
    try:
        out.relative_to(target_collections_dir)
    except ValueError:
        raise UtilityError("The imported collection would be written outside the selected OBS scenes directory.")
    # Set the collection JSON "name" field to the chosen unique collection name
    # so the imported collection's name matches its filename stem. This prevents
    # collisions where two imports of the same package would have identical
    # "name" fields but different filenames.
    if isinstance(data.get("name"), str):
        data["name"] = _collection_name
    atomic_write_json(out, data)
    return out


def _walk_manifest_path(resolved_root: Path, entry_path: str) -> tuple[Path | None, str | None]:
    """Walk every path component from the resolved package root down to a
    manifest-declared file or collection.

    Returns ``(resolved_path, error)``.  When *error* is not ``None`` the path
    is unsafe (contains a link/reparse point or escapes the package root) and
    *resolved_path* is ``None``.
    """
    current = resolved_root
    for part in Path(entry_path).parts:
        current = current / part
        if _is_link_or_reparse_point(current):
            return None, f"Manifest path contains a link or reparse point: {entry_path}"
        try:
            current.relative_to(resolved_root)
        except ValueError:
            return None, f"Manifest path escapes package root: {entry_path}"
    return current, None


def verify_portable_package(package_root: Path) -> PackageVerification:
    manifest_path = package_root / "manifest.json"
    if not manifest_path.is_file():
        return PackageVerification(ok=False, errors=["manifest.json missing"])
    try:
        manifest = validate_portable_manifest(manifest_path)
    except UtilityError as exc:
        return PackageVerification(ok=False, errors=[str(exc)])

    errors = []
    resolved_root = package_root.resolve()

    # --- Validate the collection descriptor path ---
    coll_info = manifest.get("collection", {})
    coll_rel = coll_info.get("path") if isinstance(coll_info, dict) else None
    if not isinstance(coll_rel, str) or not coll_rel:
        errors.append("Manifest collection path is missing or invalid")
    elif not _manifest_file_path_is_safe(coll_rel):
        errors.append(f"Manifest collection path is unsafe: {coll_rel}")
    else:
        coll_fp, coll_err = _walk_manifest_path(resolved_root, coll_rel)
        if coll_err:
            errors.append(coll_err)
        elif coll_fp is None:
            errors.append(f"Could not resolve collection path: {coll_rel}")
        elif not coll_fp.is_file():
            errors.append(f"Collection JSON missing: {coll_rel}")
        else:
            try:
                coll_data = load_json(coll_fp)
                if not is_obs_scene_collection_data(coll_data):
                    errors.append("Collection JSON is not a valid OBS scene collection")
            except UtilityError as exc:
                errors.append(f"Collection JSON could not be read: {exc}")

    for f in manifest.get("files", []):
        entry_path = f.get("path")
        if not isinstance(entry_path, str):
            errors.append("Manifest contains a file entry without a valid path")
            continue
        # Walk every path component from the resolved package root down to the
        # manifest file. A malicious package may place a symlink/reparse point
        # on the final file OR on an intermediate directory (even one that
        # resolves back inside the package). We must reject a link/reparse
        # point at *any* position along the path before statting or hashing,
        # and the resolved target must stay inside the package root.
        resolved_fp, walk_err = _walk_manifest_path(resolved_root, entry_path)
        if walk_err:
            errors.append(walk_err)
            continue
        if resolved_fp is None:
            errors.append(f"Could not resolve manifest file path: {entry_path}")
            continue
        try:
            if not resolved_fp.is_file():
                errors.append(f"Manifest file missing: {entry_path}")
                continue
            actual_size = resolved_fp.stat().st_size
            if actual_size != f.get("size"):
                errors.append(f"Size mismatch: {entry_path} (expected {f.get('size')}, got {actual_size})")
            expected_digest = f.get("sha256")
            if not isinstance(expected_digest, str) or len(expected_digest) != 64:
                errors.append(f"Manifest file {entry_path} has no valid sha256 digest")
                continue
            actual_sha = _sha256_chunked(resolved_fp)
            if actual_sha != expected_digest:
                errors.append(f"SHA-256 mismatch: {entry_path}")
        except OSError as exc:
            errors.append(f"Could not read manifest file {entry_path}: {exc}")

    missing = manifest.get("missing_resources", [])
    for m in missing:
        if not isinstance(m, dict) or "basename" not in m:
            errors.append("Malformed missing_resources entry")

    return PackageVerification(ok=len(errors) == 0, errors=errors)
