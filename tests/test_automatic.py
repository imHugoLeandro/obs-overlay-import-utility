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

    def test_portable_import_collision_sets_name_and_collection_name(self) -> None:
        """Importing the same portable package twice must:
        - name the second file with a collision suffix;
        - set the second JSON's "name" to match its filename stem;
        - set AutomaticImportResult.collection_name to the second installed name."""
        from obs_overlay_import_utility.exporter import (
            build_export_plan,
            export_scene_collection,
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            asset = root / "bg.png"
            asset.write_bytes(b"image")
            data = {
                "name": "CollidingPack",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(asset)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "CollidingPack.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            plan = build_export_plan(cp, dest, compressed=False)
            r = export_scene_collection(cp, dest, compressed=False, plan=plan)
            self.assertTrue(r.success, r.error)
            self.assertIsNotNone(r.package_path)
            package_path = r.package_path
            assert package_path is not None  # for type checker

            scenes_dir = root / "obs-scenes"
            scenes_dir.mkdir()

            # First import
            first = automatically_import_overlay(package_path, scenes_dir)
            self.assertTrue(first.success, first.error)
            self.assertEqual(first.kind, "portable")
            self.assertEqual(first.collection_name, "CollidingPack")
            self.assertTrue(first.collection_path.is_file())

            # Second import — must collide
            second = automatically_import_overlay(package_path, scenes_dir)
            self.assertTrue(second.success, second.error)
            self.assertEqual(second.kind, "portable")

            # Second file must have a collision suffix in its filename
            self.assertNotEqual(first.collection_path, second.collection_path)
            self.assertTrue(
                second.collection_path.stem.startswith("CollidingPack"),
                f"second collection stem should start with CollidingPack, got: {second.collection_path.stem}",
            )
            self.assertNotEqual(
                second.collection_path.stem, "CollidingPack",
                "second collection should have a collision suffix",
            )

            # Second JSON's "name" must match its filename stem
            second_data = json.loads(second.collection_path.read_text(encoding="utf-8"))
            self.assertEqual(second_data["name"], second.collection_path.stem)

            # AutomaticImportResult.collection_name must match the second installed name
            self.assertEqual(second.collection_name, second.collection_path.stem)
            self.assertNotEqual(second.collection_name, "CollidingPack")


if __name__ == "__main__":
    unittest.main()
