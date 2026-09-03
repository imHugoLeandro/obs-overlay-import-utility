"""Detect and configure portable OBS device sources after collection import."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import atomic_write_json, is_obs_scene_collection_data, load_json
from .exporter import list_obs_scene_collections
from .models import UtilityError


VIDEO_SOURCE_IDS = frozenset(
    {"av_capture_input", "dshow_input", "decklink-input", "v4l2_input"}
)
AUDIO_SOURCE_IDS = frozenset(
    {
        "wasapi_input_capture",
        "wasapi_output_capture",
        "coreaudio_input_capture",
        "coreaudio_output_capture",
        "pulse_input_capture",
        "pulse_output_capture",
        "jack_input_capture",
    }
)
DISPLAY_SOURCE_IDS = frozenset(
    {
        "monitor_capture",
        "display_capture",
        "window_capture",
        "game_capture",
        "macos_screen_capture",
        "xshm_input",
    }
)
DEVICE_SELECTOR_KEYS = frozenset(
    {
        "audio_device_id",
        "capture_window",
        "device",
        "device_hash",
        "device_id",
        "device_name",
        "display",
        "display_uuid",
        "input_device_id",
        "monitor",
        "monitor_id",
        "output_device_id",
        "screen",
        "screen_id",
        "video_device_id",
        "window",
        "window_id",
    }
)


@dataclass(frozen=True)
class DeviceRequirement:
    key: str
    name: str
    source_id: str
    kind: str


@dataclass(frozen=True)
class DeviceCandidate:
    label: str
    source_id: str
    kind: str
    settings: dict[str, Any]


def device_kind(source_id: Any, settings: Any = None) -> str | None:
    """Classify the portable device sources supported by this setup wizard."""
    if not isinstance(source_id, str):
        return None
    normalized = source_id.casefold()
    if normalized in VIDEO_SOURCE_IDS:
        return "Camera or capture device"
    if normalized in AUDIO_SOURCE_IDS:
        return "Audio device"
    if normalized in DISPLAY_SOURCE_IDS:
        return "Display, window, or game capture"
    if isinstance(settings, dict) and any(
        key in settings for key in DEVICE_SELECTOR_KEYS
    ):
        return "Other device source"
    return None


def device_requirements(data: Any) -> list[DeviceRequirement]:
    """Find imported sources that need a device-specific setup on this computer."""
    if not is_obs_scene_collection_data(data):
        return []
    requirements: list[DeviceRequirement] = []
    for index, source in enumerate(data.get("sources", [])):
        if not isinstance(source, dict):
            continue
        kind = device_kind(source.get("id"), source.get("settings"))
        name = source.get("name")
        if not kind or not isinstance(name, str):
            continue
        uuid = source.get("uuid")
        key = str(uuid) if isinstance(uuid, str) and uuid else f"{index}:{name}"
        requirements.append(
            DeviceRequirement(key=key, name=name, source_id=source["id"], kind=kind)
        )
    return requirements


def collection_device_requirements(collection_path: Path) -> list[DeviceRequirement]:
    """Load one imported collection and return its configurable device sources."""
    data = load_json(collection_path)
    if not is_obs_scene_collection_data(data):
        raise UtilityError("The imported collection is not a recognized OBS scene collection.")
    return device_requirements(data)


def available_device_candidates(
    obs_scenes_directory: Path, *, exclude_collection: Path | None = None
) -> dict[str, list[DeviceCandidate]]:
    """Collect reusable local settings grouped by exact OBS source ID."""
    candidates: dict[str, list[DeviceCandidate]] = {}
    excluded = exclude_collection.expanduser().resolve() if exclude_collection else None
    for collection_label, collection_path in list_obs_scene_collections(
        obs_scenes_directory
    ).items():
        if excluded and collection_path == excluded:
            continue
        try:
            data = load_json(collection_path)
        except UtilityError:
            continue
        for source in data.get("sources", []):
            if not isinstance(source, dict):
                continue
            kind = device_kind(source.get("id"), source.get("settings"))
            name = source.get("name")
            source_id = source.get("id")
            settings = source.get("settings")
            if (
                not kind
                or not isinstance(name, str)
                or not isinstance(source_id, str)
                or not isinstance(settings, dict)
            ):
                continue
            device_settings = {
                key: copy.deepcopy(value)
                for key, value in settings.items()
                if key in DEVICE_SELECTOR_KEYS
            }
            if not device_settings:
                continue
            label = f"{name} — {collection_label}"
            candidates.setdefault(source_id.casefold(), []).append(
                DeviceCandidate(
                    label=label,
                    source_id=source_id,
                    kind=kind,
                    settings=device_settings,
                )
            )
    for entries in candidates.values():
        entries.sort(key=lambda candidate: candidate.label.casefold())
    return candidates


def auto_apply_device_choices(
    collection_path: Path,
    obs_scenes_directory: Path,
    *,
    exclude_collection: Path | None = None,
) -> tuple[int, int]:
    """Map each device source to the single local candidate of its exact type.

    Sources with no candidate, or several equally plausible candidates, are
    left unconfigured so the user can set them up manually in OBS. Returns
    ``(auto_matched, left_unconfigured)``.
    """
    requirements = collection_device_requirements(collection_path)
    if not requirements:
        return 0, 0
    candidates = available_device_candidates(
        obs_scenes_directory, exclude_collection=exclude_collection
    )
    choices: dict[str, DeviceCandidate | None | str] = {}
    for requirement in requirements:
        entries = candidates.get(requirement.source_id.casefold(), [])
        if len(entries) == 1:
            choices[requirement.key] = entries[0]
    if choices:
        error = apply_device_choices(collection_path, choices)
        if error:
            raise UtilityError(error)
    return len(choices), len(requirements) - len(choices)


def apply_device_choices(
    collection_path: Path, choices: dict[str, DeviceCandidate | None | str]
) -> str | None:
    """Apply selected local-device settings to an imported collection atomically."""
    try:
        collection_path = collection_path.expanduser().resolve()
        data = load_json(collection_path)
        if not is_obs_scene_collection_data(data):
            raise UtilityError(
                "The imported collection is not a recognized OBS scene collection."
            )
        for index, source in enumerate(data.get("sources", [])):
            if not isinstance(source, dict):
                continue
            uuid = source.get("uuid")
            name = source.get("name")
            key = str(uuid) if isinstance(uuid, str) and uuid else f"{index}:{name}"
            choice = choices.get(key)
            if choice is None:
                continue
            if choice == "disable":
                source["enabled"] = False
                continue
            if not isinstance(choice, DeviceCandidate):
                continue
            source_id = source.get("id")
            if (
                not isinstance(source_id, str)
                or source_id.casefold() != choice.source_id.casefold()
            ):
                raise UtilityError(
                    f"{choice.label} is not compatible with the imported source {name}."
                )
            settings = source.get("settings")
            if not isinstance(settings, dict):
                settings = {}
                source["settings"] = settings
            for setting_name, setting_value in choice.settings.items():
                if setting_name in DEVICE_SELECTOR_KEYS:
                    settings[setting_name] = copy.deepcopy(setting_value)
            source["enabled"] = True
        atomic_write_json(collection_path, data)
        return None
    except (OSError, UtilityError) as exc:
        return (
            str(exc)
            if isinstance(exc, UtilityError)
            else f"Could not apply device setup: {exc}"
        )
