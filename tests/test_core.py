from __future__ import annotations

import json
import os
import copy
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility import core  # noqa: E402
from obs_overlay_import_utility.models import FileIndex  # noqa: E402
from obs_overlay_import_utility.paths import find_file_match, is_local_media_path  # noqa: E402
from obs_overlay_import_utility.streamlabs import extract_zip_archive  # noqa: E402


def scene_data(*paths: str) -> dict:
    return {
        "current_scene": "Main",
        "scene_order": [{"name": "Main"}],
        "sources": [
            {
                "name": "Overlay source",
                "settings": {"playlist": [{"value": path} for path in paths]},
            }
        ],
    }


class CoreTests(unittest.TestCase):
    def test_recognizes_supported_local_paths(self) -> None:
        for path in (
            r"C:\Creator\Overlay\image.png",
            r"C:\Creator\Overlay\sound.flac",
            "/home/creator/overlay/video.webm",
            r"D:\Overlay\widget.html",
        ):
            self.assertTrue(is_local_media_path(path), path)

    def test_ignores_urls_and_unrelated_text(self) -> None:
        self.assertFalse(is_local_media_path("https://example.com/image.png"))
        self.assertFalse(is_local_media_path("data:image/png;base64,abc"))
        self.assertFalse(is_local_media_path("image.png"))
        self.assertFalse(is_local_media_path(r"C:\notes\instructions.txt"))

    def test_scans_full_large_json_and_filters_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = scene_data(r"C:\old\image.png")
            valid["padding"] = "x" * 12000
            (root / "collection.json").write_text(json.dumps(valid), encoding="utf-8")
            (root / "collection_ImportReady.json").write_text(
                json.dumps(valid), encoding="utf-8"
            )
            (root / "metadata.json").write_text('{"name":"not OBS"}', encoding="utf-8")
            found = core.find_scene_collections(root)
            self.assertEqual(found, [(root / "collection.json").resolve()])

    def test_conversion_updates_paths_and_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            assets = root / "Overlay" / "media"
            assets.mkdir(parents=True)
            for name in ("image.png", "sound.ogg", "widget.html"):
                (assets / name).write_bytes(b"asset")
            source = root / "My Collection.json"
            original = scene_data(
                r"E:\Seller\Package\media\image.png",
                r"E:\Seller\Package\media\sound.ogg",
                r"E:\Seller\Package\media\widget.html",
            )
            source.write_text(json.dumps(original), encoding="utf-8")

            result = core.convert_collection(source, root)

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.changed, 3)
            self.assertEqual(json.loads(source.read_text(encoding="utf-8")), original)
            converted = json.loads(result.output_path.read_text(encoding="utf-8"))
            values = [
                item["value"]
                for item in converted["sources"][0]["settings"]["playlist"]
            ]
            self.assertEqual(
                values,
                [
                    str((assets / name).resolve())
                    for name in ("image.png", "sound.ogg", "widget.html")
                ],
            )

    def test_plugin_and_script_file_references_are_relinked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "magic.lua").write_text("-- script", encoding="utf-8")
            (root / "voice.ttf").write_bytes(b"font")
            (root / "vertical.json").write_text("{}", encoding="utf-8")
            (root / "mask.png").write_bytes(b"mask")
            source = root / "collection.json"
            source.write_text(
                json.dumps(
                    {
                        "current_scene": "Starting Soon",
                        "scene_order": [
                            {"name": "Starting Soon"},
                            {"name": "v-Starting Soon"},
                            {"name": "BRB"},
                        ],
                        "sources": [
                            {
                                "id": "aitum.vertical.source",
                                "name": "Vertical Scene",
                                "type": "aitum_vertical_scene",
                                "uuid": "8f9a-plugin-0001",
                                "settings": {
                                    "layout_mode": "vertical",
                                    "vertical_scene_id": "v-Starting Soon",
                                    "script_path": r"C:\Creator\Pack\scripts\magic.lua",
                                    "font_file": r"C:\Creator\Pack\fonts\voice.ttf",
                                    "nested": {
                                        "layout_file": r"C:\Creator\Pack\config\vertical.json"
                                    },
                                },
                                "filters": [
                                    {
                                        "name": "Plugin filter",
                                        "type": "aitum.filter",
                                        "settings": {
                                            "extra_path": r"C:\Creator\Pack\scripts\magic.lua"
                                        },
                                    },
                                    {
                                        "name": "Blend mask",
                                        "type": "mask_filter",
                                        "settings": {
                                            "mask_path": r"C:\Creator\Pack\media\mask.png"
                                        },
                                    },
                                ],
                            }
                        ],
                        "scenes": [
                            {
                                "name": "Starting Soon",
                                "items": [
                                    {
                                        "source_uuid": "8f9a-plugin-0001",
                                        "transform": {"pos": {"x": 0, "y": 0}},
                                    }
                                ],
                            },
                            {"name": "v-Starting Soon", "items": []},
                            {"name": "BRB", "items": []},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = core.convert_collection(source, root)

            self.assertTrue(result.success, result.error)
            converted = json.loads(result.output_path.read_text(encoding="utf-8"))
            settings = converted["sources"][0]["settings"]
            self.assertEqual(
                settings["script_path"], str((root / "magic.lua").resolve())
            )
            self.assertEqual(
                settings["font_file"], str((root / "voice.ttf").resolve())
            )
            self.assertEqual(
                settings["nested"]["layout_file"],
                str((root / "vertical.json").resolve()),
            )
            self.assertEqual(
                converted["sources"][0]["filters"][0]["settings"]["extra_path"],
                str((root / "magic.lua").resolve()),
            )
            # Image Mask/Blend filter paths are relinked too (OBS #11257).
            self.assertEqual(
                converted["sources"][0]["filters"][1]["settings"]["mask_path"],
                str((root / "mask.png").resolve()),
            )
            # Import health report inputs.
            self.assertEqual(result.plugin_source_ids, ["aitum.filter", "aitum.vertical.source"])
            self.assertEqual(result.remote_browser_urls, 0)
            # Unknown plugin fields, UUIDs, and extra/vertical scenes are preserved.
            self.assertEqual(converted["sources"][0]["id"], "aitum.vertical.source")
            self.assertEqual(converted["sources"][0]["uuid"], "8f9a-plugin-0001")
            self.assertEqual(settings["layout_mode"], "vertical")
            self.assertEqual(settings["vertical_scene_id"], "v-Starting Soon")
            self.assertEqual(
                [s["name"] for s in converted["scenes"]],
                ["Starting Soon", "v-Starting Soon", "BRB"],
            )

    def test_summary_counts_browser_urls_and_plugin_types(self) -> None:
        data = {
            "sources": [
                {
                    "id": "obs_browser_source",
                    "settings": {"url": "https://streamelements.com/overlay/abc"},
                },
                {
                    "id": "browser_source",
                    "settings": {"url": "file:///C:/local/widget.html"},
                },
                {"id": "image_source", "settings": {"file": r"C:\a\b.png"}},
                {"id": "aitum.vertical.source", "settings": {}},
                {
                    "id": "ffmpeg_source",
                    "filters": [
                        {"type": "chroma_key_filter_v2"},
                        {"type": "vendor.shader.filter"},
                    ],
                },
            ]
        }
        remote_browser, plugin_ids = core.summarize_collection(data)
        self.assertEqual(remote_browser, 1)  # https URL counts; file:// does not
        self.assertEqual(plugin_ids, ["aitum.vertical.source", "vendor.shader.filter"])

    def test_missing_file_prevents_output_in_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "collection.json"
            source.write_text(
                json.dumps(scene_data(r"C:\old\missing.png")), encoding="utf-8"
            )
            result = core.convert_collection(source, root)
            self.assertFalse(result.success)
            self.assertEqual(len(result.missing), 1)
            self.assertFalse((root / "collection_ImportReady.json").exists())

    def test_non_strict_mode_can_write_with_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "collection.json"
            source.write_text(
                json.dumps(scene_data(r"C:\old\missing.png")), encoding="utf-8"
            )
            result = core.convert_collection(source, root, strict=False)
            self.assertTrue(result.success)
            self.assertEqual(len(result.missing), 1)

    def test_ambiguous_file_prevents_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "one").mkdir()
            (root / "two").mkdir()
            (root / "one" / "same.png").write_bytes(b"1")
            (root / "two" / "same.png").write_bytes(b"2")
            source = root / "collection.json"
            source.write_text(
                json.dumps(scene_data(r"C:\old\same.png")), encoding="utf-8"
            )
            result = core.convert_collection(source, root)
            self.assertFalse(result.success)
            self.assertEqual(len(result.ambiguous), 1)

    def test_matching_uses_trailing_folder_to_resolve_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected = root / "package" / "media"
            other = root / "alternate" / "images"
            expected.mkdir(parents=True)
            other.mkdir(parents=True)
            (expected / "same.png").write_bytes(b"1")
            (other / "same.png").write_bytes(b"2")
            source = root / "collection.json"
            source.write_text(
                json.dumps(scene_data(r"C:\seller\media\same.png")), encoding="utf-8"
            )
            result = core.convert_collection(source, root)
            self.assertTrue(result.success)
            converted = json.loads(result.output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                converted["sources"][0]["settings"]["playlist"][0]["value"],
                str((expected / "same.png").resolve()),
            )

    def test_case_sensitive_matching_respects_folder_case(self) -> None:
        first = r"C:\one\Parent\Media\same.png"
        second = r"C:\two\parent\Media\same.png"
        index = FileIndex(
            by_name={"same.png": [first, second]},
            by_folder={"Media": {"same.png": [first, second]}},
            file_count=2,
        )
        match, ambiguous = find_file_match(
            r"D:\seller\parent\Media\same.png", index, case_sensitive=True
        )
        self.assertEqual(match, second)
        self.assertEqual(ambiguous, ())

    def test_unknown_plugin_path_key_is_also_relinked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            asset = root / "plugin-texture.png"
            asset.write_bytes(b"x")
            source = root / "collection.json"
            data = scene_data()
            data["sources"][0]["settings"] = {
                "third_party_plugin_asset": r"C:\creator\plugin-texture.png"
            }
            source.write_text(json.dumps(data), encoding="utf-8")
            result = core.convert_collection(source, root)
            self.assertTrue(result.success)
            converted = json.loads(result.output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                converted["sources"][0]["settings"]["third_party_plugin_asset"],
                str(asset.resolve()),
            )

    def test_output_name_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "image.png").write_bytes(b"x")
            source = root / "collection.json"
            source.write_text(
                json.dumps(scene_data(r"C:\old\image.png")), encoding="utf-8"
            )
            first = core.convert_collection(source, root)
            second = core.convert_collection(source, root)
            self.assertEqual(first.output_path.name, "collection_Updated.json")
            self.assertEqual(second.output_path.name, "collection_Updated2.json")

    def test_atomic_failure_leaves_no_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "result.json"
            with mock.patch(
                "obs_overlay_import_utility.core.os.replace",
                side_effect=OSError("blocked"),
            ):
                with self.assertRaises(core.UtilityError):
                    core.atomic_write_json(target, {"ok": True})
            self.assertFalse(target.exists())
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_index_walks_overlay_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "image.png").write_bytes(b"x")
            source = root / "collection.json"
            source.write_text(
                json.dumps(scene_data(r"C:\old\image.png")), encoding="utf-8"
            )
            real_walk = os.walk
            with mock.patch(
                "obs_overlay_import_utility.core.os.walk", wraps=real_walk
            ) as walk:
                result = core.convert_collection(source, root)
            self.assertTrue(result.success)
            self.assertEqual(walk.call_count, 1)

    def test_resize_changes_only_obs_scene_item_transforms(self) -> None:
        data = {
            "name": "Plugin resize safety",
            "current_scene": "Main",
            "scene_order": [{"name": "Main"}],
            "resolution": {"x": 100, "y": 100},
            "sources": [
                {
                    "name": "Main",
                    "id": "scene",
                    "settings": {
                        "items": [
                            {
                                "name": "Plugin",
                                "pos": {"x": 10.0, "y": 20.0},
                                "scale": {"x": 1.0, "y": 1.0},
                                "bounds": {"x": 30.0, "y": 40.0},
                                "scale_ref": {"x": 100.0, "y": 100.0},
                            }
                        ]
                    },
                },
                {
                    "name": "Plugin",
                    "id": "custom_plugin_source",
                    "settings": {
                        "pos": {"x": 7, "y": 8},
                        "scale": {"x": 9, "y": 10},
                        "bounds": {"x": 11, "y": 12},
                    },
                },
            ],
        }
        plugin_settings = copy.deepcopy(data["sources"][1]["settings"])

        self.assertTrue(core.resize_scene_collection(data, 200, 300))

        self.assertEqual(data["sources"][1]["settings"], plugin_settings)
        item = data["sources"][0]["settings"]["items"][0]
        self.assertEqual(item["pos"], {"x": 20.0, "y": 60.0})
        self.assertEqual(data["resolution"], {"x": 200, "y": 300})

    def test_resize_scales_active_bounds_instead_of_source_scale(self) -> None:
        data = {
            "name": "Bounded", "current_scene": "Main",
            "scene_order": [{"name": "Main"}], "resolution": {"x": 100, "y": 100},
            "sources": [{"name": "Main", "id": "scene", "settings": {"items": [{
                "name": "Bounded source", "bounds_type": 2,
                "pos": {"x": 10.0, "y": 20.0}, "scale": {"x": 1.5, "y": 1.25},
                "bounds": {"x": 30.0, "y": 40.0},
            }]}}],
        }
        self.assertTrue(core.resize_scene_collection(data, 200, 300))
        item = data["sources"][0]["settings"]["items"][0]
        self.assertEqual(item["pos"], {"x": 20.0, "y": 60.0})
        self.assertEqual(item["scale"], {"x": 1.5, "y": 1.25})
        self.assertEqual(item["bounds"], {"x": 60.0, "y": 120.0})
    def test_source_has_no_obs_plugin_or_embedded_binary_dependency(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in (ROOT / "src").rglob("*.py")
        )
        self.assertNotIn("obspython", source.casefold())
        self.assertNotIn("base64.b64decode", source.casefold())


class ZipRedirectCoreTests(unittest.TestCase):
    """A redirected ZIP pack: extract → scan finds the OBS export → convert."""

    def test_zip_pack_scan_and_convert_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "MyOverlayPack.zip"
            with zipfile.ZipFile(archive, "w") as zip_out:
                zip_out.writestr("images/logo.png", b"png")
                zip_out.writestr(
                    "scene_collection.json",
                    json.dumps(scene_data(r"C:\old\images\logo.png")),
                )

            extracted = extract_zip_archive(archive)
            collections = core.find_scene_collections(extracted)

            self.assertEqual(collections, [(extracted / "scene_collection.json").resolve()])
            result = core.convert_collection(collections[0], extracted)
            self.assertTrue(result.success, result.error)
            self.assertIsNotNone(result.output_path)
            converted = json.loads(result.output_path.read_text(encoding="utf-8"))
            self.assertIn("logo.png", converted["sources"][0]["settings"]["playlist"][0]["value"])

    def test_zip_pack_without_collection_scans_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "NoJson.zip"
            with zipfile.ZipFile(archive, "w") as zip_out:
                zip_out.writestr("readme.txt", "no collection here")

            extracted = extract_zip_archive(archive)
            collections = core.find_scene_collections(extracted)
            self.assertEqual(collections, [])


if __name__ == "__main__":
    unittest.main()
