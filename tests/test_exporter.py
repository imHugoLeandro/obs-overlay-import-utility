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
from obs_overlay_import_utility.core import atomic_write_json  # noqa: E402
from obs_overlay_import_utility.models import UtilityError  # noqa: E402
from obs_overlay_import_utility.exporter import (  # noqa: E402
    active_obs_scene_collection,
    build_export_inventory,
    build_export_plan,
    export_inventory_from_plan,
    export_scene_collection,
    list_obs_scene_collections,
    detect_portable_package,
    validate_portable_manifest,
    materialize_portable_collection,
    verify_portable_package,
    is_safe_portable_path,
    _analyse_dependencies,
    _count_scenes_and_sources,
    _unique_asset_filename,
)


def _is_contained(child: Path, parent: Path) -> bool:
    """Return True when *child* resolves to a path inside *parent*.

    Uses resolved paths so Windows 8.3 short-name forms (e.g. ``RUNNER~1`` vs
    ``runneradmin``) do not cause false containment failures.
    """
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _can_create_symlinks() -> bool:
    """Best-effort check for symlink creation support in this environment."""
    import tempfile

    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp) / "target"
        base.write_text("x", encoding="utf-8")
        link = Path(temp) / "link"
        try:
            link.symlink_to(base)
        except (OSError, NotImplementedError, AttributeError):
            return False
        return link.is_symlink()


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
                (pkg / "assets" / "other" / "layout.plugin-data").is_file()
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
            self.assertIn("../assets/other/layout.plugin-data",
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
            # Use resolved-path equality so Windows 8.3 short-name forms
            # (RUNNER~1 vs runneradmin) do not cause false mismatches.
            self.assertIsNotNone(inventory.package_path)
            self.assertEqual(
                inventory.package_path.resolve(),
                (destination / _pkg_name("Inventory")).resolve(),
            )

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
            # Use resolved-path containment so Windows 8.3 short-name forms
            # (RUNNER~1 vs runneradmin) do not cause false mismatches.
            imported_file = Path(img_src["settings"]["file"])
            self.assertTrue(
                _is_contained(imported_file, moved.resolve()),
                "imported collection must contain absolute path to moved package",
            )

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

    def test_zip_mode_missing_file_uses_missing_placeholder(self) -> None:
        """ZIP publication must replace missing-file absolute paths with
        ../missing/... placeholders, using resolved-path comparison to avoid
        Windows 8.3 short-name mismatches (RUNNER~1 vs runneradmin)."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            present = root / "present.png"
            present.write_bytes(b"img")
            missing = root / "gone.png"
            data = {
                "name": "ZipMissing",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "OK", "id": "image_source", "settings": {"file": str(present)}},
                    {"name": "Gone", "id": "image_source", "settings": {"file": str(missing)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "ZipMissing.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            plan = build_export_plan(cp, dest, compressed=True)
            r = export_scene_collection(cp, dest, compressed=True, plan=plan)
            self.assertTrue(r.success, r.error)
            self.assertTrue(r.compressed)
            self.assertIsNotNone(r.archive_path)
            archive_path = r.archive_path
            assert archive_path is not None  # for type checker
            self.assertTrue(archive_path.is_file())

            # Read the collection JSON from the ZIP archive.
            import zipfile as _zf
            with _zf.ZipFile(archive_path, "r") as zf:
                coll_name = archive_path.name.replace(".zip", "")
                coll_zip_path = f"{coll_name}/collection/{cp.stem}.json"
                coll_data = json.loads(zf.read(coll_zip_path))

            gone = next(s for s in coll_data["sources"] if s["name"] == "Gone")
            gone_path = gone["settings"]["file"]
            # The missing file must use the ../missing/ placeholder, not an
            # absolute path.
            self.assertTrue(
                gone_path.startswith("../missing/"),
                f"missing path should use ../missing/ placeholder, got: {gone_path}",
            )
            self.assertFalse(
                str(root) in gone_path or str(missing) in gone_path,
                "seller's absolute path must not appear in exported ZIP package",
            )

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
        self.assertFalse(is_safe_portable_path("C:\\\\Windows"))
        self.assertFalse(is_safe_portable_path(""))
        # Empty segments (repeated slashes) are rejected.
        self.assertFalse(is_safe_portable_path("assets//images/bg.png"))
        self.assertFalse(is_safe_portable_path("assets/images//bg.png"))
        # Leading slash is rejected.
        self.assertFalse(is_safe_portable_path("/assets/images/bg.png"))

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


    # --- Collision-safe filename tests ---

    def test_different_filenames_keep_original_names(self) -> None:
        self.assertEqual(_unique_asset_filename("background.png", set()), "background.png")
        used = {"background.png"}
        self.assertEqual(_unique_asset_filename("logo.png", used), "logo.png")

    def test_same_filenames_get_deterministic_suffix(self) -> None:
        used = {"background.png"}
        self.assertEqual(_unique_asset_filename("background.png", used), "background 2.png")
        used.add("background 2.png")
        self.assertEqual(_unique_asset_filename("background.png", used), "background 3.png")

    def test_collision_is_case_insensitive(self) -> None:
        used = {"Background.PNG"}
        result = _unique_asset_filename("background.png", used)
        self.assertNotEqual(result, "background.png")
        self.assertIn("background", result.casefold())

    # --- Device dependency tests ---

    def test_device_requirements_are_populated(self) -> None:
        data = {
            "name": "DevReqs",
            "current_scene": "Main",
            "scene_order": [{"name": "Main"}],
            "sources": [
                {"name": "Webcam", "id": "dshow_input", "settings": {"device_id": "some-device"}},
                {"name": "Mic", "id": "wasapi_input_capture", "settings": {"device_id": "some-mic"}},
                {"name": "Main", "id": "scene", "settings": {"items": []}},
            ],
        }
        deps = _analyse_dependencies(data)
        self.assertGreater(len(deps.devices), 0, "device deps should be detected")
        kinds = {d["kind"] for d in deps.devices}
        self.assertIn("Camera or capture device", kinds)
        self.assertIn("Audio device", kinds)

    # --- Canvas detection tests ---

    def test_canvas_dimensions_are_detected(self) -> None:
        data = {
            "name": "Canvas",
            "current_scene": "Main",
            "scene_order": [{"name": "Main"}],
            "resolution": {"x": 1920, "y": 1080},
            "sources": [{"name": "Main", "id": "scene", "settings": {"items": []}}],
        }
        _, _, cw, ch = _count_scenes_and_sources(data)
        self.assertEqual(cw, 1920)
        self.assertEqual(ch, 1080)

    def test_missing_canvas_returns_none(self) -> None:
        data = {
            "name": "NoCanvas",
            "current_scene": "Main",
            "scene_order": [{"name": "Main"}],
            "sources": [{"name": "Main", "id": "scene", "settings": {"items": []}}],
        }
        _, _, cw, ch = _count_scenes_and_sources(data)
        self.assertIsNone(cw)
        self.assertIsNone(ch)

    # --- Inventory from plan tests ---

    def test_inventory_from_plan_matches_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"img")
            data = {
                "name": "PlanInv",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "PlanInv.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            plan = build_export_plan(cp, dest, compressed=True)
            inv = export_inventory_from_plan(plan)
            self.assertTrue(inv.success)
            self.assertEqual(inv.compressed, True)
            self.assertIn(".zip", str(inv.package_path))
            self.assertEqual(inv.total_bytes, plan.total_bytes)
            self.assertEqual(len(inv.items), len(plan.files))

    # --- Missing path privacy tests ---

    def test_missing_absolute_paths_do_not_enter_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "present.png"
            image.write_bytes(b"img")
            missing = root / "gone.png"
            data = {
                "name": "Missing",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "OK", "id": "image_source", "settings": {"file": str(image)}},
                    {"name": "Gone", "id": "image_source", "settings": {"file": str(missing)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "Missing.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            r = export_scene_collection(cp, dest)
            self.assertTrue(r.success, r.error)
            exported = json.loads(r.collection_path.read_text(encoding="utf-8"))
            gone = next(s for s in exported["sources"] if s["name"] == "Gone")
            self.assertFalse(
                gone["settings"]["file"].startswith(str(root)),
                "seller's absolute path must not appear in exported package",
            )
            self.assertIn("../missing/", gone["settings"]["file"],
                          f"missing path should use ../missing/ placeholder, got: {gone['settings']['file']}")

    # --- Revalidation tests ---

    def test_same_size_source_mutation_fails_revalidation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"same" * 1)
            data = {
                "name": "SameSize",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "SameSize.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            plan = build_export_plan(cp, dest, compressed=False)
            img.write_bytes(b"DIFFERENT")
            r = export_scene_collection(cp, dest, compressed=False, plan=plan)
            self.assertFalse(r.success)
            self.assertIn("changed", r.error)

    # --- Manifest import tests ---

    def test_malformed_manifest_prevents_fallback_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "manifest.json").write_text("{invalid json", encoding="utf-8")
            (root / "collection.json").write_text(
                json.dumps({"name": "Fallback", "current_scene": "M", "scene_order": [], "sources": []}),
                encoding="utf-8",
            )
            from obs_overlay_import_utility.models import UtilityError
            with self.assertRaises(UtilityError):
                detect_portable_package(root)

    def test_unsupported_manifest_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "manifest.json").write_text(
                json.dumps({"schema": "obs-overlay-portable-package", "schema_version": 999}),
                encoding="utf-8",
            )
            from obs_overlay_import_utility.models import UtilityError
            with self.assertRaises(UtilityError):
                detect_portable_package(root)
            with self.assertRaises(UtilityError):
                validate_portable_manifest(root / "manifest.json")

    def test_materialization_verifies_package_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "manifest.json").write_text(
                json.dumps({
                    "schema": "obs-overlay-portable-package",
                    "schema_version": 1,
                    "collection": {"path": "collection/Test.json", "path_mode": "collection-relative"},
                    "files": [],
                }),
                encoding="utf-8",
            )
            ocd = root / "obs_collections"
            ocd.mkdir()
            from obs_overlay_import_utility.models import UtilityError
            with self.assertRaises(UtilityError):
                materialize_portable_collection(root / "manifest.json", ocd)

    # --- ZIP atomic publication tests ---

    def test_zip_publication_uses_atomic_same_filesystem_move(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"img" * 50)
            data = {
                "name": "AtomicZip",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "AtomicZip.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            plan = build_export_plan(cp, dest, compressed=True)
            r = export_scene_collection(cp, dest, compressed=True, plan=plan)
            self.assertTrue(r.success, r.error)
            self.assertTrue(r.archive_path.is_file())
            self.assertTrue(str(plan.output_path) == str(r.archive_path))

    # --- source_names in manifest tests ---

    def test_file_referenced_by_multiple_sources_lists_all_used_by(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "shared.png"
            img.write_bytes(b"shared")
            data = {
                "name": "Shared",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "SrcA", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "SrcB", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "Shared.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            r = export_scene_collection(cp, dest)
            self.assertTrue(r.success, r.error)
            manifest = json.loads((r.package_path / "manifest.json").read_text(encoding="utf-8"))
            for f in manifest["files"]:
                if f["category"] != "browser":
                    self.assertIn("SrcA", f["used_by"])
                    self.assertIn("SrcB", f["used_by"])

    # --- Export result includes path_mode ---

    def test_zip_inventory_displays_zip_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"img")
            data = {
                "name": "ZipPath",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "ZipPath.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            plan = build_export_plan(cp, dest, compressed=True)
            inv = export_inventory_from_plan(plan)
            self.assertTrue(inv.package_path is not None)
            self.assertTrue(str(inv.package_path).endswith(".zip"))

    def test_folder_inventory_displays_folder_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"img")
            data = {
                "name": "FolderPath",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "FolderPath.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            plan = build_export_plan(cp, dest, compressed=False)
            inv = export_inventory_from_plan(plan)
            self.assertTrue(inv.package_path is not None)
            self.assertFalse(str(inv.package_path).endswith(".zip"))


class PortableIntegrityHardeningTests(unittest.TestCase):
    # --- Fix 1: untrusted manifest validation ---

    def test_validate_manifest_rejects_absolute_collection_path(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "/etc/passwd"},
            "files": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_traversal_file_path(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/Test.json"},
            "files": [
                {"path": "../secrets/keys.json", "size": 1, "sha256": "a" * 64, "category": "other"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_unc_file_path(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/Test.json"},
            "files": [
                {"path": "//server/share/file.png", "size": 1, "sha256": "a" * 64, "category": "images"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_drive_qualified_path(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/Test.json"},
            "files": [
                {"path": "C:/Windows/system32/file.dll", "size": 1, "sha256": "a" * 64, "category": "other"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_duplicate_file_paths(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/Test.json"},
            "files": [
                {"path": "assets/images/bg.png", "size": 1, "sha256": "a" * 64, "category": "images"},
                {"path": "assets/images/bg.png", "size": 1, "sha256": "b" * 64, "category": "images"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_missing_or_wrong_type_fields(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        cases = [
            # missing path key entirely
            {"size": 3, "sha256": "a" * 64, "category": "images"},
            # size not an int
            {"path": "assets/images/bg.png", "size": "small", "sha256": "a" * 64, "category": "images"},
            # digest wrong length
            {"path": "assets/images/bg.png", "size": 3, "sha256": "deadbeef", "category": "images"},
            # category missing
            {"path": "assets/images/bg.png", "size": 3, "sha256": "a" * 64},
        ]
        for bad_entry in cases:
            manifest = {
                "schema": "obs-overlay-portable-package",
                "schema_version": 1,
                "collection": {"path": "collection/Test.json"},
                "files": [bad_entry],
            }
            with tempfile.TemporaryDirectory() as temp:
                mp = Path(temp) / "manifest.json"
                mp.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(UtilityError):
                    validate_portable_manifest(mp)

    def test_validate_manifest_rejects_non_object(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    # --- Fix 2: portable import cannot write outside the OBS scenes directory ---

    def _exported_package(self, root: Path) -> Path:
        img = root / "bg.png"
        img.write_bytes(b"img")
        data = {
            "name": "Imported",
            "current_scene": "Main",
            "scene_order": [{"name": "Main"}],
            "sources": [
                {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                {"name": "Main", "id": "scene", "settings": {"items": []}},
            ],
        }
        cp = root / "Imported.json"
        cp.write_text(json.dumps(data), encoding="utf-8")
        dest = root / "exports"
        dest.mkdir()
        r = export_scene_collection(cp, dest)
        self.assertTrue(r.success, r.error)
        return r.package_path

    def test_portable_import_uses_safe_unique_collection_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._exported_package(root)
            ocd = root / "obs_collections"
            ocd.mkdir()
            # Pre-seed a name that collides with the proposed collection name.
            (ocd / "Imported.json").write_text("{}", encoding="utf-8")
            out = materialize_portable_collection(pkg / "manifest.json", ocd)
            self.assertTrue(out.is_file())
            # The helper must have chosen a unique name, not overwritten ours.
            self.assertTrue((ocd / "Imported.json").is_file())
            self.assertNotEqual(out.name, "Imported.json")
            self.assertTrue(out.name.startswith("Imported"))

    def test_portable_import_rejects_traversal_collection_name(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._exported_package(root)
            # Tamper the collection JSON name with a traversal payload.
            coll = json.loads((pkg / "collection" / "Imported.json").read_text(encoding="utf-8"))
            coll["name"] = "../../escape"
            atomic_write_json(pkg / "collection" / "Imported.json", coll)
            ocd = root / "obs_collections"
            ocd.mkdir()
            # A traversal name must never be honored; import is refused.
            with self.assertRaises(UtilityError):
                materialize_portable_collection(pkg / "manifest.json", ocd)
            self.assertEqual([c.name for c in ocd.iterdir()], [])

    def test_portable_import_rejects_drive_qualified_collection_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._exported_package(root)
            coll = json.loads((pkg / "collection" / "Imported.json").read_text(encoding="utf-8"))
            coll["name"] = "C:/Windows/System32/evil"
            atomic_write_json(pkg / "collection" / "Imported.json", coll)
            ocd = root / "obs_collections"
            ocd.mkdir()
            out = materialize_portable_collection(pkg / "manifest.json", ocd)
            self.assertTrue(out.is_file())
            # The output must resolve into the OBS scenes directory. Resolved
            # paths are used so 8.3 short-name forms (e.g. RUNNER~1) on Windows
            # do not break the containment check.
            self.assertTrue(
                _is_contained(out, ocd),
                "collection written outside target directory",
            )
            self.assertEqual([c.name for c in ocd.iterdir()], [out.name])

    def test_portable_import_rejects_unc_collection_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._exported_package(root)
            coll = json.loads((pkg / "collection" / "Imported.json").read_text(encoding="utf-8"))
            coll["name"] = "//server/share/evil"
            atomic_write_json(pkg / "collection" / "Imported.json", coll)
            ocd = root / "obs_collections"
            ocd.mkdir()
            out = materialize_portable_collection(pkg / "manifest.json", ocd)
            self.assertTrue(out.is_file())
            self.assertTrue(
                _is_contained(out, ocd),
                "collection written outside target directory",
            )
            self.assertEqual([c.name for c in ocd.iterdir()], [out.name])

    def test_portable_import_rejects_reserved_windows_collection_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._exported_package(root)
            coll = json.loads((pkg / "collection" / "Imported.json").read_text(encoding="utf-8"))
            coll["name"] = "CON"
            atomic_write_json(pkg / "collection" / "Imported.json", coll)
            ocd = root / "obs_collections"
            ocd.mkdir()
            # A reserved Windows name is sanitized to a safe unique filename and
            # must remain inside the OBS scenes directory.
            out = materialize_portable_collection(pkg / "manifest.json", ocd)
            self.assertTrue(out.is_file())
            self.assertTrue(
                _is_contained(out, ocd),
                "collection written outside target directory",
            )
            self.assertEqual([c.name for c in ocd.iterdir()], [out.name])

    def test_portable_import_duplicate_normal_name_gets_unique_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._exported_package(root)
            ocd = root / "obs_collections"
            ocd.mkdir()
            first = materialize_portable_collection(pkg / "manifest.json", ocd)
            second = materialize_portable_collection(pkg / "manifest.json", ocd)
            self.assertNotEqual(first.name, second.name)
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())

    # --- Fix 3: same-size mutation fails export (digest revalidation) ---

    def test_same_size_mutation_fails_export_digest_revalidation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            img = root / "bg.png"
            img.write_bytes(b"AAAA")  # 4 bytes
            data = {
                "name": "DigestFrozen",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {"name": "Img", "id": "image_source", "settings": {"file": str(img)}},
                    {"name": "Main", "id": "scene", "settings": {"items": []}},
                ],
            }
            cp = root / "DigestFrozen.json"
            cp.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            plan = build_export_plan(cp, dest, compressed=False)
            # AAAA -> BBBB keeps the same size (4 bytes) but changes the digest.
            img.write_bytes(b"BBBB")
            r = export_scene_collection(cp, dest, compressed=False, plan=plan)
            self.assertFalse(r.success)
            self.assertIn("changed", r.error)

    # --- Fix 4: distinct browser roots with the same folder name survive ---

    def test_distinct_browser_roots_same_name_get_unique_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Two independent browser source roots both named "overlay".
            browser_a = root / "projects" / "overlay"
            browser_b = root / "other" / "overlay"
            for br in (browser_a, browser_b):
                br.mkdir(parents=True)
                (br / "index.html").write_text(
                    f'<h1>{br.parts[-2]}</h1>', encoding="utf-8"
                )
            collection_path = root / "Browser.json"
            data = {
                "name": "DoubleBrowser",
                "current_scene": "Main",
                "scene_order": [{"name": "Main"}],
                "sources": [
                    {
                        "name": "A",
                        "id": "browser_source",
                        "settings": {"local_file": str(browser_a / "index.html")},
                    },
                    {
                        "name": "B",
                        "id": "browser_source",
                        "settings": {"local_file": str(browser_b / "index.html")},
                    },
                ],
            }
            collection_path.write_text(json.dumps(data), encoding="utf-8")
            dest = root / "exports"
            dest.mkdir()
            r = export_scene_collection(collection_path, dest)
            self.assertTrue(r.success, r.error)

            manifest = json.loads((r.package_path / "manifest.json").read_text(encoding="utf-8"))
            # The two same-named browser roots must get distinct package dirs.
            self.assertEqual(set(manifest["browser_projects"]), {"overlay", "overlay 2"})

            dir_a = r.package_path / "browser" / "overlay"
            dir_b = r.package_path / "browser" / "overlay 2"
            self.assertTrue(dir_a.is_dir())
            self.assertTrue(dir_b.is_dir())
            # Content must be preserved and distinct.
            self.assertEqual(
                (dir_a / "index.html").read_text(encoding="utf-8"), "<h1>projects</h1>"
            )
            self.assertEqual(
                (dir_b / "index.html").read_text(encoding="utf-8"), "<h1>other</h1>"
            )
            # The rewritten collection must reference both dirs.
            exported = json.loads(r.collection_path.read_text(encoding="utf-8"))
            refs = [
                s["settings"]["local_file"]
                for s in exported["sources"]
                if s["id"] == "browser_source"
            ]
            self.assertEqual(len(refs), 2)
            self.assertIn("../browser/overlay/index.html", refs)
            self.assertIn("../browser/overlay 2/index.html", refs)

    # --- Fix 2: Windows-safe imported collection names ---

    def test_reserved_collection_names_are_sanitized(self) -> None:
        from obs_overlay_import_utility.core import next_obs_collection_path

        # (input name, expected sanitized stem)
        cases = [
            ("CON", "_CON"),
            ("con", "_con"),
            ("CON.txt", "_CON.txt"),
            ("CON.backup.txt", "_CON.backup.txt"),
            ("LPT1", "_LPT1"),
            ("LPT1.extra.json", "_LPT1.extra.json"),
            ("COM9.anything", "_COM9.anything"),
            ("lpt9", "_lpt9"),
            ("PRN", "_PRN"),
        ]
        for name, expected in cases:
            stem, path = next_obs_collection_path(Path("/tmp/never-created"), name)
            self.assertEqual(stem, expected, f"name={name!r}")
            self.assertTrue(stem.startswith("_"))
            self.assertTrue(path.name.endswith(".json"))
        # Sanity: genuinely normal names are unchanged (incl. dotted names).
        for name in ("My Pack", "My.Collection", "report.final.json", "comic"):
            stem, _ = next_obs_collection_path(Path("/tmp/never-created"), name)
            self.assertEqual(stem, name, f"normal name={name!r} should be unchanged")

    def test_reserved_name_collision_suffix_behavior(self) -> None:
        from obs_overlay_import_utility.core import next_obs_collection_path

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Seed the sanitized form so the helper must apply a numeric suffix.
            (root / "_CON.json").write_text("{}", encoding="utf-8")
            stem, path = next_obs_collection_path(root, "CON")
            self.assertEqual(stem, "_CON 1")
            self.assertTrue(path.name.endswith(".json"))

    def test_normal_collision_behavior_unchanged(self) -> None:
        from obs_overlay_import_utility.core import next_obs_collection_path

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Normal.json").write_text("{}", encoding="utf-8")
            stem, _ = next_obs_collection_path(root, "Normal")
            self.assertEqual(stem, "Normal 1")

    # --- Fix 1: symlinked intermediate directory must not be traversed ---

    def test_verify_rejects_symlinked_intermediate_directory(self) -> None:
        if not _can_create_symlinks():
            self.skipTest("this environment cannot create symlinks")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root / "outside"
            outside.mkdir()
            secret = outside / "secret.bin"
            secret.write_bytes(b"top-secret")

            # Build a package whose assets/ directory is a symlink to /outside.
            pkg = root / "Pkg-Portable"
            pkg.mkdir()
            (pkg / "collection").mkdir()
            assets_link = pkg / "assets"
            assets_link.symlink_to(outside, target_is_directory=True)
            # Declare the secret as an in-package asset.
            manifest = {
                "schema": "obs-overlay-portable-package",
                "schema_version": 1,
                "collection": {"path": "collection/Test.json"},
                "files": [
                    {
                        "path": "assets/secret.bin",
                        "size": secret.stat().st_size,
                        "sha256": _sha256_of(secret),
                        "category": "other",
                    }
                ],
            }
            (pkg / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (pkg / "collection" / "Test.json").write_text(
                json.dumps({"name": "Test", "current_scene": "M", "scene_order": [], "sources": []}),
                encoding="utf-8",
            )

            verify = verify_portable_package(pkg)
            self.assertFalse(verify.ok)
            self.assertTrue(
                any("escapes package root" in e or "link or reparse point" in e for e in verify.errors),
                f"expected traversal/reparse rejection, got: {verify.errors}",
            )

            # No collection may be materialized from a package that fails verify.
            ocd = root / "obs_collections"
            ocd.mkdir()
            with self.assertRaises(UtilityError):
                materialize_portable_collection(pkg / "manifest.json", ocd)
            self.assertEqual([c.name for c in ocd.iterdir()], [])

    def test_verify_rejects_final_file_symlink(self) -> None:
        if not _can_create_symlinks():
            self.skipTest("this environment cannot create symlinks")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # A real file inside the package, plus a manifest entry that points
            # to a *symlink* of that file. The link resolves back inside the
            # package, so a final-file-only check would accept it; we must not.
            pkg = root / "Pkg-Portable"
            pkg.mkdir()
            (pkg / "collection").mkdir()
            real = pkg / "assets"
            real.mkdir()
            real_file = real / "image.png"
            real_file.write_bytes(b"real-content")
            link_file = pkg / "assets" / "image_link.png"
            link_file.symlink_to(real_file)
            manifest = {
                "schema": "obs-overlay-portable-package",
                "schema_version": 1,
                "collection": {"path": "collection/Test.json"},
                "files": [
                    {
                        "path": "assets/image_link.png",
                        "size": real_file.stat().st_size,
                        "sha256": _sha256_of(real_file),
                        "category": "other",
                    }
                ],
            }
            (pkg / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (pkg / "collection" / "Test.json").write_text(
                json.dumps({"name": "Test", "current_scene": "M", "scene_order": [], "sources": []}),
                encoding="utf-8",
            )

            verify = verify_portable_package(pkg)
            self.assertFalse(verify.ok)
            self.assertTrue(
                any("link or reparse point" in e for e in verify.errors),
                f"expected final-file link rejection, got: {verify.errors}",
            )

    def test_verify_rejects_intermediate_dir_symlink_inside_package(self) -> None:
        if not _can_create_symlinks():
            self.skipTest("this environment cannot create symlinks")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Intermediate directory symlink that resolves to *another* real
            # directory inside the package (not outside). The resolved target is
            # still in-package, so containment alone would pass; the link must
            # still be rejected.
            pkg = root / "Pkg-Portable"
            pkg.mkdir()
            (pkg / "collection").mkdir()
            real_dir = pkg / "real_assets"
            real_dir.mkdir()
            secret = real_dir / "secret.bin"
            secret.write_bytes(b"inside-secret")
            link_dir = pkg / "assets"
            link_dir.symlink_to(real_dir, target_is_directory=True)
            manifest = {
                "schema": "obs-overlay-portable-package",
                "schema_version": 1,
                "collection": {"path": "collection/Test.json"},
                "files": [
                    {
                        "path": "assets/secret.bin",
                        "size": secret.stat().st_size,
                        "sha256": _sha256_of(secret),
                        "category": "other",
                    }
                ],
            }
            (pkg / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (pkg / "collection" / "Test.json").write_text(
                json.dumps({"name": "Test", "current_scene": "M", "scene_order": [], "sources": []}),
                encoding="utf-8",
            )

            verify = verify_portable_package(pkg)
            self.assertFalse(verify.ok)
            self.assertTrue(
                any("link or reparse point" in e for e in verify.errors),
                f"expected intermediate-dir link rejection, got: {verify.errors}",
            )

    # --- Fix 2: verify_portable_package validates collection manifest JSON ---

    def _make_minimal_package(self, root: Path) -> Path:
        """Create a minimal valid package with one asset and return its root."""
        pkg = root / "Pkg-Portable"
        pkg.mkdir()
        (pkg / "collection").mkdir()
        (pkg / "assets").mkdir()
        img = pkg / "assets" / "image.png"
        img.write_bytes(b"img")
        digest = _sha256_of(img)
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/Test.json"},
            "files": [
                {
                    "path": "assets/image.png",
                    "size": img.stat().st_size,
                    "sha256": digest,
                    "category": "images",
                }
            ],
        }
        (pkg / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (pkg / "collection" / "Test.json").write_text(
            json.dumps({"name": "Test", "current_scene": "M", "scene_order": [], "sources": []}),
            encoding="utf-8",
        )
        return pkg

    def test_verify_rejects_missing_collection_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._make_minimal_package(root)
            # Remove the collection file.
            (pkg / "collection" / "Test.json").unlink()
            verify = verify_portable_package(pkg)
            self.assertFalse(verify.ok)
            self.assertTrue(
                any("Collection JSON missing" in e for e in verify.errors),
                f"expected missing collection rejection, got: {verify.errors}",
            )

    def test_verify_rejects_invalid_collection_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._make_minimal_package(root)
            # Overwrite the collection with invalid JSON.
            (pkg / "collection" / "Test.json").write_text(
                "{not valid json", encoding="utf-8"
            )
            verify = verify_portable_package(pkg)
            self.assertFalse(verify.ok)
            self.assertTrue(
                any("Collection JSON could not be read" in e for e in verify.errors),
                f"expected invalid collection JSON rejection, got: {verify.errors}",
            )

    def test_verify_rejects_collection_not_obs_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._make_minimal_package(root)
            # Overwrite the collection with valid JSON but not OBS data.
            (pkg / "collection" / "Test.json").write_text(
                json.dumps({"not": "an obs collection"}), encoding="utf-8"
            )
            verify = verify_portable_package(pkg)
            self.assertFalse(verify.ok)
            self.assertTrue(
                any("not a valid OBS scene collection" in e for e in verify.errors),
                f"expected non-OBS collection rejection, got: {verify.errors}",
            )

    def test_verify_rejects_collection_symlink_inside_package(self) -> None:
        if not _can_create_symlinks():
            self.skipTest("this environment cannot create symlinks")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._make_minimal_package(root)
            # Replace the real collection file with a symlink to another
            # in-package file. The symlink resolves inside the package, so
            # containment alone would pass; the link must still be rejected.
            target = pkg / "assets" / "image.png"
            coll = pkg / "collection" / "Test.json"
            coll.unlink()
            coll.symlink_to(target)
            verify = verify_portable_package(pkg)
            self.assertFalse(verify.ok)
            self.assertTrue(
                any("link or reparse point" in e for e in verify.errors),
                f"expected collection symlink rejection, got: {verify.errors}",
            )

    def test_verify_rejects_collection_symlink_escaping_package(self) -> None:
        if not _can_create_symlinks():
            self.skipTest("this environment cannot create symlinks")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._make_minimal_package(root)
            # Create a file outside the package and symlink the collection
            # to it.
            outside = root / "outside.json"
            outside.write_text(
                json.dumps({"name": "Test", "current_scene": "M", "scene_order": [], "sources": []}),
                encoding="utf-8",
            )
            coll = pkg / "collection" / "Test.json"
            coll.unlink()
            coll.symlink_to(outside)
            verify = verify_portable_package(pkg)
            self.assertFalse(verify.ok)
            self.assertTrue(
                any("link or reparse point" in e or "escapes package root" in e
                    for e in verify.errors),
                f"expected collection symlink escape rejection, got: {verify.errors}",
            )

    def test_verify_rejects_collection_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pkg = self._make_minimal_package(root)
            # Tamper the manifest to point the collection path outside the package.
            manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
            manifest["collection"]["path"] = "../../etc/passwd"
            (pkg / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            verify = verify_portable_package(pkg)
            self.assertFalse(verify.ok)
            self.assertTrue(
                any("unsafe" in e or "escapes" in e for e in verify.errors),
                f"expected collection traversal rejection, got: {verify.errors}",
            )

    # --- Fix 3: manifest paths are canonical (no .. or . segments) ---

    def test_validate_manifest_rejects_dotdot_in_collection_path(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "assets/../collection/C.json"},
            "files": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_dot_in_collection_path(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/./C.json"},
            "files": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_dotdot_in_file_path(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/C.json"},
            "files": [
                {"path": "assets/../collection/C.json", "size": 1,
                 "sha256": "a" * 64, "category": "images"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_dot_in_file_path(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/C.json"},
            "files": [
                {"path": "assets/./images/bg.png", "size": 1,
                 "sha256": "a" * 64, "category": "images"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_duplicate_normalized_paths(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        # Two paths that differ only in separator style normalize to the same
        # path and must not both pass validation.
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/C.json"},
            "files": [
                {"path": "assets/images/bg.png", "size": 1,
                 "sha256": "a" * 64, "category": "images"},
                {"path": "assets\\images\\bg.png", "size": 1,
                 "sha256": "b" * 64, "category": "images"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_alias_collision_after_normalization(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        # ``assets/../collection/C.json`` and ``collection/C.json`` normalize to
        # the same path. Both must be rejected because dot-segments are not
        # allowed, and even without the dot-segment the duplicate would be caught.
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/C.json"},
            "files": [
                {"path": "collection/C.json", "size": 1,
                 "sha256": "a" * 64, "category": "other"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            # This should pass because collection/C.json is a valid path and
            # there's only one file entry. But if we add the alias form it
            # must be rejected.
            manifest["files"].append({
                "path": "assets/../collection/C.json", "size": 1,
                "sha256": "b" * 64, "category": "other",
            })
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    # --- Fix 2 (cont): manifest path canonicalization (empty segments) ---

    def test_validate_manifest_rejects_empty_segments_in_collection_path(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "assets//images/bg.png"},
            "files": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_empty_segments_in_file_path(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/C.json"},
            "files": [
                {"path": "assets/images//bg.png", "size": 1,
                 "sha256": "a" * 64, "category": "images"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)

    def test_validate_manifest_rejects_leading_slash_in_file_path(self) -> None:
        from obs_overlay_import_utility.models import UtilityError
        manifest = {
            "schema": "obs-overlay-portable-package",
            "schema_version": 1,
            "collection": {"path": "collection/C.json"},
            "files": [
                {"path": "/assets/images/bg.png", "size": 1,
                 "sha256": "a" * 64, "category": "images"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            mp = Path(temp) / "manifest.json"
            mp.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UtilityError):
                validate_portable_manifest(mp)


def _sha256_of(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


if __name__ == "__main__":
    unittest.main()
