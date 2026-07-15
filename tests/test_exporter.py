from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility import exporter  # noqa: E402
from obs_overlay_import_utility.exporter import (  # noqa: E402
    active_obs_scene_collection,
    build_export_inventory,
    build_export_plan,
    export_scene_collection,
    list_obs_scene_collections,
    detect_portable_package,
    validate_portable_manifest,
    materialize_portable_collection,
    verify_portable_package,
    is_safe_portable_path,
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
                "settings": {
                    "resource_bundle": str(plugin_file),
                    "same_image": str(image),
                },
            },
        ],
    }


def _pkg_name(base: str) -> str:
    return base + "-Portable"


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
            collection_path.write_text(
                json.dumps(collection(image, plugin_file, filter_file)),
                encoding="utf-8",
            )
            destination = root / "exports"
            destination.mkdir()

            result = export_scene_collection(collection_path, destination)

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.copied_files, 3)
            self.assertGreater(result.source_references, 0)
            pkg = result.package_path
            self.assertTrue((pkg / "assets" / "images" / "background.png").is_file())
            self.assertTrue(
                (pkg / "assets" / "other" / "layout 2.plugin-data").is_file()
            )
            self.assertTrue(
                (pkg / "assets" / "other" / "colour.cube").is_file()
            )
            exported = json.loads(result.collection_path.read_text(encoding="utf-8"))
            source = next(
                item
                for item in exported["sources"]
                if item["name"] == "Custom plugin source"
            )
            # Collection-relative paths
            self.assertIn("../assets/images/background.png",
                          source["settings"]["same_image"])
            self.assertIn("../assets/other/layout 2.plugin-data",
                          source["settings"]["resource_bundle"])
            image_source = next(
                item for item in exported["sources"] if item["name"] == "Image"
            )
            self.assertIn("../assets/other/colour.cube",
                          image_source["filters"][0]["settings"]["lookup_file"])
            # Verify no absolute paths remain
            for p in [source["settings"]["same_image"],
                      source["settings"]["resource_bundle"],
                      image_source["filters"][0]["settings"]["lookup_file"]]:
                self.assertTrue(p.startswith("../"), f"expected relative, got: {p}")

    def test_packs_full_local_browser_overlay_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            browser_root = root / "browser"
            (browser_root / "assets").mkdir(parents=True)
            (browser_root / "index.html").write_text(
                '<link rel="stylesheet" href="style.css">', encoding="utf-8"
            )
            (browser_root / "style.css").write_text(
                'body { background: url("assets/bg.png"); }', encoding="utf-8"
            )
            (browser_root / "script.js").write_text(
                'console.log("overlay")', encoding="utf-8"
            )
            (browser_root / "assets" / "bg.png").write_bytes(b"image")
            collection_path = root / "Browser.json"
            html_path = browser_root / "index.html"
            data = {
                "name": "Browser Pack",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {
                        "name": "Browser",
                        "id": "browser_source",
                        "settings": {"local_file": str(html_path)},
                    }
                ],
            }
            collection_path.write_text(json.dumps(data), encoding="utf-8")
            destination = root / "exports"
            destination.mkdir()

            result = export_scene_collection(collection_path, destination)

            self.assertTrue(result.success, result.error)
            target_root = result.package_path / "browser" / "browser"
            self.assertTrue((target_root / "index.html").is_file())
            self.assertTrue((target_root / "style.css").is_file())
            self.assertTrue((target_root / "script.js").is_file())
            self.assertTrue((target_root / "assets" / "bg.png").is_file())
            exported = json.loads(result.collection_path.read_text(encoding="utf-8"))
            local_file = exported["sources"][0]["settings"]["local_file"]
            self.assertTrue(local_file.startswith("../browser/"),
                            f"expected relative browser path, got: {local_file}")

    def test_rejects_export_destination_inside_browser_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            browser_root = root / "browser"
            browser_root.mkdir()
            html = browser_root / "index.html"
            html.write_text("<html></html>", encoding="utf-8")
            collection_path = root / "Browser.json"
            data = {
                "name": "Browser",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {
                        "name": "Browser source",
                        "id": "browser_source",
                        "settings": {"local_file": str(html)},
                    }
                ],
            }
            collection_path.write_text(json.dumps(data), encoding="utf-8")
            destination = browser_root / "exports"
            destination.mkdir()

            result = export_scene_collection(collection_path, destination)

            self.assertFalse(result.success)
            self.assertIn("cannot be inside", result.error)
            self.assertEqual(list(destination.iterdir()), [])

    def test_browser_preflight_limit_fails_without_partial_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            browser_root = root / "browser"
            browser_root.mkdir()
            html = browser_root / "index.html"
            html.write_text("<html></html>", encoding="utf-8")
            (browser_root / "style.css").write_text("body {}", encoding="utf-8")
            collection_path = root / "Browser.json"
            data = {
                "name": "Browser",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {
                        "name": "Browser source",
                        "id": "browser_source",
                        "settings": {"local_file": str(html)},
                    }
                ],
            }
            collection_path.write_text(json.dumps(data), encoding="utf-8")
            destination = root / "exports"
            destination.mkdir()

            with mock.patch.object(exporter, "MAX_BROWSER_FILES", 1):
                result = export_scene_collection(collection_path, destination)

            self.assertFalse(result.success)
            self.assertIn("more than 1 files", result.error)
            self.assertEqual(list(destination.iterdir()), [])

    def test_rejects_broad_browser_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            browser_root = root / "broad-folder"
            browser_root.mkdir()
            html = browser_root / "index.html"
            html.write_text("<html></html>", encoding="utf-8")
            collection_path = root / "Browser.json"
            data = {
                "name": "Browser",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {
                        "name": "Browser source",
                        "id": "browser_source",
                        "settings": {"local_file": str(html)},
                    }
                ],
            }
            collection_path.write_text(json.dumps(data), encoding="utf-8")
            destination = root / "exports"
            destination.mkdir()

            with mock.patch.object(
                exporter,
                "_unsafe_browser_roots",
                return_value={browser_root.resolve()},
            ):
                result = export_scene_collection(collection_path, destination)

            self.assertFalse(result.success)
            self.assertIn("broad personal or system folder", result.error)
            self.assertEqual(list(destination.iterdir()), [])

    def test_lists_collections_and_prefers_obs_active_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            scenes.mkdir(parents=True)
            image = root / "image.png"
            image.write_bytes(b"image")
            for name in ("Current", "Other"):
                (scenes / f"{name}.json").write_text(
                    json.dumps(collection(image, image, image) | {"name": name}),
                    encoding="utf-8",
                )
            (scenes.parent.parent / "user.ini").write_text(
                "[Basic]\nSceneCollectionFile=Current.json\n", encoding="utf-8"
            )

            collections = list_obs_scene_collections(scenes)

            self.assertEqual(set(collections), {"Current", "Other"})
            self.assertEqual(
                active_obs_scene_collection(scenes), (scenes / "Current.json").resolve()
            )

    def test_inventory_reports_unique_resources_and_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            browser = root / "browser"
            browser.mkdir()
            html = browser / "index.html"
            html.write_text("<html></html>", encoding="utf-8")
            css = browser / "style.css"
            css.write_text("body {}", encoding="utf-8")
            image = root / "image.png"
            image.write_bytes(b"image")
            missing = root / "missing.plugin"
            data = {
                "name": "Inventory",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Browser", "id": "browser_source", "settings": {"local_file": str(html)}},
                    {"name": "Image", "id": "image_source", "settings": {"file": str(image), "duplicate": str(image)}},
                    {"name": "Plugin", "id": "plugin", "settings": {"asset": str(missing)}},
                ],
            }
            collection_path = root / "Inventory.json"
            collection_path.write_text(json.dumps(data), encoding="utf-8")
            destination = root / "exports"
            destination.mkdir()

            inventory = build_export_inventory(collection_path, destination)

            self.assertTrue(inventory.success, inventory.error)
            self.assertGreater(inventory.source_references, 0)
            self.assertEqual(len(inventory.items), 3)
            self.assertEqual(inventory.browser_files, 2)
            self.assertEqual(inventory.total_bytes, html.stat().st_size + css.stat().st_size + image.stat().st_size)
            self.assertEqual(len(inventory.missing_references), 1)
            self.assertEqual(inventory.package_path, destination / _pkg_name("Inventory"))

    def test_atomic_collection_write_failure_leaves_no_partial_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "image.png"
            image.write_bytes(b"image")
            collection_path = root / "Collection.json"
            collection_path.write_text(
                json.dumps(collection(image, image, image)), encoding="utf-8"
            )
            destination = root / "exports"
            destination.mkdir()

            with mock.patch.object(
                exporter, "atomic_write_json", side_effect=OSError("blocked write")
            ):
                result = export_scene_collection(collection_path, destination)

            self.assertFalse(result.success)
            self.assertIn("blocked write", result.error)
            self.assertEqual(list(destination.iterdir()), [])

    def test_sanitizes_windows_reserved_and_invalid_package_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination = root / "exports"
            destination.mkdir()
            expected = (("CON", _pkg_name("_CON")), ("Bad:<Name>? .", _pkg_name("Bad__Name__")))
            for index, (name, package_name) in enumerate(expected):
                path = root / f"Collection {index}.json"
                path.write_text(
                    json.dumps(
                        {
                            "name": name,
                            "current_scene": "Main",
                            "scene_order": [{"name": "Main"}],
                            "sources": [{"name": "Main", "id": "scene", "settings": {"items": []}}],
                        }
                    ),
                    encoding="utf-8",
                )
                result = export_scene_collection(path, destination)
                self.assertTrue(result.success, result.error)
                self.assertEqual(result.package_path.name, package_name)

    # --- New portable-package tests ---

    def test_portable_paths_are_collection_relative(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"image")
            data = {
                "name": "Test",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "Test.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            r = export_scene_collection(cp, dest)
            self.assertTrue(r.success, r.error)
            exported = json.loads(r.collection_path.read_text(encoding="utf-8"))
            img_src = next(s for s in exported["sources"] if s["name"] == "Img")
            self.assertTrue(img_src["settings"]["file"].startswith("../assets/images/"),
                            f"expected collection-relative, got: {img_src['settings']['file']}")
            self.assertNotIn(str(root), img_src["settings"]["file"],
                             "must not contain seller's original path")

    def test_move_package_then_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"img")
            data = {
                "name": "Movable",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "Movable.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            r = export_scene_collection(cp, dest)
            self.assertTrue(r.success, r.error)
            pkg = r.package_path

            # Move to new location
            moved = root / "imported_packs" / pkg.name
            moved.parent.mkdir(parents=True, exist_ok=True)
            shutil = __import__("shutil")
            shutil.move(str(pkg), str(moved))

            # Detect and import from new location
            manifest = detect_portable_package(moved)
            self.assertIsNotNone(manifest)
            manifest_data = validate_portable_manifest(manifest)
            self.assertIn("collection", manifest_data)

            ocd = root / "obs_collections"
            ocd.mkdir()
            materialized = materialize_portable_collection(manifest, ocd)
            self.assertTrue(materialized.is_file())
            imported = json.loads(materialized.read_text(encoding="utf-8"))
            img_src = next(s for s in imported["sources"] if s["name"] == "Img")
            self.assertIn(str(moved), img_src["settings"]["file"],
                          "imported collection must contain absolute path to moved package")

    def test_manifest_exists_in_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"img")
            data = {
                "name": "Manifested",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "Manifested.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            r = export_scene_collection(cp, dest)
            self.assertTrue(r.success, r.error)
            manifest_path = r.package_path / "manifest.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "obs-overlay-portable-package")
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["collection"]["path_mode"], "collection-relative")
            # Manifest paths must not be absolute
            for f in manifest.get("files", []):
                self.assertFalse(f["path"].startswith("/"))
                self.assertFalse(":" in f["path"])

    def test_verify_portable_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"img")
            data = {
                "name": "Verified",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "Verified.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            r = export_scene_collection(cp, dest)
            self.assertTrue(r.success, r.error)
            v = verify_portable_package(r.package_path)
            self.assertTrue(v.ok, f"Verification failed: {v.errors}")

    def test_zip_mode_creates_only_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"img")
            data = {
                "name": "Zipped",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "Zipped.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            plan = build_export_plan(cp, dest, compressed=True)
            r = export_scene_collection(cp, dest, compressed=True, plan=plan)
            self.assertTrue(r.success, r.error)
            self.assertTrue(r.compressed)
            self.assertTrue(r.archive_path is not None)
            self.assertTrue(r.archive_path.suffix == ".zip")
            self.assertTrue(r.archive_path.is_file())
            # ZIP mode must not leave a normal final folder
            pkg_folder = r.archive_path.with_suffix("")
            self.assertFalse(pkg_folder.is_dir(),
                             "ZIP mode must not leave a normal folder")

    def test_frozen_plan_revalidation_catches_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"img")
            data = {
                "name": "Frozen",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "Frozen.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            plan = build_export_plan(cp, dest, compressed=False)
            # Mutate the collection after freezing
            cp.write_text(cp.read_text().replace("Frozen", "Changed"), encoding="utf-8")
            r = export_scene_collection(cp, dest, compressed=False, plan=plan)
            self.assertFalse(r.success)
            self.assertIn("changed", r.error)

    def test_is_safe_portable_path(self) -> None:
        self.assertTrue(is_safe_portable_path("../assets/images/bg.png"))
        self.assertTrue(is_safe_portable_path("assets/images/bg.png"))
        self.assertTrue(is_safe_portable_path("collection/Test.json"))
        self.assertFalse(is_safe_portable_path("../assets/../../../etc/passwd"))
        self.assertFalse(is_safe_portable_path("/etc/passwd"))
        self.assertFalse(is_safe_portable_path("C:\\Windows"))
        self.assertFalse(is_safe_portable_path(""))

    def test_manifest_contains_file_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"img" * 100)
            data = {
                "name": "Hashed",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "Hashed.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            r = export_scene_collection(cp, dest)
            self.assertTrue(r.success)
            manifest = json.loads((r.package_path / "manifest.json").read_text(encoding="utf-8"))
            for f in manifest["files"]:
                self.assertIn("sha256", f)
                self.assertIn("size", f)
                self.assertGreater(f["size"], 0)
                self.assertEqual(len(f["sha256"]), 64)

    def test_instructions_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"img")
            data = {
                "name": "Instructed",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "Instructed.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            r = export_scene_collection(cp, dest)
            self.assertTrue(r.success)
            txt = r.package_path / "Import Instructions.txt"
            self.assertTrue(txt.is_file())
            content = txt.read_text(encoding="utf-8")
            self.assertIn("How to use", content)


if __name__ == "__main__":
    unittest.main()
