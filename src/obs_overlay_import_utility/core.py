"""Safe OBS scene collection discovery and conversion engine."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterator

from .constants import GENERATED_JSON_RE, SUPPORTED_EXTENSIONS, TRACKING_FILENAME
from .models import (
    AmbiguousMatch,
    ConversionResult,
    FileIndex,
    PathReference,
    UtilityError,
)
from .paths import (
    find_file_match,
    is_local_media_path,
    normalized_key,
    normalized_output_path,
    portable_filename,
    portable_parent_name,
)


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UtilityError(f"Could not read {path.name}: {exc}") from exc


def is_obs_scene_collection_data(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    sources = data.get("sources")
    scene_order = data.get("scene_order")
    return isinstance(sources, list) and (
        isinstance(scene_order, list)
        or isinstance(data.get("current_scene"), str)
        or any(isinstance(source, dict) and "settings" in source for source in sources)
    )


def is_likely_obs_json(path: Path) -> bool:
    try:
        return is_obs_scene_collection_data(load_json(path))
    except UtilityError:
        return False


def should_skip_json(path: Path) -> bool:
    name = path.name
    return (
        name.casefold() == TRACKING_FILENAME.casefold()
        or bool(GENERATED_JSON_RE.search(name))
        or any(
            part.casefold() in {".git", ".venv", ".venv-build", "build", "dist"}
            for part in path.parts
        )
    )


def _prune_directories(current: str, directories: list[str]) -> None:
    directories[:] = [
        name
        for name in directories
        if name.casefold()
        not in {".git", ".venv", ".venv-build", "__pycache__", "build", "dist"}
        and not Path(current, name).is_symlink()
    ]


def find_scene_collections(root: Path) -> list[Path]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise UtilityError("Choose a valid overlay folder first.")

    collections: list[Path] = []
    try:
        for current, directories, files in os.walk(root, followlinks=False):
            _prune_directories(current, directories)
            for filename in files:
                path = Path(current, filename)
                if path.suffix.casefold() != ".json" or should_skip_json(path):
                    continue
                if is_likely_obs_json(path):
                    collections.append(path)
    except OSError as exc:
        raise UtilityError(f"Could not scan this folder: {exc}") from exc
    return sorted(collections, key=lambda path: str(path).casefold())


def build_file_index(root: Path, *, case_sensitive: bool = False) -> FileIndex:
    root = root.expanduser().resolve()
    index = FileIndex()
    try:
        for current, directories, files in os.walk(root, followlinks=False):
            _prune_directories(current, directories)
            for filename in files:
                path = Path(current, filename)
                if path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
                    continue
                resolved = str(path.resolve())
                name_key = normalized_key(filename, case_sensitive)
                folder_key = normalized_key(path.parent.name, case_sensitive)
                index.by_name.setdefault(name_key, []).append(resolved)
                index.by_folder.setdefault(folder_key, {}).setdefault(
                    name_key, []
                ).append(resolved)
                index.file_count += 1
    except OSError as exc:
        raise UtilityError(f"Could not index overlay files: {exc}") from exc
    return index


def iter_path_references(
    value: Any, *, source_name: str = "Scene collection"
) -> Iterator[PathReference]:
    if isinstance(value, dict):
        current_source = (
            value.get("name") if isinstance(value.get("name"), str) else source_name
        )
        for key, child in value.items():
            if isinstance(child, str) and is_local_media_path(child):
                yield PathReference(value, key, key, child, current_source)
            elif isinstance(child, (dict, list)):
                yield from iter_path_references(child, source_name=current_source)
    elif isinstance(value, list):
        for position, child in enumerate(value):
            if isinstance(child, str) and is_local_media_path(child):
                yield PathReference(value, position, position, child, source_name)
            elif isinstance(child, (dict, list)):
                yield from iter_path_references(child, source_name=source_name)


def path_exists_on_this_platform(value: str) -> bool:
    return Path(normalized_output_path(value)).is_file()


def next_output_path(collection_path: Path) -> Path:
    base = collection_path.with_name(f"{collection_path.stem}_ImportReady.json")
    if not base.exists():
        return base
    number = 2
    while True:
        candidate = collection_path.with_name(
            f"{collection_path.stem}_ImportReady_{number}.json"
        )
        if not candidate.exists():
            return candidate
        number += 1


def atomic_write_json(path: Path, data: Any) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except OSError as exc:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise UtilityError(f"Could not save the converted collection: {exc}") from exc


def _portable_collection_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", value)
    cleaned = " ".join(cleaned.split()).rstrip(". ")
    return cleaned or "Imported Scene Collection"


def next_obs_collection_path(directory: Path, base_name: str) -> tuple[str, Path]:
    """Choose a new OBS collection filename without replacing an existing collection."""
    name = _portable_collection_name(base_name)
    candidate = directory / f"{name}.json"
    number = 1
    while candidate.exists():
        candidate = directory / f"{name} {number}.json"
        number += 1
    return candidate.stem, candidate


def install_scene_collection(
    collection_path: Path, obs_scenes_directory: Path
) -> tuple[str, Path]:
    """Copy a validated OBS collection into OBS using a unique collection name."""
    collection_path = collection_path.expanduser().resolve()
    data = load_json(collection_path)
    if not is_obs_scene_collection_data(data):
        raise UtilityError(
            "The converted file is not a recognized OBS scene collection."
        )
    base_name = (
        data.get("name") if isinstance(data.get("name"), str) else collection_path.stem
    )
    obs_scenes_directory = obs_scenes_directory.expanduser().resolve()
    obs_scenes_directory.mkdir(parents=True, exist_ok=True)
    collection_name, destination = next_obs_collection_path(
        obs_scenes_directory, base_name
    )
    installed = copy.deepcopy(data)
    installed["name"] = collection_name
    atomic_write_json(destination, installed)
    return collection_name, destination


def scene_item_uses_bounds(item: dict[str, Any]) -> bool:
    """Return whether an OBS scene item uses an active bounds mode."""
    bounds_type = item.get("bounds_type")
    if isinstance(bounds_type, str):
        return bounds_type.casefold() not in {"", "0", "none", "obs_bounds_none"}
    return bounds_type not in (None, 0)


def _scale_transform_pair(
    value: Any,
    factor_x: float,
    factor_y: float,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> None:
    if not isinstance(value, dict):
        return
    if isinstance(value.get("x"), (int, float)):
        value["x"] = value["x"] * factor_x + offset_x
    if isinstance(value.get("y"), (int, float)):
        value["y"] = value["y"] * factor_y + offset_y


def resize_scene_item_transform(
    item: dict[str, Any],
    factor_x: float,
    factor_y: float,
    reference_width: int,
    reference_height: int,
    *,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> None:
    """Resize one OBS scene-item transform without double-scaling active bounds."""
    _scale_transform_pair(item.get("pos"), factor_x, factor_y, offset_x, offset_y)
    bounds = item.get("bounds")
    if scene_item_uses_bounds(item) and isinstance(bounds, dict):
        _scale_transform_pair(bounds, factor_x, factor_y)
    else:
        _scale_transform_pair(item.get("scale"), factor_x, factor_y)
    item["scale_ref"] = {
        "x": float(reference_width),
        "y": float(reference_height),
    }


def resize_scene_collection(data: Any, width: int, height: int) -> bool:
    """Resize an OBS collection's canvas and absolute scene-item transforms.

    Returns whether the source collection contained a usable canvas resolution.
    Collections without one are still marked with the requested resolution, but their
    transforms are left intact because there is no safe scale factor to apply.
    """
    if not is_obs_scene_collection_data(data):
        raise UtilityError(
            "The converted file is not a recognized OBS scene collection."
        )
    if not (16 <= width <= 32_768 and 16 <= height <= 32_768):
        raise UtilityError("The OBS profile canvas resolution is invalid.")

    resolution = data.get("resolution")
    source_width = resolution.get("x") if isinstance(resolution, dict) else None
    source_height = resolution.get("y") if isinstance(resolution, dict) else None
    can_scale = (
        isinstance(source_width, (int, float))
        and isinstance(source_height, (int, float))
        and source_width > 0
        and source_height > 0
    )
    scale_x = width / source_width if can_scale else 1.0
    scale_y = height / source_height if can_scale else 1.0

    for source in data.get("sources", []):
        if not isinstance(source, dict) or source.get("id") not in {"scene", "group"}:
            continue
        settings = source.get("settings")
        items = settings.get("items") if isinstance(settings, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if can_scale:
                resize_scene_item_transform(
                    item,
                    scale_x,
                    scale_y,
                    width,
                    height,
                )
            elif "scale_ref" in item:
                item["scale_ref"] = {"x": float(width), "y": float(height)}
    data["resolution"] = {"x": int(width), "y": int(height)}
    return can_scale


def convert_collection(
    collection_path: Path,
    overlay_root: Path,
    *,
    strict: bool = True,
    case_sensitive: bool = False,
) -> ConversionResult:
    collection_path = collection_path.expanduser().resolve()
    overlay_root = overlay_root.expanduser().resolve()
    result = ConversionResult()

    try:
        if not collection_path.is_file():
            raise UtilityError("The selected scene collection no longer exists.")
        data = load_json(collection_path)
        if not is_obs_scene_collection_data(data):
            raise UtilityError(
                "The selected JSON is not a recognized OBS scene collection."
            )

        converted = copy.deepcopy(data)
        references = list(iter_path_references(converted))
        result.candidate_paths = len(references)
        index = build_file_index(overlay_root, case_sensitive=case_sensitive)
        result.indexed_files = index.file_count

        for reference in references:
            if path_exists_on_this_platform(reference.value):
                result.unchanged += 1
                continue
            replacement, ambiguous = find_file_match(
                reference.value, index, case_sensitive=case_sensitive
            )
            if replacement:
                reference.parent[reference.key] = normalized_output_path(replacement)
                result.changed += 1
            elif ambiguous:
                result.ambiguous.append(
                    AmbiguousMatch(reference.source_name, reference.value, ambiguous)
                )
            else:
                result.missing.append(
                    f"{reference.source_name}: {portable_filename(reference.value)}"
                    + (
                        f" (expected folder: {portable_parent_name(reference.value)})"
                        if portable_parent_name(reference.value)
                        else ""
                    )
                )

        if result.ambiguous or (strict and result.missing):
            return result

        output_path = next_output_path(collection_path)
        atomic_write_json(output_path, converted)
        result.output_path = output_path
        result.success = True
        return result
    except UtilityError as exc:
        result.error = str(exc)
        return result
