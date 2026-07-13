from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility.automatic import automatically_import_overlay  # noqa: E402


def obs_collection(path: str) -> dict:
    return {
        "name": "Imported Pack",
        "current_scene": "Main",
        "scene_order": [{"name": "Main"}],
        "resolution": {"x": 2560, "y": 1440},
        "sources": [{"name": "Image", "settings": {"file": path}}],
    }


def streamlabs_config() -> dict:
    return {
        "nodeType": "RootNode",
        "scenes": {
            "items": [
                {
                    "name": "Main",
                    "sceneId": "main",
                    "slots": {
                        "items": [
                            {
                                "name": "Background",
                                "content": {"nodeType": "ImageNode", "filename": "background.png"},
                            }
                        ]
                    },
                }
            ]
        },
    }


class AutomaticImportTests(unittest.TestCase):
    def test_detects_obs_export_and_installs_it_in_obs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            asset = root / "background.png"
            asset.write_bytes(b"image")
            (root / "collection.json").write_text(
                json.dumps(obs_collection(r"C:\seller\background.png")), encoding="utf-8"
            )

            result = automatically_import_overlay(root, root / "obs-scenes")

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.kind, "obs")
            self.assertTrue(result.collection_path.is_file())
            installed = json.loads(result.collection_path.read_text(encoding="utf-8"))
            self.assertEqual(installed["name"], "Imported Pack")
            self.assertEqual(installed["sources"][0]["settings"]["file"], str(asset.resolve()))

    def test_prefers_obs_export_when_pack_contains_both_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            asset = root / "background.png"
            asset.write_bytes(b"image")
            (root / "collection.json").write_text(
                json.dumps(obs_collection(r"C:\\seller\\background.png")), encoding="utf-8"
            )
            with zipfile.ZipFile(root / "pack.overlay", "w") as archive:
                archive.writestr("config.json", json.dumps(streamlabs_config()))
                archive.writestr("background.png", b"image")
            scenes = root / "obs" / "basic" / "scenes"
            config = scenes.parent.parent
            (config / "basic" / "profiles" / "Streaming").mkdir(parents=True)
            (config / "user.ini").write_text("[Basic]\nProfileDir=Streaming\n", encoding="utf-8")
            (config / "basic" / "profiles" / "Streaming" / "basic.ini").write_text(
                "[Video]\nBaseCX=1920\nBaseCY=1080\n", encoding="utf-8"
            )

            result = automatically_import_overlay(root, scenes)

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.kind, "obs")
            self.assertIsNone(result.extraction_path)
            self.assertEqual((result.canvas_width, result.canvas_height), (1920, 1080))
            installed = json.loads(result.collection_path.read_text(encoding="utf-8"))
            self.assertEqual(installed["resolution"], {"x": 1920, "y": 1080})


if __name__ == "__main__":
    unittest.main()
