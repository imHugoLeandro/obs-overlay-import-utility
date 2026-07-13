"""Export OBS scene collections with their local files as portable overlay packs."""

from __future__ import annotations

import configparser
import copy
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .core import atomic_write_json, is_obs_scene_collection_data, load_json
from .models import PathReference, UtilityError
from .paths import looks_absolute_local_path, normalized_output_path


IMAGE_EXTENSIONS = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".tif", ".tiff", ".webp"})
VIDEO_EXTENSIONS = frozenset({".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm"})
AUDIO_EXTENSIONS = frozenset({".aac", ".aif", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".wma"})


@dataclass
class ExportResult:
    """Customer-safe summary of one completed or failed overlay export."""

    success: bool = False
    package_path: Path | None = None
    collection_path: Path | None = None
    copied_files: int = 0
    source_references: int = 0
    skipped_references: list[str] = field(default_factory=list)
    error: str | None = None


def list_obs_scene_collections(obs_scenes_directory: Path) -> dict[str, Path]:
    """Return OBS scene collections keyed by their displayed collection name."""
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
    """Return the scene collection selected by OBS, when its marker is available."""
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
    if not filename or Path(filename).name != filename or Path(filename).suffix.casefold() != ".json":
        return None
    candidate = (scenes_directory / filename).resolve()
    try:
        candidate.relative_to(scenes_directory)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _iter_local_path_references(value: Any, *, source_name: str = "Scene collection") -> Iterator[PathReference]:
    """Find every absolute local path in OBS or plugin source/filter data."""
    if isinstance(value, dict):
        current_source = value.get("name") if isinstance(value.get("name"), str) else source_name
        for key, child in value.items():
            if isinstance(child, str) and looks_absolute_local_path(child):
                yield PathReference(value, key, key, child, current_source)
            elif isinstance(child, (dict, list)):
                yield from _iter_local_path_references(child, source_name=current_source)
    elif isinstance(value, list):
        for position, child in enumerate(value):
            if isinstance(child, str) and looks_absolute_local_path(child):
                yield PathReference(value, position, position, child, source_name)
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
    return "other resources"


def _next_package_directory(destination: Path, collection_name: str) -> Path:
    cleaned = " ".join(collection_name.split()).strip().rstrip(". ") or "OBS Overlay"
    candidate = destination / cleaned
    number = 1
    while candidate.exists():
        candidate = destination / f"{cleaned} {number}"
        number += 1
    return candidate


def _next_browser_directory(parent: Path, source_directory: Path) -> Path:
    base_name = " ".join(source_directory.name.split()).strip() or "browser overlay"
    candidate = parent / base_name
    number = 2
    while candidate.exists():
        candidate = parent / f"{base_name} {number}"
        number += 1
    return candidate


def _copy_browser_overlay_directory(
    source_file: Path, package_path: Path, copied_paths: dict[Path, Path]
) -> tuple[Path, int]:
    """Copy a local browser overlay directory so relative web dependencies remain valid."""
    source_root = source_file.parent.resolve()
    target_root = _next_browser_directory(package_path / "browser overlays", source_root)
    copied = 0
    for current, directories, files in os.walk(source_root, followlinks=False):
        directories[:] = [name for name in directories if not Path(current, name).is_symlink()]
        relative_directory = Path(current).relative_to(source_root)
        destination_directory = target_root / relative_directory
        destination_directory.mkdir(parents=True, exist_ok=True)
        for filename in files:
            source = Path(current, filename)
            if source.is_symlink():
                continue
            destination = destination_directory / filename
            shutil.copy2(source, destination)
            copied_paths[source.resolve()] = destination.resolve()
            copied += 1
    target_file = copied_paths.get(source_file.resolve())
    if target_file is None:
        raise UtilityError("Could not include the local browser overlay file.")
    return target_file, copied

def _next_asset_path(folder: Path, source: Path) -> Path:
    candidate = folder / source.name
    number = 2
    while candidate.exists():
        candidate = folder / f"{source.stem} {number}{source.suffix}"
        number += 1
    return candidate


def export_scene_collection(collection_path: Path, destination: Path) -> ExportResult:
    """Copy an OBS collection and all directly referenced local files into one pack."""
    result = ExportResult()
    try:
        collection_path = collection_path.expanduser().resolve()
        destination = destination.expanduser().resolve()
        if not collection_path.is_file():
            raise UtilityError("The selected OBS scene collection no longer exists.")
        if not destination.is_dir():
            raise UtilityError("Choose a valid export destination folder.")
        original = load_json(collection_path)
        if not is_obs_scene_collection_data(original):
            raise UtilityError("The selected JSON is not a recognized OBS scene collection.")

        collection_name = original.get("name") if isinstance(original.get("name"), str) else collection_path.stem
        package_path = _next_package_directory(destination, collection_name)
        package_path.mkdir(parents=True)
        converted = copy.deepcopy(original)
        copied_paths: dict[Path, Path] = {}

        for reference in _iter_local_path_references(converted):
            source = Path(normalized_output_path(reference.value)).resolve()
            result.source_references += 1
            if not source.is_file():
                result.skipped_references.append(f"{reference.source_name}: {reference.value}")
                continue
            target = copied_paths.get(source)
            if target is None and source.suffix.casefold() in {".htm", ".html"}:
                target, copied = _copy_browser_overlay_directory(source, package_path, copied_paths)
                result.copied_files += copied
            elif target is None:
                target_folder = package_path / _resource_folder(source)
                target_folder.mkdir(parents=True, exist_ok=True)
                target = _next_asset_path(target_folder, source)
                shutil.copy2(source, target)
                copied_paths[source] = target
                result.copied_files += 1
            reference.parent[reference.key] = str(target.resolve())

        exported_collection = package_path / f"{collection_path.stem}.json"
        atomic_write_json(exported_collection, converted)
        result.success = True
        result.package_path = package_path
        result.collection_path = exported_collection
    except (OSError, UtilityError) as exc:
        result.error = str(exc) if isinstance(exc, UtilityError) else f"Could not export the scene collection: {exc}"
    return result
