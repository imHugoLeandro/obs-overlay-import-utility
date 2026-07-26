"""Automatic overlay-package detection and OBS collection installation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .core import (
    atomic_write_json,
    convert_collection,
    find_scene_collections,
    install_scene_collection,
    load_json,
    resize_scene_collection,
)
from .models import ConversionResult, UtilityError
from .obs_profile import active_profile_canvas
from .streamlabs import StreamlabsImportResult, find_streamlabs_packages, import_streamlabs_overlay


@dataclass
class AutomaticImportResult:
    """Summary of one automatically detected package import."""

    kind: str = ""
    success: bool = False
    collection_name: str = ""
    collection_path: Path | None = None
    extraction_path: Path | None = None
    canvas_width: int | None = None
    canvas_height: int | None = None
    profile_name: str | None = None
    conversion: ConversionResult | None = None
    streamlabs: StreamlabsImportResult | None = None
    error: str | None = None


def automatically_import_overlay(
    overlay_root: Path,
    obs_scenes_directory: Path,
    *,
    strict: bool = True,
    case_sensitive: bool = True,
) -> AutomaticImportResult:
    """Detect one supported pack, favoring manifest, then OBS export, then Streamlabs."""
    result = AutomaticImportResult()
    try:
        overlay_root = overlay_root.expanduser().resolve()
        obs_scenes_directory = obs_scenes_directory.expanduser().resolve()

        from .exporter import detect_portable_package, materialize_portable_collection

        manifest_path = detect_portable_package(overlay_root)
        if manifest_path is not None:
            collection_path = materialize_portable_collection(manifest_path, obs_scenes_directory)
            result.kind = "portable"
            result.success = True
            # Use the actual chosen collection name (filename stem) from the
            # installed collection, not the manifest's original name, which may
            # have been suffixed to avoid a collision.
            result.collection_name = collection_path.stem
            result.collection_path = collection_path
            return result

        # An OBS export has the most complete source and transform information, so use
        # it when a pack includes both its original JSON and a Streamlabs package.
        collections = find_scene_collections(overlay_root)
        if len(collections) > 1:
            raise UtilityError(
                "Found more than one OBS scene collection export. Use Fix Scene Collection Paths instead."
            )
        if collections:
            conversion = convert_collection(
                collections[0], overlay_root, strict=strict, case_sensitive=case_sensitive
            )
            result.kind = "obs"
            result.conversion = conversion
            if not conversion.success or not conversion.output_path:
                result.error = conversion.error or "The OBS collection could not be prepared safely."
                return result

            profile_canvas = active_profile_canvas(obs_scenes_directory)
            if profile_canvas:
                converted = load_json(conversion.output_path)
                resize_scene_collection(converted, profile_canvas.width, profile_canvas.height)
                atomic_write_json(conversion.output_path, converted)
                result.canvas_width = profile_canvas.width
                result.canvas_height = profile_canvas.height
                result.profile_name = profile_canvas.profile_name

            collection_name, collection_path = install_scene_collection(
                conversion.output_path, obs_scenes_directory
            )
            result.success = True
            result.collection_name = collection_name
            result.collection_path = collection_path
            return result

        packages = find_streamlabs_packages(overlay_root)
        if len(packages) != 1:
            if not packages:
                raise UtilityError("No OBS scene collection export or Streamlabs .overlay file was found.")
            raise UtilityError(
                "Found more than one Streamlabs .overlay file. Use Import Streamlabs Scene File instead."
            )
        streamlabs = import_streamlabs_overlay(packages[0], obs_scenes_directory)
        result.kind = "streamlabs"
        result.streamlabs = streamlabs
        result.success = streamlabs.success
        result.collection_name = streamlabs.collection_name
        result.collection_path = streamlabs.collection_path
        result.extraction_path = streamlabs.extraction_path
        result.canvas_width = streamlabs.canvas_width
        result.canvas_height = streamlabs.canvas_height
        result.profile_name = streamlabs.profile_name
        result.error = streamlabs.error
        return result
    except UtilityError as exc:
        result.error = str(exc)
        return result