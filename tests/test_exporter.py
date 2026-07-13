from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility.exporter import (  # noqa: E402
    active_obs_scene_collection,
    export_scene_collection,
    list_obs_scene_collections,
)


def collection(image: Path, plugin_file: Path, filter_file: Path) -> dict:
    return {
        "name": "Creator Pack",
        "current_scene": "Main",
        "scene_order": [{"name": "Main"}],
        "sources": [
            {
                "name": "Main",
                "id": "scene",
                "settings": {"items": []},
            },
            {
                "name": "Image",
                "id": "image_source",
                "settings": {"file": str(image)},
                "filters": [
                    {
                        "name": "Plugin filter",
                        "id": "custom.plugin.filter",
                        "settings": {"lookup_file": str(filter_file)},
                    }
                ],
            },
            {
                "name": "Custom plugin source",
                "id": "custom.plugin.source",
                "settings": {"resource_bundle": str(plugin_file), "same_image": str(image)},
            },
        ],
    }


class ExporterTests(unittest.TestCase):
    def test_exports_media_and_unknown_plugin_filter_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "source" / "background.png"
            plugin_file = root / "source" / "layout.plugin-data"
            filter_file = root / "source" / "colour.cube"
            for path in (image, plugin_file, filter_file):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(path.name.encode())
            collection_path = root / "Creator Pack.json"
            collection_path.write_text(json.dumps(collection(image, plugin_file, filter_file)), encoding="utf-8")
            destination = root / "exports"
            destination.mkdir()

            result = export_scene_collection(collection_path, destination)

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.copied_files, 3)
            self.assertEqual(result.source_references, 4)
            self.assertTrue((result.package_path / "images" / "background.png").is_file())
            self.assertTrue((result.package_path / "other resources" / "layout.plugin-data").is_file())
            self.assertTrue((result.package_path / "other resources" / "colour.cube").is_file())
            exported = json.loads(result.collection_path.read_text(encoding="utf-8"))
            source = next(item for item in exported["sources"] if item["name"] == "Custom plugin source")
            self.assertEqual(source["settings"]["same_image"], str((result.package_path / "images" / "background.png").resolve()))
            self.assertEqual(source["settings"]["resource_bundle"], str((result.package_path / "other resources" / "layout.plugin-data").resolve()))
            image_source = next(item for item in exported["sources"] if item["name"] == "Image")
            self.assertEqual(image_source["filters"][0]["settings"]["lookup_file"], str((result.package_path / "other resources" / "colour.cube").resolve()))

    def test_packs_full_local_browser_overlay_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            browser_root = root / "browser"
            (browser_root / "assets").mkdir(parents=True)
            (browser_root / "index.html").write_text('<link rel="stylesheet" href="style.css">', encoding="utf-8")
            (browser_root / "style.css").write_text('body { background: url("assets/bg.png"); }', encoding="utf-8")
            (browser_root / "script.js").write_text('console.log("overlay")', encoding="utf-8")
            (browser_root / "assets" / "bg.png").write_bytes(b"image")
            collection_path = root / "Browser.json"
            data = collection(browser_root / "index.html", browser_root / "index.html", browser_root / "index.html")
            data["sources"] = [
                {"name": "Browser", "id": "browser_source", "settings": {"local_file": str(browser_root / "index.html")}}
            ]
            data["scene_order"] = []
            collection_path.write_text(json.dumps(data), encoding="utf-8")
            destination = root / "exports"
            destination.mkdir()

            result = export_scene_collection(collection_path, destination)

            self.assertTrue(result.success, result.error)
            target_root = result.package_path / "browser overlays" / "browser"
            self.assertTrue((target_root / "index.html").is_file())
            self.assertTrue((target_root / "style.css").is_file())
            self.assertTrue((target_root / "script.js").is_file())
            self.assertTrue((target_root / "assets" / "bg.png").is_file())
            exported = json.loads(result.collection_path.read_text(encoding="utf-8"))
            self.assertEqual(exported["sources"][0]["settings"]["local_file"], str((target_root / "index.html").resolve()))
    def test_lists_collections_and_prefers_obs_active_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            scenes.mkdir(parents=True)
            image = root / "image.png"
            image.write_bytes(b"image")
            for name in ("Current", "Other"):
                (scenes / f"{name}.json").write_text(
                    json.dumps(collection(image, image, image) | {"name": name}), encoding="utf-8"
                )
            (scenes.parent.parent / "user.ini").write_text(
                "[Basic]\nSceneCollectionFile=Current.json\n", encoding="utf-8"
            )

            collections = list_obs_scene_collections(scenes)

            self.assertEqual(set(collections), {"Current", "Other"})
            self.assertEqual(active_obs_scene_collection(scenes), (scenes / "Current.json").resolve())


if __name__ == "__main__":
    unittest.main()
