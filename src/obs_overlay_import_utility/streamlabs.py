"""Safe conversion of Streamlabs Desktop overlay packages to OBS collections."""

from __future__ import annotations

import copy
import json
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .core import atomic_write_json, next_obs_collection_path
from .models import UtilityError
from .obs_profile import active_profile_canvas


STREAMLABS_CANVAS_WIDTH = 2560.0
STREAMLABS_CANVAS_HEIGHT = 1440.0
MAX_ARCHIVE_SIZE = 4 * 1024 * 1024 * 1024


@dataclass
class StreamlabsImportResult:
    """The customer-safe summary of a Streamlabs package import."""

    success: bool = False
    extraction_path: Path | None = None
    collection_path: Path | None = None
    collection_name: str = ""
    canvas_width: int = int(STREAMLABS_CANVAS_WIDTH)
    canvas_height: int = int(STREAMLABS_CANVAS_HEIGHT)
    profile_name: str | None = None
    imported_sources: int = 0
    skipped_sources: list[str] = field(default_factory=list)
    error: str | None = None


def default_obs_scenes_directory(obs_executable: Path | None = None) -> Path:
    """Return the data directory used by normal or detected portable OBS installs."""
    if obs_executable:
        executable = obs_executable.expanduser().resolve()
        # A portable OBS install keeps configuration under its installation root.
        for parent in executable.parents:
            candidate = parent / "config" / "obs-studio" / "basic" / "scenes"
            if candidate.is_dir():
                return candidate
            if parent.name.casefold() == "obs-studio":
                break

    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "obs-studio" / "basic" / "scenes"
    return Path.home() / "AppData" / "Roaming" / "obs-studio" / "basic" / "scenes"


def _safe_archive_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    total_size = 0
    members: list[zipfile.ZipInfo] = []
    seen: set[str] = set()
    for member in archive.infolist():
        path = PurePosixPath(member.filename)
        if not member.filename or path.is_absolute() or ".." in path.parts:
            raise UtilityError("The Streamlabs package contains an unsafe file path.")
        if stat.S_IFMT(member.external_attr >> 16) == stat.S_IFLNK:
            raise UtilityError("The Streamlabs package contains an unsupported symbolic link.")
        key = str(path).casefold()
        if key in seen:
            raise UtilityError("The Streamlabs package contains duplicate file paths.")
        seen.add(key)
        total_size += member.file_size
        if total_size > MAX_ARCHIVE_SIZE:
            raise UtilityError("The Streamlabs package is too large to extract safely.")
        members.append(member)
    return members


def find_streamlabs_packages(root: Path) -> list[Path]:
    """Find Streamlabs ``.overlay`` packages without following directory links."""
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise UtilityError("Choose a valid overlay folder first.")
    packages: list[Path] = []
    try:
        for current, directories, files in os.walk(root, followlinks=False):
            directories[:] = [
                name
                for name in directories
                if name.casefold() not in {".git", ".venv", ".venv-build", "__pycache__", "build", "dist"}
                and not Path(current, name).is_symlink()
            ]
            for filename in files:
                path = Path(current, filename)
                if path.suffix.casefold() == ".overlay" and not path.is_symlink():
                    packages.append(path)
    except OSError as exc:
        raise UtilityError(f"Could not scan this folder: {exc}") from exc
    return sorted(packages, key=lambda path: str(path).casefold())

def _next_available_directory(parent: Path, base_name: str) -> Path:
    candidate = parent / base_name
    number = 2
    while candidate.exists():
        candidate = parent / f"{base_name} {number}"
        number += 1
    return candidate


def _unique_name(name: str, used: set[str]) -> str:
    cleaned = " ".join(name.split()).strip() or "Untitled source"
    candidate = cleaned
    number = 2
    while candidate.casefold() in used:
        candidate = f"{cleaned} {number}"
        number += 1
    used.add(candidate.casefold())
    return candidate


def _source(name: str, source_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "uuid": str(uuid.uuid4()),
        "id": source_id,
        "versioned_id": source_id,
        "settings": settings,
        "mixers": 0,
        "sync": 0,
        "flags": 0,
        "volume": 1.0,
        "balance": 0.5,
        "enabled": True,
        "muted": False,
        "push-to-mute": False,
        "push-to-mute-delay": 0,
        "push-to-talk": False,
        "push-to-talk-delay": 0,
        "hotkeys": {},
        "deinterlace_mode": 0,
        "deinterlace_field_order": 0,
        "monitoring_type": 0,
        "private_settings": {},
    }


@dataclass
class _AssetIndex:
    by_relative_path: dict[str, Path]
    by_filename: dict[str, list[Path]]


def _asset_index(root: Path) -> _AssetIndex:
    """Index every extracted file, retaining enough context to avoid wrong duplicates."""
    by_relative_path: dict[str, Path] = {}
    by_filename: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().casefold()
        by_relative_path[relative] = path
        by_filename.setdefault(path.name.casefold(), []).append(path)
    return _AssetIndex(by_relative_path=by_relative_path, by_filename=by_filename)


def _asset_path(value: Any, assets: _AssetIndex) -> str:
    if not isinstance(value, str) or not value:
        return ""
    normalized = value.replace("\\", "/").lstrip("/").casefold()
    exact = assets.by_relative_path.get(normalized)
    if exact:
        return str(exact.resolve())
    candidates = assets.by_filename.get(Path(normalized).name, [])
    return str(candidates[0].resolve()) if len(candidates) == 1 else value


def _source_settings(content: dict[str, Any], assets: _AssetIndex) -> tuple[str, dict[str, Any]] | None:
    node_type = content.get("nodeType")
    settings = copy.deepcopy(content.get("settings", {}))
    if not isinstance(settings, dict):
        settings = {}

    if node_type == "ImageNode":
        return "image_source", {"file": _asset_path(content.get("filename"), assets)}
    if node_type == "VideoNode":
        settings["local_file"] = _asset_path(content.get("filename"), assets)
        settings["is_local_file"] = True
        return "ffmpeg_source", settings
    if node_type in {"WebcamNode", "CameraNode"}:
        return "av_capture_input", {"device_id": ""}
    if node_type in {"AudioInputNode", "MicNode", "MicrophoneNode"}:
        return "wasapi_input_capture", {"device_id": "default"}
    if node_type in {"AudioOutputNode", "DesktopAudioNode"}:
        return "wasapi_output_capture", {"device_id": "default"}
    if node_type == "TextNode":
        return "text_gdiplus_v2", settings
    if node_type == "WidgetNode":
        return "browser_source", settings
    if node_type == "StreamlabelNode":
        text = content.get("textSource")
        return "text_gdiplus_v2", {"text": text if isinstance(text, str) else ""}
    return None


def _filters(item: dict[str, Any], assets: _AssetIndex) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for filter_data in item.get("filters", []):
        if not isinstance(filter_data, dict) or not isinstance(filter_data.get("type"), str):
            continue
        settings = copy.deepcopy(filter_data.get("settings", {}))
        if not isinstance(settings, dict):
            settings = {}
        for key in ("file", "image_path", "local_file", "path"):
            if key in settings:
                settings[key] = _asset_path(settings[key], assets)
        converted.append(
            {
                "name": str(filter_data.get("name") or filter_data["type"]),
                "uuid": str(uuid.uuid4()),
                "id": filter_data["type"],
                "versioned_id": filter_data["type"],
                "settings": settings,
                "enabled": True,
            }
        )
    return converted


def _scene_item(
    item: dict[str, Any], source: dict[str, Any], identifier: int, canvas_width: float, canvas_height: float
) -> dict[str, Any]:
    crop = item.get("crop", {}) if isinstance(item.get("crop"), dict) else {}
    return {
        "name": source["name"],
        "source_uuid": source["uuid"],
        "visible": bool(item.get("visible", True)),
        "locked": bool(item.get("locked", False)),
        "rot": float(item.get("rotation", 0) or 0),
        "scale_ref": {"x": canvas_width, "y": canvas_height},
        "align": 5,
        "bounds_type": 0,
        "bounds_align": 0,
        "bounds_crop": False,
        "crop_left": int(crop.get("left", 0) or 0),
        "crop_top": int(crop.get("top", 0) or 0),
        "crop_right": int(crop.get("right", 0) or 0),
        "crop_bottom": int(crop.get("bottom", 0) or 0),
        "id": identifier,
        "group_item_backup": False,
        "pos": {
            "x": float(item.get("x", 0) or 0) * canvas_width,
            "y": float(item.get("y", 0) or 0) * canvas_height,
        },
        "scale": {
            "x": float(item.get("scaleX", 1 / STREAMLABS_CANVAS_WIDTH) or 0) * canvas_width,
            "y": float(item.get("scaleY", 1 / STREAMLABS_CANVAS_HEIGHT) or 0) * canvas_height,
        },
        "bounds": {"x": 0.0, "y": 0.0},
        "scale_filter": "disable",
        "blend_method": "default",
        "blend_type": "normal",
        "private_settings": {},
    }


def convert_streamlabs_config(
    data: Any,
    extraction_root: Path,
    collection_name: str,
    *,
    canvas_width: float = STREAMLABS_CANVAS_WIDTH,
    canvas_height: float = STREAMLABS_CANVAS_HEIGHT,
) -> tuple[dict[str, Any], int, list[str]]:
    """Convert the portable subset of a Streamlabs Desktop config to OBS JSON."""
    if not isinstance(data, dict) or data.get("nodeType") != "RootNode":
        raise UtilityError("The package does not contain a recognized Streamlabs config.json file.")
    scene_items = data.get("scenes", {}).get("items", []) if isinstance(data.get("scenes"), dict) else []
    if not isinstance(scene_items, list) or not scene_items:
        raise UtilityError("The Streamlabs package does not contain any scenes.")

    assets = _asset_index(extraction_root)
    used_names: set[str] = set()
    sources: list[dict[str, Any]] = []
    scene_by_id: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []

    for index, scene in enumerate(scene_items, start=1):
        if not isinstance(scene, dict):
            continue
        name = _unique_name(str(scene.get("name") or f"Scene {index}"), used_names)
        source = _source(name, "scene", {"id_counter": 0, "custom_size": False, "items": []})
        source["hotkeys"] = {"OBSBasic.SelectScene": []}
        sources.append(source)
        scene_id = scene.get("sceneId")
        if isinstance(scene_id, str):
            scene_by_id[scene_id] = source

    imported_sources = 0
    for scene in scene_items:
        if not isinstance(scene, dict) or not isinstance(scene.get("sceneId"), str):
            continue
        target_scene = scene_by_id.get(scene["sceneId"])
        if target_scene is None:
            continue
        entries = scene.get("slots", {}).get("items", []) if isinstance(scene.get("slots"), dict) else []
        if not isinstance(entries, list):
            continue
        for identifier, item in enumerate(entries, start=1):
            if not isinstance(item, dict) or not isinstance(item.get("content"), dict):
                continue
            content = item["content"]
            node_type = content.get("nodeType")
            if node_type == "SceneSourceNode":
                child = scene_by_id.get(content.get("sceneId"))
                if child is None:
                    skipped.append(f"{item.get('name', 'Unnamed source')}: linked scene is missing")
                    continue
                target_scene["settings"]["items"].append(
                _scene_item(item, child, identifier, canvas_width, canvas_height)
            )
                continue

            source_type = _source_settings(content, assets)
            if source_type is None:
                skipped.append(f"{item.get('name', 'Unnamed source')}: {node_type or 'unknown'} source")
                continue
            source_id, settings = source_type
            name = _unique_name(str(item.get("name") or node_type), used_names)
            child = _source(name, source_id, settings)
            filters = _filters(item, assets)
            if filters:
                child["filters"] = filters
            sources.append(child)
            target_scene["settings"]["items"].append(
                _scene_item(item, child, identifier, canvas_width, canvas_height)
            )
            imported_sources += 1
        target_scene["settings"]["id_counter"] = len(entries)

    scene_order = [{"name": source["name"]} for source in scene_by_id.values()]
    first_scene = scene_order[0]["name"] if scene_order else "Scene"
    converted = {
        "name": collection_name,
        "sources": sources,
        "groups": [],
        "scene_order": scene_order,
        "current_scene": first_scene,
        "current_program_scene": first_scene,
        "current_transition": "Fade",
        "transition_duration": 300,
        "transitions": [],
        "quick_transitions": [],
        "saved_projectors": [],
        "preview_locked": False,
        "scaling_enabled": False,
        "scaling_level": -23,
        "scaling_off_x": 0.0,
        "scaling_off_y": 0.0,
        "modules": {},
        "resolution": {"x": int(canvas_width), "y": int(canvas_height)},
        "version": 2,
    }
    return converted, imported_sources, skipped


def import_streamlabs_overlay(archive_path: Path, obs_scenes_directory: Path) -> StreamlabsImportResult:
    """Extract a Streamlabs ``.overlay`` package and install a new OBS collection."""
    result = StreamlabsImportResult()
    temporary_root: Path | None = None
    try:
        archive_path = archive_path.expanduser().resolve()
        if not archive_path.is_file():
            raise UtilityError("Choose a valid Streamlabs .overlay file.")
        with zipfile.ZipFile(archive_path) as archive:
            members = _safe_archive_members(archive)
            config_members = [member for member in members if PurePosixPath(member.filename).name.casefold() == "config.json"]
            if len(config_members) != 1:
                raise UtilityError("The Streamlabs package must contain exactly one config.json file.")
            temporary_root = Path(tempfile.mkdtemp(prefix=f".{archive_path.stem}-", dir=archive_path.parent))
            for member in members:
                if member.is_dir():
                    continue
                target = temporary_root.joinpath(*PurePosixPath(member.filename).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)

        config_path = temporary_root.joinpath(*PurePosixPath(config_members[0].filename).parts)
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise UtilityError(f"Could not read Streamlabs config.json: {exc}") from exc

        obs_scenes_directory = obs_scenes_directory.expanduser().resolve()
        obs_scenes_directory.mkdir(parents=True, exist_ok=True)
        profile_canvas = active_profile_canvas(obs_scenes_directory)
        canvas_width = float(profile_canvas.width) if profile_canvas else STREAMLABS_CANVAS_WIDTH
        canvas_height = float(profile_canvas.height) if profile_canvas else STREAMLABS_CANVAS_HEIGHT
        collection_name, collection_path = next_obs_collection_path(obs_scenes_directory, archive_path.stem)
        converted, imported, skipped = convert_streamlabs_config(
            config,
            temporary_root,
            collection_name,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
        )

        extraction_path = _next_available_directory(archive_path.parent, f"{archive_path.stem} overlay")
        os.replace(temporary_root, extraction_path)
        temporary_root = None
        # Rebuild after the rename so OBS stores the final, customer-visible asset paths.
        converted, imported, skipped = convert_streamlabs_config(
            config,
            extraction_path,
            collection_name,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
        )
        atomic_write_json(collection_path, converted)

        result.success = True
        result.extraction_path = extraction_path
        result.collection_path = collection_path
        result.collection_name = collection_name
        result.canvas_width = int(canvas_width)
        result.canvas_height = int(canvas_height)
        result.profile_name = profile_canvas.profile_name if profile_canvas else None
        result.imported_sources = imported
        result.skipped_sources = skipped
    except (OSError, zipfile.BadZipFile, UtilityError) as exc:
        result.error = str(exc) if isinstance(exc, UtilityError) else f"Could not import the Streamlabs package: {exc}"
    finally:
        if temporary_root:
            shutil.rmtree(temporary_root, ignore_errors=True)
    return result
