"""Resize the active OBS collection through obs-websocket without reloading OBS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import UtilityError
from .obs_live import ObsLiveError, ObsWebSocketClient
from .resizer import (
    MODE_SCALE_RATIO,
    MODE_STRETCH,
    SCOPE_COLLECTION,
    SCOPE_SCENE,
    SCOPE_SOURCE,
    ResizeResult,
)


@dataclass(frozen=True)
class LiveTransformBackup:
    scene_name: str
    scene_item_id: int
    transform: dict[str, Any]


@dataclass(frozen=True)
class LiveResizeSnapshot:
    collection_name: str
    transforms: tuple[LiveTransformBackup, ...]
    video_settings: dict[str, Any] | None


@dataclass(frozen=True)
class LiveResizeOutcome:
    result: ResizeResult
    snapshot: LiveResizeSnapshot | None = None


def _changed_transform(
    transform: dict[str, Any], factor_x: float, factor_y: float, offset_x: float, offset_y: float
) -> dict[str, float]:
    changed = {
        "positionX": float(transform.get("positionX", 0.0)) * factor_x + offset_x,
        "positionY": float(transform.get("positionY", 0.0)) * factor_y + offset_y,
    }
    bounds_type = transform.get("boundsType")
    if bounds_type not in {None, "OBS_BOUNDS_NONE"}:
        changed["boundsWidth"] = float(transform.get("boundsWidth", 0.0)) * factor_x
        changed["boundsHeight"] = float(transform.get("boundsHeight", 0.0)) * factor_y
    else:
        changed["scaleX"] = float(transform.get("scaleX", 1.0)) * factor_x
        changed["scaleY"] = float(transform.get("scaleY", 1.0)) * factor_y
    return changed


def resize_active_collection(
    *,
    password: str | None,
    collection_name: str,
    scope: str,
    selected_name: str | None,
    selected_uuid: str | None,
    mode: str,
    target_width: int,
    target_height: int,
) -> LiveResizeOutcome:
    """Apply and persist a resize directly to the collection loaded by OBS."""
    result = ResizeResult()
    applied: list[LiveTransformBackup] = []
    original_video: dict[str, Any] | None = None
    try:
        if scope not in {SCOPE_COLLECTION, SCOPE_SCENE, SCOPE_SOURCE}:
            raise UtilityError("Choose a valid resize scope.")
        if mode not in {MODE_STRETCH, MODE_SCALE_RATIO}:
            raise UtilityError("Choose Stretch or Scale Ratio.")
        if not (16 <= target_width <= 32768 and 16 <= target_height <= 32768):
            raise UtilityError("Choose a target size between 16 and 32768 pixels.")
        with ObsWebSocketClient(password=password) as client:
            current, _collections = client.scene_collections()
            if current != collection_name:
                raise UtilityError(
                    f'OBS is using "{current}", not the selected collection "{collection_name}".'
                )
            video = client.request("GetVideoSettings")
            source_width = int(video.get("baseWidth", 0))
            source_height = int(video.get("baseHeight", 0))
            if source_width < 16 or source_height < 16:
                raise UtilityError("OBS returned an invalid active canvas size.")
            factor_x = target_width / source_width
            factor_y = target_height / source_height
            offset_x = offset_y = 0.0
            if mode == MODE_SCALE_RATIO:
                factor_x = factor_y = min(factor_x, factor_y)
                offset_x = (target_width - source_width * factor_x) / 2
                offset_y = (target_height - source_height * factor_y) / 2

            scenes_data = client.request("GetSceneList").get("scenes", [])
            scenes = [str(item.get("sceneName")) for item in scenes_data if isinstance(item, dict)]
            contexts: list[tuple[str, str]] = [(name, "GetSceneItemList") for name in scenes]
            if scope in {SCOPE_COLLECTION, SCOPE_SOURCE}:
                groups = client.request("GetGroupList").get("groups", [])
                contexts.extend((str(name), "GetGroupSceneItemList") for name in groups)
            if scope == SCOPE_SCENE:
                if not selected_name or selected_name not in scenes:
                    raise UtilityError("The selected scene is not available in live OBS.")
                contexts = [(selected_name, "GetSceneItemList")]

            pending: list[tuple[LiveTransformBackup, dict[str, float]]] = []
            for context_name, request_type in contexts:
                response = client.request(request_type, {"sceneName": context_name})
                for item in response.get("sceneItems", []):
                    if not isinstance(item, dict):
                        continue
                    if scope == SCOPE_SOURCE and item.get("sourceUuid") != selected_uuid:
                        continue
                    transform = item.get("sceneItemTransform")
                    item_id = item.get("sceneItemId")
                    if not isinstance(transform, dict) or not isinstance(item_id, int):
                        continue
                    backup = LiveTransformBackup(context_name, item_id, dict(transform))
                    pending.append((backup, _changed_transform(
                        transform, factor_x, factor_y, offset_x, offset_y
                    )))
            if not pending:
                raise UtilityError("The selected scene or source has no resizable live items.")

            for backup, transform in pending:
                client.request("SetSceneItemTransform", {
                    "sceneName": backup.scene_name,
                    "sceneItemId": backup.scene_item_id,
                    "sceneItemTransform": transform,
                })
                applied.append(backup)
            if scope == SCOPE_COLLECTION:
                original_video = {
                    key: video[key]
                    for key in (
                        "fpsNumerator", "fpsDenominator", "baseWidth", "baseHeight",
                        "outputWidth", "outputHeight",
                    )
                    if key in video
                }
                client.request("SetVideoSettings", {
                    "baseWidth": target_width,
                    "baseHeight": target_height,
                })

            result.success = True
            result.changed_items = len(applied)
            result.source_width = source_width
            result.source_height = source_height
            result.target_width = target_width
            result.target_height = target_height
            result.canvas_changed = scope == SCOPE_COLLECTION
            result.live = True
            return LiveResizeOutcome(result, LiveResizeSnapshot(
                collection_name, tuple(applied), original_video
            ))
    except (ObsLiveError, UtilityError, OSError, ValueError, TypeError) as exc:
        if applied:
            try:
                with ObsWebSocketClient(password=password) as rollback:
                    for backup in reversed(applied):
                        rollback.request("SetSceneItemTransform", {
                            "sceneName": backup.scene_name,
                            "sceneItemId": backup.scene_item_id,
                            "sceneItemTransform": backup.transform,
                        })
            except ObsLiveError:
                pass
        result.error = str(exc)
        return LiveResizeOutcome(result)


def undo_live_resize(password: str | None, snapshot: LiveResizeSnapshot) -> str | None:
    """Restore a live resize snapshot in the current OBS session."""
    try:
        with ObsWebSocketClient(password=password) as client:
            current, _collections = client.scene_collections()
            if current != snapshot.collection_name:
                raise UtilityError(
                    f'Switch OBS back to "{snapshot.collection_name}" before using Undo.'
                )
            for backup in reversed(snapshot.transforms):
                client.request("SetSceneItemTransform", {
                    "sceneName": backup.scene_name,
                    "sceneItemId": backup.scene_item_id,
                    "sceneItemTransform": backup.transform,
                })
            if snapshot.video_settings:
                client.request("SetVideoSettings", snapshot.video_settings)
        return None
    except (ObsLiveError, UtilityError) as exc:
        return str(exc)
