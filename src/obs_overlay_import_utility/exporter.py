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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .constants import __version__
from .core import atomic_write_json, is_obs_scene_collection_data, load_json
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
    """Compatibility wrapper — UI code may reference this, but the real plan is ExportPlan."""
    success: bool = False
    collection_path: Path | None = None
    destination: Path | None = None
    package_path: Path | None = None
    source_references: int = 0
    total_bytes: int = 0
    browser_files: int = 0
    items: list[ExportInventoryItem] = field(default_factory=list)
    missing_references: list[str] = field(default_factory=list)
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
    """Return a collection-relative portable path like ``../assets/images/bg.png``."""
    return f"../assets/{category}/{filename}"


def portable_browser_path(project_dir_name: str, relative: str) -> str:
    """Return a collection-relative portable path for a browser file."""
    rel = relative.replace("\\", "/")
    return f"../browser/{project_dir_name}/{rel}"


def is_safe_portable_path(path: str) -> bool:
    """Check that a portable path stays within the package after resolving ``..``."""
    if not path or path.startswith("\\\\"):
        return False
    if len(path) >= 2 and path[1] == ":":
        return False
    normalized = path.replace("\\", "/")
    if normalized.startswith("/"):
        return False
    parts = normalized.split("/")
    depth = 0
    for part in parts:
        if part == "..":
            depth -= 1
        elif part != "." and part:
            depth += 1
        if depth < 0:
            pass  # allow initial ../ for collection-relative paths
    if depth < 0:
        return False
    return True


# ---------------------------------------------------------------------------
# Dependency analysis
# ---------------------------------------------------------------------------

def _analyse_dependencies(data: dict[str, Any]) -> DependencyReport:
    report = DependencyReport()
    seen_fonts: set[str] = set()
    seen_devices: set[tuple[str, str]] = set()
    seen_remote: set[tuple[str, str, str]] = set()
    seen_plugin_src: set[tuple[str, str]] = set()
    seen_plugin_flt: set[tuple[str, str]] = set()

    def _walk(value: Any, source_name: str = "", source_id: str = "") -> None:
        if isinstance(value, dict):
            name = value.get("name", source_name) if isinstance(value.get("name"), str) else source_name
            sid = value.get("id", source_id) if isinstance(value.get("id"), str) else source_id

            if sid and sid not in BUILTIN_SOURCE_IDS and "source" in sid.casefold():
                seen_plugin_src.add((sid, name))
            if sid and sid not in BUILTIN_FILTER_IDS and "filter" in sid.casefold():
                seen_plugin_flt.add((sid, name))

            for key, child in value.items():
                if key == "font" and isinstance(child, dict) and isinstance(child.get("face"), str):
                    seen_fonts.add(child["face"])
                elif key == "font" and isinstance(child, str):
                    seen_fonts.add(child)
                elif key == "style" and isinstance(child, str):
                    pass

                if isinstance(child, str) and REMOTE_URL_RE.match(child):
                    sensitive = bool(SENSITIVE_URL_RE.search(child))
                    host = ""
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(child)
                        host = parsed.netloc
                    except Exception:
                        pass
                    seen_remote.add((child.split("?")[0] if sensitive else child, host, "yes" if sensitive else "no"))
                elif isinstance(child, (dict, list)):
                    _walk(child, source_name=name, source_id=sid)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    _walk(item, source_name=source_name, source_id=source_id)

    _walk(data)
    report.fonts = sorted(seen_fonts)
    for item in seen_devices:
        report.devices.append({"source_name": item[0], "source_id": item[1]})
    for item in sorted(seen_remote):
        report.remote_resources.append({"url": item[0], "host": item[1], "sensitive": item[2]})
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
    canvas_w = None
    canvas_h = None
    if isinstance(sources, list):
        for src in sources:
            if isinstance(src, dict):
                sid = src.get("id", "")
                if sid != "scene":
                    non_scene += 1
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
    while candidate.exists() or (not compressed and (destination / f"{base}.zip").exists() if compressed else (destination / base).exists()):
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


def _next_asset_path(folder: Path, source: Path) -> Path:
    candidate = folder / source.name
    number = 2
    while candidate.exists():
        candidate = folder / f"{source.stem} {number}{source.suffix}"
        number += 1
    return candidate


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
    category_counts: dict[str, int] = {}
    browser_roots_scanned: set[Path] = set()
    browser_project_dirs: list[str] = []

    for reference in _iter_local_path_references(portable):
        source = Path(normalized_output_path(reference.value)).resolve()
        if not source.is_file():
            missing.append({
                "source": reference.source_name,
                "setting": str(reference.detection_key),
                "basename": source.name,
                "reason": "File not found",
            })
            continue

        if source.suffix.casefold() in {".htm", ".html"}:
            source_root = source.parent.resolve()
            if source_root not in browser_roots_scanned:
                browser_roots_scanned.add(source_root)
                project_dir = _sanitise_name(source_root.name)
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
                        ))
                    else:
                        seen_sources[resolved].add(reference.source_name)
                if project_dir not in browser_project_dirs:
                    browser_project_dirs.append(project_dir)
            continue

        cat = _category_for(source)
        if source not in seen_sources:
            seen_sources[source] = {reference.source_name}
            idx = category_counts.get(cat, 0)
            category_counts[cat] = idx + 1
            if idx > 0:
                base, ext = os.path.splitext(source.name)
                filename = f"{base} {idx + 1}{ext}"
            else:
                filename = source.name
            pkg = portable_package_path(cat, filename)
            planned.append(PlannedFile(
                source_path=source,
                package_path=pkg,
                category=cat,
                size=source.stat().st_size,
                source_names=(reference.source_name,),
            ))
        else:
            seen_sources[source].add(reference.source_name)

    for pf in planned:
        pf_dict = pf.__dict__.copy()
        pf_dict["source_names"] = tuple(sorted(seen_sources.get(pf.source_path, set())))

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
# build_export_inventory (compatibility wrapper)
# ---------------------------------------------------------------------------

def build_export_inventory(
    collection_path: Path,
    destination: Path,
) -> ExportInventory:
    result = ExportInventory()
    try:
        plan = build_export_plan(collection_path, destination, compressed=False)
        result.success = True
        result.collection_path = plan.collection_path
        result.destination = plan.destination
        result.package_path = plan.output_path
        result.source_references = len(plan.files) + len(plan.missing_references)
        result.total_bytes = plan.total_bytes
        result.browser_files = sum(1 for pf in plan.files if pf.category == "browser")
        result.items = [
            ExportInventoryItem(
                path=pf.source_path,
                category=pf.category,
                size=pf.size,
                source_name=", ".join(pf.source_names),
                package_path=pf.package_path,
            )
            for pf in plan.files
        ]
        result.missing_references = [
            f"{m['source']}: {m.get('basename', '')}" for m in plan.missing_references
        ]
        result.plan = plan
    except (OSError, UtilityError) as exc:
        result.error = str(exc) if isinstance(exc, UtilityError) else f"Could not inspect the scene collection for export: {exc}"
    return result


# ---------------------------------------------------------------------------
# manifest.json generation
# ---------------------------------------------------------------------------

def _build_manifest(plan: ExportPlan, package_root_name: str) -> dict[str, Any]:
    files = []
    for pf in plan.files:
        sha = hashlib.sha256(pf.source_path.read_bytes()).hexdigest()
        files.append({
            "path": pf.package_path.replace("../", ""),
            "category": pf.category,
            "size": pf.size,
            "sha256": sha,
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
            {"setting": m["setting"], "basename": m["basename"], "reason": m["reason"]}
            for m in plan.missing_references
        ],
        "previews": plan.preview_files,
    }


def _build_instructions(plan: ExportPlan) -> str:
    lines = [
        "OBS Overlay Import Utility — Portable Package",
        "=" * 50,
        "",
        "How to use this package:",
        "",
        "1. If this is a ZIP file, extract it completely before proceeding.",
        "2. Keep the extracted folder together — do not move individual files.",
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
            lines.append(f"  - {d['source_name']} ({d['source_id']})")
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
    errors = []
    manifest_path = package_path / "manifest.json"
    collection_path = package_path / "collection" / f"{plan.collection_stem}.json"

    if not manifest_path.is_file():
        errors.append("manifest.json missing")
    else:
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
                elif fp.stat().st_size != f["size"]:
                    errors.append(f"Size mismatch: {f['path']}")
                else:
                    actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
                    if actual_sha != f["sha256"]:
                        errors.append(f"SHA-256 mismatch: {f['path']}")
        except Exception as exc:
            errors.append(f"Manifest verification failed: {exc}")

    if not collection_path.is_file():
        errors.append("Collection JSON missing")
    else:
        try:
            data = load_json(collection_path)
            if not is_obs_scene_collection_data(data):
                errors.append("Collection JSON not a valid OBS scene collection")
        except Exception as exc:
            errors.append(f"Collection verification failed: {exc}")

    for pf in plan.files:
        fp = package_path / pf.package_path.replace("../", "")
        if not fp.is_file():
            errors.append(f"Planned file missing: {pf.package_path}")

    # Check no absolute paths in collection
    for ref in _iter_local_path_references(json.loads(collection_path.read_text(encoding="utf-8"))):
        if looks_absolute_local_path(ref.value) and not ref.value.startswith(".."):
            errors.append(f"Absolute path found in collection: {ref.value}")

    return PackageVerification(ok=len(errors) == 0, errors=errors)


def _verify_zip_package(zip_path: Path, plan: ExportPlan, package_root_name: str) -> PackageVerification:
    errors = []
    try:
        result = zipfile.Path(zip_path)
        if hasattr(result, "testzip"):
            pass
    except Exception:
        pass

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad:
                errors.append(f"ZIP CRC error in: {bad}")

            names = zf.namelist()
            roots = set()
            for name in names:
                if name.startswith("/") or ".." in name.split("/"):
                    errors.append(f"Unsafe ZIP entry: {name}")
                    continue
                top = name.split("/")[0]
                roots.add(top)

            if len(roots) != 1:
                errors.append(f"ZIP must have exactly one top-level directory, got: {roots}")
            else:
                root = next(iter(roots))
                manifest_zip_path = f"{root}/manifest.json"
                if manifest_zip_path not in names:
                    errors.append("manifest.json missing from ZIP")
                else:
                    manifest_data = json.loads(zf.read(manifest_zip_path))
                    for f in manifest_data.get("files", []):
                        zip_fp = f"{root}/{f['path']}"
                        if zip_fp not in names:
                            errors.append(f"Manifest file not in ZIP: {f['path']}")
                        else:
                            info = zf.getinfo(zip_fp)
                            if info.file_size != f["size"]:
                                errors.append(f"ZIP size mismatch: {f['path']}")
                            actual_sha = hashlib.sha256(zf.read(zip_fp)).hexdigest()
                            if actual_sha != f["sha256"]:
                                errors.append(f"ZIP SHA-256 mismatch: {f['path']}")
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
        if pf.source_path.stat().st_size != pf.size:
            raise UtilityError(f"Source file size changed: {pf.source_path}")

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
    browser_dirs: dict[Path, Path] = {}

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

        shutil.move(str(temp_zip), str(plan.output_path))
        archive_bytes = plan.output_path.stat().st_size
        temp_dir.rmdir()
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
    """Return the manifest path if *root* contains a valid portable package."""
    manifest = root / "manifest.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("schema") == MANIFEST_SCHEMA:
                return manifest
        except Exception:
            pass
    return None


def validate_portable_manifest(manifest_path: Path) -> dict[str, Any]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("schema") != MANIFEST_SCHEMA:
        raise UtilityError("Not a recognized OBS overlay portable package manifest.")
    version = data.get("schema_version")
    if not isinstance(version, int) or version < 1:
        raise UtilityError(f"Unsupported manifest schema version: {version}")
    coll_info = data.get("collection", {})
    if not isinstance(coll_info, dict):
        raise UtilityError("Manifest is missing collection information.")
    return data


def materialize_portable_collection(manifest_path: Path, target_collections_dir: Path) -> Path:
    manifest_data = validate_portable_manifest(manifest_path)
    package_root = manifest_path.parent.resolve()
    coll_rel = manifest_data["collection"]["path"]
    coll_src = (package_root / coll_rel).resolve()
    if not coll_src.is_file():
        raise UtilityError(f"Collection file not found in package: {coll_rel}")
    data = load_json(coll_src)

    def _rewrite(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str) and child.startswith("../"):
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

    name = data.get("name") if isinstance(data.get("name"), str) else coll_src.stem
    out = target_collections_dir / f"{name}.json"
    number = 1
    while out.exists():
        out = target_collections_dir / f"{name} {number}.json"
        number += 1
    atomic_write_json(out, data)
    return out


def verify_portable_package(package_root: Path) -> PackageVerification:
    manifest_path = package_root / "manifest.json"
    if not manifest_path.is_file():
        return PackageVerification(ok=False, errors=["manifest.json missing"])
    try:
        manifest = validate_portable_manifest(manifest_path)
    except UtilityError as exc:
        return PackageVerification(ok=False, errors=[str(exc)])

    errors = []
    for f in manifest.get("files", []):
        fp = package_root / f["path"]
        if not fp.is_file():
            errors.append(f"Manifest file missing: {f['path']}")
        elif fp.stat().st_size != f["size"]:
            errors.append(f"Size mismatch: {f['path']}")
        else:
            actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
            if actual_sha != f["sha256"]:
                errors.append(f"SHA-256 mismatch: {f['path']}")

    missing = manifest.get("missing_resources", [])
    for m in missing:
        if not isinstance(m, dict) or "basename" not in m:
            errors.append("Malformed missing_resources entry")

    return PackageVerification(ok=len(errors) == 0, errors=errors)
