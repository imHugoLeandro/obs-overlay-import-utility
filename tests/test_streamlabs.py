from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility import streamlabs  # noqa: E402
from obs_overlay_import_utility.streamlabs import import_streamlabs_overlay  # noqa: E402


def sample_config() -> dict:
    return {
        "schemaVersion": 2,
        "nodeType": "RootNode",
        "scenes": {
            "items": [
                {
                    "name": "Starting Soon",
                    "sceneId": "scene-start",
                    "slots": {
                        "items": [
                            {
                                "name": "Background",
                                "x": 0,
                                "y": 0,
                                "scaleX": 1 / 2560,
                                "scaleY": 1 / 1440,
                                "visible": True,
                                "locked": False,
                                "crop": {},
                                "content": {
                                    "nodeType": "ImageNode",
                                    "filename": "background.png",
                                },
                            },
                            {
                                "name": "Camera",
                                "content": {"nodeType": "WebcamNode"},
                            },
                        ]
                    },
                }
            ]
        },
    }


class StreamlabsImportTests(unittest.TestCase):
    def _write_package(self, root: Path, name: str = "Demo.overlay") -> Path:
        package = root / name
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("config.json", json.dumps(sample_config()))
            archive.writestr("background.png", b"image")
        return package

    def _write_active_profile(self, scenes: Path, width: int, height: int) -> None:
        config = scenes.parent.parent
        (config / "basic" / "profiles" / "Streaming").mkdir(parents=True, exist_ok=True)
        (config / "user.ini").write_text("[Basic]\nProfile=Streaming\nProfileDir=Streaming\n", encoding="utf-8")
        (config / "basic" / "profiles" / "Streaming" / "basic.ini").write_text(
            f"[Video]\nBaseCX={width}\nBaseCY={height}\n", encoding="utf-8"
        )

    def test_extracts_converts_and_installs_unique_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            package = self._write_package(root)

            first = import_streamlabs_overlay(package, scenes)
            second = import_streamlabs_overlay(package, scenes)

            self.assertTrue(first.success, first.error)
            self.assertEqual(first.collection_name, "Demo")
            self.assertEqual(second.collection_name, "Demo 1")
            self.assertTrue((root / "Demo overlay" / "background.png").is_file())
            converted = json.loads(first.collection_path.read_text(encoding="utf-8"))
            self.assertEqual(converted["name"], "Demo")
            self.assertEqual(converted["scene_order"], [{"name": "Starting Soon"}])
            image_source = next(source for source in converted["sources"] if source["id"] == "image_source")
            self.assertEqual(image_source["settings"]["file"], str((root / "Demo overlay" / "background.png").resolve()))
            self.assertEqual(first.skipped_sources, [])
            camera_source = next(source for source in converted["sources"] if source["id"] == "av_capture_input")
            self.assertEqual(camera_source["settings"], {"device_id": ""})

    def test_uses_active_obs_profile_canvas_and_nested_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            self._write_active_profile(scenes, 1920, 1080)
            package = root / "Nested.overlay"
            config = sample_config()
            config["scenes"]["items"][0]["slots"]["items"][0]["content"]["filename"] = "assets/background.png"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("config.json", json.dumps(config))
                archive.writestr("assets/background.png", b"image")

            result = import_streamlabs_overlay(package, scenes)

            self.assertTrue(result.success, result.error)
            self.assertEqual((result.canvas_width, result.canvas_height, result.profile_name), (1920, 1080, "Streaming"))
            converted = json.loads(result.collection_path.read_text(encoding="utf-8"))
            self.assertEqual(converted["resolution"], {"x": 1920, "y": 1080})
            scene = next(source for source in converted["sources"] if source["id"] == "scene")
            item = scene["settings"]["items"][0]
            self.assertEqual(item["scale_ref"], {"x": 1920.0, "y": 1080.0})
            self.assertEqual(item["scale"], {"x": 0.75, "y": 0.75})
            image_source = next(source for source in converted["sources"] if source["id"] == "image_source")
            self.assertEqual(
                image_source["settings"]["file"],
                str((root / "Nested overlay" / "assets" / "background.png").resolve()),
            )
    def test_rejects_unsafe_archive_paths_without_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "Unsafe.overlay"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("../outside.txt", "nope")
                archive.writestr("config.json", json.dumps(sample_config()))

            result = import_streamlabs_overlay(package, root / "scenes")

            self.assertFalse(result.success)
            self.assertIn("unsafe file path", result.error)
            self.assertFalse((root / "outside.txt").exists())


    def test_rejects_backslash_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "Unsafe.overlay"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("..\\outside.txt", "nope")
                archive.writestr("config.json", json.dumps(sample_config()))
            result = import_streamlabs_overlay(package, root / "scenes")
            self.assertFalse(result.success)
            self.assertIn("unsafe file path", result.error)
            self.assertFalse((root / "outside.txt").exists())

    def test_rejects_archive_entry_and_member_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = self._write_package(root)
            with mock.patch.object(streamlabs, "MAX_ARCHIVE_FILES", 1):
                entry_result = import_streamlabs_overlay(package, root / "entry-scenes")
            with mock.patch.object(streamlabs, "MAX_ARCHIVE_MEMBER_SIZE", 1):
                size_result = import_streamlabs_overlay(package, root / "size-scenes")
            self.assertFalse(entry_result.success)
            self.assertIn("more than 1 entries", entry_result.error)
            self.assertFalse(size_result.success)
            self.assertIn("too large", size_result.error)

    def test_rejects_unsafe_compression_ratio_and_low_disk_space(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "Compressed.overlay"
            with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("config.json", json.dumps(sample_config()) + " " * 4096)
            with (
                mock.patch.object(streamlabs, "MIN_RATIO_CHECK_SIZE", 1),
                mock.patch.object(streamlabs, "MAX_COMPRESSION_RATIO", 1),
            ):
                ratio_result = import_streamlabs_overlay(package, root / "ratio-scenes")
            with mock.patch.object(
                streamlabs.shutil, "disk_usage", return_value=SimpleNamespace(free=0)
            ):
                disk_result = import_streamlabs_overlay(package, root / "disk-scenes")
            self.assertFalse(ratio_result.success)
            self.assertIn("compression ratio", ratio_result.error)
            self.assertFalse(disk_result.success)
            self.assertIn("free disk space", disk_result.error)

    def test_collection_publish_failure_rolls_back_extracted_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            package = self._write_package(root)
            real_replace = streamlabs.os.replace

            def fail_collection_publish(source: object, destination: object) -> None:
                if str(source).endswith(".pending"):
                    raise OSError("blocked collection publish")
                real_replace(source, destination)

            with mock.patch.object(
                streamlabs.os, "replace", side_effect=fail_collection_publish
            ):
                result = import_streamlabs_overlay(package, scenes)

            self.assertFalse(result.success)
            self.assertIn("blocked collection publish", result.error)
            self.assertFalse((root / "Demo overlay").exists())
            self.assertEqual(list(scenes.glob("*.json")), [])
            self.assertEqual(list(scenes.glob("*.pending")), [])

    def test_recursively_relinks_custom_source_and_filter_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            package = root / "Custom.overlay"
            config = sample_config()
            custom = {
                "name": "Plugin widget",
                "content": {
                    "nodeType": "CustomNode",
                    "sourceId": "vendor.plugin.source",
                    "settings": {
                        "nested": [{"asset": "assets/widget.dat"}],
                        "remote": "https://example.com/widget.dat",
                    },
                },
                "filters": [
                    {
                        "name": "Plugin filter",
                        "type": "vendor.plugin.filter",
                        "settings": {"nested": {"lut": "assets/filter.dat"}},
                    }
                ],
            }
            config["scenes"]["items"][0]["slots"]["items"].append(custom)
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("config.json", json.dumps(config))
                archive.writestr("background.png", b"image")
                archive.writestr("assets/widget.dat", b"widget")
                archive.writestr("assets/filter.dat", b"filter")

            result = import_streamlabs_overlay(package, scenes)

            self.assertTrue(result.success, result.error)
            converted = json.loads(result.collection_path.read_text(encoding="utf-8"))
            source = next(
                item for item in converted["sources"] if item["id"] == "vendor.plugin.source"
            )
            extracted = root / "Custom overlay" / "assets"
            self.assertEqual(
                source["settings"]["nested"][0]["asset"],
                str((extracted / "widget.dat").resolve()),
            )
            self.assertEqual(
                source["settings"]["remote"], "https://example.com/widget.dat"
            )
            self.assertEqual(
                source["filters"][0]["settings"]["nested"]["lut"],
                str((extracted / "filter.dat").resolve()),
            )
    def test_malformed_scene_item_numbers_fall_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            package = root / "Numbers.overlay"
            config = sample_config()
            item = config["scenes"]["items"][0]["slots"]["items"][0]
            item["scaleX"] = "auto"
            item["scaleY"] = "auto"
            item["rotation"] = "sideways"
            item["crop"] = {"left": "wide"}
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("config.json", json.dumps(config))
                archive.writestr("background.png", b"image")

            result = import_streamlabs_overlay(package, scenes)

            self.assertTrue(result.success, result.error)
            converted = json.loads(result.collection_path.read_text(encoding="utf-8"))
            scene = next(source for source in converted["sources"] if source["id"] == "scene")
            item = scene["settings"]["items"][0]
            self.assertEqual(item["rot"], 0.0)
            self.assertEqual(item["crop_left"], 0)
            self.assertEqual(item["scale"], {"x": 1.0, "y": 1.0})

    def test_id_counter_is_above_every_scene_item_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            package = self._write_package(root)

            result = import_streamlabs_overlay(package, scenes)

            self.assertTrue(result.success, result.error)
            converted = json.loads(result.collection_path.read_text(encoding="utf-8"))
            for source in converted["sources"]:
                if source["id"] != "scene":
                    continue
                items = source["settings"]["items"]
                max_item_id = max((item["id"] for item in items), default=0)
                self.assertGreater(source["settings"]["id_counter"], max_item_id)

    def test_image_filename_inside_settings_is_relinked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            package = root / "SettingsFile.overlay"
            config = sample_config()
            content = config["scenes"]["items"][0]["slots"]["items"][0]["content"]
            del content["filename"]
            content["settings"] = {"file": "assets/background.png"}
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("config.json", json.dumps(config))
                archive.writestr("assets/background.png", b"image")

            result = import_streamlabs_overlay(package, scenes)

            self.assertTrue(result.success, result.error)
            converted = json.loads(result.collection_path.read_text(encoding="utf-8"))
            image_source = next(
                source for source in converted["sources"] if source["id"] == "image_source"
            )
            expected = str(
                (root / "SettingsFile overlay" / "assets" / "background.png").resolve()
            )
            self.assertEqual(image_source["settings"]["file"], expected)

    def test_extraction_folder_uses_windows_safe_stem(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            package = root / "My:Overlay.overlay"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("config.json", json.dumps(sample_config()))
                archive.writestr("background.png", b"image")

            result = import_streamlabs_overlay(package, scenes)

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.collection_name, "My Overlay")
            self.assertEqual(result.extraction_path.name, "My Overlay overlay")
            self.assertNotIn(":", result.extraction_path.name)
            self.assertTrue((result.extraction_path / "background.png").is_file())

    def test_scale_to_canvas_off_keeps_streamlabs_canvas(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            self._write_active_profile(scenes, 1920, 1080)
            package = self._write_package(root, name="NoScale.overlay")

            result = import_streamlabs_overlay(
                package, scenes, scale_to_canvas=False
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(
                (result.canvas_width, result.canvas_height, result.profile_name),
                (2560, 1440, None),
            )
            converted = json.loads(result.collection_path.read_text(encoding="utf-8"))
            self.assertEqual(converted["resolution"], {"x": 2560, "y": 1440})

    def test_scale_to_canvas_fits_aspect_uniformly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            self._write_active_profile(scenes, 1600, 1200)
            package = root / "Fit.overlay"
            config = sample_config()
            config["scenes"]["items"][0]["slots"]["items"][0]["y"] = 1
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("config.json", json.dumps(config))
                archive.writestr("background.png", b"image")

            result = import_streamlabs_overlay(package, scenes, scale_to_canvas=True)

            self.assertTrue(result.success, result.error)
            self.assertEqual((result.canvas_width, result.canvas_height), (1600, 1200))
            converted = json.loads(result.collection_path.read_text(encoding="utf-8"))
            scene = next(source for source in converted["sources"] if source["id"] == "scene")
            item = scene["settings"]["items"][0]
            # 16:9 layout fits inside the 4:3 canvas at uniform 0.625 scale.
            self.assertEqual(item["scale_ref"], {"x": 1600.0, "y": 900.0})
            self.assertEqual(item["scale"], {"x": 0.625, "y": 0.625})
            self.assertEqual(item["pos"], {"x": 0.0, "y": 900.0})

    def test_display_node_imports_as_monitor_capture_without_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            package = root / "Screen.overlay"
            config = sample_config()
            config["scenes"]["items"][0]["slots"]["items"].append(
                {"name": "Monitor", "content": {"nodeType": "DisplayNode"}}
            )
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("config.json", json.dumps(config))
                archive.writestr("background.png", b"image")

            result = import_streamlabs_overlay(package, scenes)

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.skipped_sources, [])
            converted = json.loads(result.collection_path.read_text(encoding="utf-8"))
            monitor = next(
                source for source in converted["sources"] if source["id"] == "monitor_capture"
            )
            self.assertEqual(monitor["name"], "Monitor")

    def test_streamlabs_filters_convert_to_obs_and_preserve_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            package = root / "Filters.overlay"
            config = sample_config()
            config["scenes"]["items"][0]["slots"]["items"][0]["filters"] = [
                {
                    "name": "Green key",
                    "type": "ChromaKeyFilter",
                    "settings": {"similarity": 400},
                    "enabled": False,
                },
                {
                    "type": "vendor.plugin.filter",
                    "settings": {"lut": "assets/filter.dat"},
                },
            ]
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("config.json", json.dumps(config))
                archive.writestr("background.png", b"image")
                archive.writestr("assets/filter.dat", b"lut")

            result = import_streamlabs_overlay(package, scenes)

            self.assertTrue(result.success, result.error)
            converted = json.loads(result.collection_path.read_text(encoding="utf-8"))
            image_source = next(
                source for source in converted["sources"] if source["id"] == "image_source"
            )
            key, plugin = image_source["filters"]
            self.assertEqual(key["id"], "chroma_key_filter_v2")
            self.assertEqual(key["settings"], {"similarity": 400})
            self.assertFalse(key["enabled"])
            self.assertEqual(plugin["id"], "vendor.plugin.filter")
            self.assertTrue(plugin["enabled"])
            self.assertEqual(
                plugin["settings"]["lut"],
                str((root / "Filters overlay" / "assets" / "filter.dat").resolve()),
            )

    def test_unexpected_conversion_failure_returns_error_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            package = self._write_package(root)

            def boom(*args: object, **kwargs: object) -> dict:
                raise ValueError("malformed item")

            with mock.patch.object(streamlabs, "_scene_item", side_effect=boom):
                result = import_streamlabs_overlay(package, scenes)

            self.assertFalse(result.success)
            self.assertIn("Could not import the Streamlabs package", result.error)
            self.assertFalse((root / "Demo overlay").exists())
            self.assertEqual(list(scenes.glob("*.json")), [])
            self.assertEqual(list(scenes.glob("*.pending")), [])


if __name__ == "__main__":
    unittest.main()
