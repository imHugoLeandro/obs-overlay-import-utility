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
from .paths import is_remote_value


STREAMLABS_CANVAS_WIDTH = 2560.0
STREAMLABS_CANVAS_HEIGHT = 1440.0
MAX_ARCHIVE_FILES = 10_000
MAX_ARCHIVE_SIZE = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBER_SIZE = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
MIN_RATIO_CHECK_SIZE = 1024 * 1024
MIN_FREE_SPACE_AFTER_EXTRACTION = 256 * 1024 * 1024



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


def _archive_member_path(member: zipfile.ZipInfo) -> PurePosixPath:
    normalized = member.filename.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or any(":" in part for part in path.parts)
    ):
        raise UtilityError("The Streamlabs package contains an unsafe file path.")
    return path


def _safe_archive_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_FILES:
        raise UtilityError(
            f"The Streamlabs package contains more than {MAX_ARCHIVE_FILES:,} entries."
        )

    total_size = 0
    safe_members: list[zipfile.ZipInfo] = []
    seen: set[str] = set()
    for member in members:
        path = _archive_member_path(member)
        unix_type = stat.S_IFMT(member.external_attr >> 16)
        if unix_type == stat.S_IFLNK:
            raise UtilityError("The Streamlabs package contains an unsupported symbolic link.")
        if unix_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise UtilityError("The Streamlabs package contains an unsupported special file.")
        if member.flag_bits & 0x1:
            raise UtilityError("Encrypted Streamlabs package entries are not supported.")
        if member.file_size > MAX_ARCHIVE_MEMBER_SIZE:
            raise UtilityError("A Streamlabs package file is too large to extract safely.")
        if (
            member.file_size >= MIN_RATIO_CHECK_SIZE
            and (
                member.compress_size == 0
                or member.file_size / member.compress_size > MAX_COMPRESSION_RATIO
            )
        ):
            raise UtilityError("The Streamlabs package has an unsafe compression ratio.")

        key = path.as_posix().casefold()
        if key in seen:
            raise UtilityError("The Streamlabs package contains duplicate file paths.")
        seen.add(key)
        total_size += member.file_size
        if total_size > MAX_ARCHIVE_SIZE:
            raise UtilityError("The Streamlabs package is too large to extract safely.")
        safe_members.append(member)
    return safe_members


def _ensure_extraction_space(parent: Path, members: list[zipfile.ZipInfo]) -> None:
    required = sum(member.file_size for member in members if not member.is_dir())
    free = shutil.disk_usage(parent).free
    if free - required < MIN_FREE_SPACE_AFTER_EXTRACTION:
        raise UtilityError(
            "There is not enough free disk space to extract this Streamlabs package safely."
        )


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


def _asset_index(root: Path, *, published_root: Path | None = None) -> _AssetIndex:
    """Index extracted files while optionally publishing paths under their final root."""
    published_root = published_root.expanduser().resolve() if published_root else root
    by_relative_path: dict[str, Path] = {}
    by_filename: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        published_path = published_root / relative_path
        relative = relative_path.as_posix().casefold()
        by_relative_path[relative] = published_path
        by_filename.setdefault(path.name.casefold(), []).append(published_path)
    return _AssetIndex(by_relative_path=by_relative_path, by_filename=by_filename)


def _asset_path(value: Any, assets: _AssetIndex) -> str:
    if not isinstance(value, str) or not value or is_remote_value(value):
        return value if isinstance(value, str) else ""
    normalized = value.replace("\\", "/").lstrip("/").casefold()
    exact = assets.by_relative_path.get(normalized)
    if exact:
        return str(exact.resolve())
    candidates = assets.by_filename.get(Path(normalized).name, [])
    return str(candidates[0].resolve()) if len(candidates) == 1 else value


def _relink_asset_values(value: Any, assets: _AssetIndex) -> Any:
    if isinstance(value, dict):
        return {key: _relink_asset_values(child, assets) for key, child in value.items()}
    if isinstance(value, list):
        return [_relink_asset_values(child, assets) for child in value]
    if isinstance(value, str):
        return _asset_path(value, assets)
    return value


def _source_settings(content: dict[str, Any], assets: _AssetIndex) -> tuple[str, dict[str, Any]] | None:
    node_type = content.get("nodeType")
    settings = copy.deepcopy(content.get("settings", {}))
    if not isinstance(settings, dict):
        settings = {}
    settings = _relink_asset_values(settings, assets)

    if node_type == "ImageNode":
        settings["file"] = _asset_path(content.get("filename"), assets)
        return "image_source", settings
    if node_type == "VideoNode":
        settings["local_file"] = _asset_path(content.get("filename"), assets)
        settings["is_local_file"] = True
        return "ffmpeg_source", settings
    if node_type in {"WebcamNode", "CameraNode"}:
        settings["device_id"] = ""
        return "av_capture_input", settings
    if node_type in {"AudioInputNode", "MicNode", "MicrophoneNode"}:
        settings["device_id"] = "default"
        return "wasapi_input_capture", settings
    if node_type in {"AudioOutputNode", "DesktopAudioNode"}:
        settings["device_id"] = "default"
        return "wasapi_output_capture", settings
    if node_type == "TextNode":
        return "text_gdiplus_v2", settings
    if node_type == "WidgetNode":
        return "browser_source", settings
    if node_type == "StreamlabelNode":
        text = content.get("textSource")
        settings["text"] = text if isinstance(text, str) else ""
        return "text_gdiplus_v2", settings

    custom_source_id = next(
        (
            content.get(key)
            for key in ("sourceId", "source_id", "obsSourceId", "type")
            if isinstance(content.get(key), str) and content.get(key)
        ),
        None,
    )
    if custom_source_id:
        return custom_source_id, settings
    return None


def _filters(item: dict[str, Any], assets: _AssetIndex) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for filter_data in item.get("filters", []):
        if not isinstance(filter_data, dict) or not isinstance(filter_data.get("type"), str):
            continue
        settings = copy.deepcopy(filter_data.get("settings", {}))
        if not isinstance(settings, dict):
            settings = {}
        settings = _relink_asset_values(settings, assets)
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
    published_root: Path | None = None,
    canvas_width: float = STREAMLABS_CANVAS_WIDTH,
    canvas_height: float = STREAMLABS_CANVAS_HEIGHT,
) -> tuple[dict[str, Any], int, list[str]]:
    """Convert the portable subset of a Streamlabs Desktop config to OBS JSON."""
    if not isinstance(data, dict) or data.get("nodeType") != "RootNode":
        raise UtilityError("The package does not contain a recognized Streamlabs config.json file.")
    scene_items = data.get("scenes", {}).get("items", []) if isinstance(data.get("scenes"), dict) else []
    if not isinstance(scene_items, list) or not scene_items:
        raise UtilityError("The Streamlabs package does not contain any scenes.")

    assets = _asset_index(extraction_root, published_root=published_root)
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
    """Extract and install a Streamlabs package with rollback on publish failure."""
    result = StreamlabsImportResult()
    temporary_root: Path | None = None
    pending_collection: Path | None = None
    extraction_path: Path | None = None
    extraction_published = False
    try:
        archive_path = archive_path.expanduser().resolve()
        if not archive_path.is_file() or archive_path.suffix.casefold() != ".overlay":
            raise UtilityError("Choose a valid Streamlabs .overlay file.")
        with zipfile.ZipFile(archive_path) as archive:
            members = _safe_archive_members(archive)
            _ensure_extraction_space(archive_path.parent, members)
            config_members = [
                member
                for member in members
                if _archive_member_path(member).name.casefold() == "config.json"
            ]
            if len(config_members) != 1:
                raise UtilityError("The Streamlabs package must contain exactly one config.json file.")
            config_member_path = _archive_member_path(config_members[0])
            temporary_root = Path(
                tempfile.mkdtemp(prefix=f".{archive_path.stem}-", dir=archive_path.parent)
            )
            for member in members:
                if member.is_dir():
                    continue
                member_path = _archive_member_path(member)
                target = temporary_root.joinpath(*member_path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)

        config_path = temporary_root.joinpath(*config_member_path.parts)
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise UtilityError(f"Could not read Streamlabs config.json: {exc}") from exc

        obs_scenes_directory = obs_scenes_directory.expanduser().resolve()
        obs_scenes_directory.mkdir(parents=True, exist_ok=True)
        profile_canvas = active_profile_canvas(obs_scenes_directory)
        canvas_width = float(profile_canvas.width) if profile_canvas else STREAMLABS_CANVAS_WIDTH
        canvas_height = float(profile_canvas.height) if profile_canvas else STREAMLABS_CANVAS_HEIGHT
        collection_name, collection_path = next_obs_collection_path(
            obs_scenes_directory, archive_path.stem
        )
        extraction_path = _next_available_directory(
            archive_path.parent, f"{archive_path.stem} overlay"
        )
        converted, imported, skipped = convert_streamlabs_config(
            config,
            temporary_root,
            collection_name,
            published_root=extraction_path,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
        )

        pending_collection = obs_scenes_directory / (
            f".{collection_path.name}.{uuid.uuid4().hex}.pending"
        )
        atomic_write_json(pending_collection, converted)
        if extraction_path.exists() or collection_path.exists():
            raise UtilityError(
                "Another import created one of the selected destination paths. Run the import again."
            )

        os.replace(temporary_root, extraction_path)
        temporary_root = None
        extraction_published = True
        try:
            os.replace(pending_collection, collection_path)
        except OSError as publish_error:
            try:
                shutil.rmtree(extraction_path)
                extraction_published = False
            except OSError as rollback_error:
                raise UtilityError(
                    "OBS collection publishing failed and the extracted package could not be rolled back: "
                    f"{extraction_path}. Remove it manually before retrying."
                ) from rollback_error
            raise publish_error
        pending_collection = None

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
        result.error = (
            str(exc)
            if isinstance(exc, UtilityError)
            else f"Could not import the Streamlabs package: {exc}"
        )
    finally:
        if pending_collection is not None:
            pending_collection.unlink(missing_ok=True)
        if temporary_root is not None:
            shutil.rmtree(temporary_root, ignore_errors=True)
        if not result.success and extraction_published and extraction_path is not None:
            shutil.rmtree(extraction_path, ignore_errors=True)
    return result
