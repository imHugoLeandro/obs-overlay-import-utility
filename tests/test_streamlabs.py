from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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


if __name__ == "__main__":
    unittest.main()
