"""Resize OBS collection, scene, or source transforms with undoable backups."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import atomic_write_json, is_obs_scene_collection_data, load_json
from .models import UtilityError


SCOPE_COLLECTION = "Collection"
SCOPE_SCENE = "Scene"
SCOPE_SOURCE = "Source"
MODE_STRETCH = "Stretch"
MODE_SCALE_RATIO = "Scale Ratio"


@dataclass
class ResizeResult:
    """Summary of an overwrite-safe resize operation."""

    success: bool = False
    collection_path: Path | None = None
    backup_path: Path | None = None
    changed_items: int = 0
    source_width: int = 0
    source_height: int = 0
    target_width: int = 0
    target_height: int = 0
    canvas_changed: bool = False
    error: str | None = None


def scene_names(data: Any) -> list[str]:
    """Return scene names from an OBS scene collection."""
    if not is_obs_scene_collection_data(data):
        return []
    return [
        source["name"]
        for source in data.get("sources", [])
        if isinstance(source, dict)
        and source.get("id") == "scene"
        and isinstance(source.get("name"), str)
    ]


def source_names(data: Any) -> list[str]:
    """Return non-scene source names that can appear in scene item transforms."""
    if not is_obs_scene_collection_data(data):
        return []
    return [
        source["name"]
        for source in data.get("sources", [])
        if isinstance(source, dict)
        and source.get("id") != "scene"
        and isinstance(source.get("name"), str)
    ]


def _canvas(data: dict[str, Any]) -> tuple[int, int]:
    resolution = data.get("resolution")
    width = resolution.get("x") if isinstance(resolution, dict) else None
    height = resolution.get("y") if isinstance(resolution, dict) else None
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        raise UtilityError("This collection has no usable canvas resolution.")
    if not (16 <= width <= 32_768 and 16 <= height <= 32_768):
        raise UtilityError("This collection has an invalid canvas resolution.")
    return int(width), int(height)


def _valid_target(width: int, height: int) -> None:
    if not (16 <= width <= 32_768 and 16 <= height <= 32_768):
        raise UtilityError(
            "Choose a target width and height between 16 and 32768 pixels."
        )


def _scene_sources(
    data: dict[str, Any], selected_scene: str | None
) -> list[dict[str, Any]]:
    scenes = [
        source
        for source in data.get("sources", [])
        if isinstance(source, dict) and source.get("id") == "scene"
    ]
    if selected_scene is None:
        return scenes
    matching = [source for source in scenes if source.get("name") == selected_scene]
    if not matching:
        raise UtilityError("The selected scene no longer exists in this collection.")
    return matching


def _scale_pair(
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


def _resize_item(
    item: dict[str, Any],
    factor_x: float,
    factor_y: float,
    offset_x: float,
    offset_y: float,
    target_width: int,
    target_height: int,
) -> None:
    _scale_pair(item.get("pos"), factor_x, factor_y, offset_x, offset_y)
    _scale_pair(item.get("scale"), factor_x, factor_y)
    _scale_pair(item.get("bounds"), factor_x, factor_y)
    item["scale_ref"] = {"x": float(target_width), "y": float(target_height)}


def _backup_path(collection_path: Path) -> Path:
    directory = collection_path.parent / ".obs-overlay-resizer-backups"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return directory / f"{collection_path.stem}-{timestamp}-{uuid.uuid4().hex[:8]}.json"


def resize_collection(
    collection_path: Path,
    *,
    scope: str,
    selected_name: str | None,
    mode: str,
    target_width: int,
    target_height: int,
) -> ResizeResult:
    """Resize selected OBS transforms, overwrite the collection, and retain an undo backup."""
    result = ResizeResult()
    try:
        collection_path = collection_path.expanduser().resolve()
        if not collection_path.is_file():
            raise UtilityError("The selected OBS scene collection no longer exists.")
        if scope not in {SCOPE_COLLECTION, SCOPE_SCENE, SCOPE_SOURCE}:
            raise UtilityError(
                "Choose whether to resize the collection, one scene, or one source."
            )
        if mode not in {MODE_STRETCH, MODE_SCALE_RATIO}:
            raise UtilityError("Choose Stretch or Scale Ratio.")
        if scope != SCOPE_COLLECTION and not selected_name:
            raise UtilityError("Choose the scene or source to resize.")
        _valid_target(target_width, target_height)
        original = load_json(collection_path)
        if not is_obs_scene_collection_data(original):
            raise UtilityError(
                "The selected JSON is not a recognized OBS scene collection."
            )
        source_width, source_height = _canvas(original)
        converted = copy.deepcopy(original)
        factor_x = target_width / source_width
        factor_y = target_height / source_height
        offset_x = 0.0
        offset_y = 0.0
        if mode == MODE_SCALE_RATIO:
            factor_x = factor_y = min(factor_x, factor_y)
            offset_x = (target_width - source_width * factor_x) / 2
            offset_y = (target_height - source_height * factor_y) / 2

        selected_scene = selected_name if scope == SCOPE_SCENE else None
        scenes = _scene_sources(converted, selected_scene)
        for scene in scenes:
            settings = scene.get("settings")
            items = settings.get("items") if isinstance(settings, dict) else None
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                if scope == SCOPE_SOURCE and item.get("name") != selected_name:
                    continue
                reference_width = (
                    target_width if scope == SCOPE_COLLECTION else source_width
                )
                reference_height = (
                    target_height if scope == SCOPE_COLLECTION else source_height
                )
                _resize_item(
                    item,
                    factor_x,
                    factor_y,
                    offset_x,
                    offset_y,
                    reference_width,
                    reference_height,
                )
                result.changed_items += 1

        if scope == SCOPE_SOURCE and result.changed_items == 0:
            raise UtilityError(
                "The selected source is not used by any scene in this collection."
            )
        if scope == SCOPE_SCENE and result.changed_items == 0:
            raise UtilityError("The selected scene has no resizable source items.")

        if scope == SCOPE_COLLECTION:
            converted["resolution"] = {"x": target_width, "y": target_height}
        backup_path = _backup_path(collection_path)
        atomic_write_json(backup_path, original)
        atomic_write_json(collection_path, converted)
        result.success = True
        result.collection_path = collection_path
        result.backup_path = backup_path
        result.source_width = source_width
        result.source_height = source_height
        result.target_width = target_width
        result.canvas_changed = scope == SCOPE_COLLECTION
        result.target_height = target_height
    except (OSError, UtilityError) as exc:
        result.error = (
            str(exc)
            if isinstance(exc, UtilityError)
            else f"Could not resize the scene collection: {exc}"
        )
    return result


def undo_resize(collection_path: Path, backup_path: Path) -> str | None:
    """Restore a resize backup and remove it only after the restore succeeds."""
    try:
        collection_path = collection_path.expanduser().resolve()
        backup_path = backup_path.expanduser().resolve()
        if not backup_path.is_file():
            raise UtilityError("The resize backup is no longer available.")
        restored = load_json(backup_path)
        if not is_obs_scene_collection_data(restored):
            raise UtilityError(
                "The resize backup is not a recognized OBS scene collection."
            )
        atomic_write_json(collection_path, restored)
        backup_path.unlink()
        return None
    except (OSError, UtilityError) as exc:
        return (
            str(exc)
            if isinstance(exc, UtilityError)
            else f"Could not undo the resize: {exc}"
        )
