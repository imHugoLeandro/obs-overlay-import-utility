from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility.resizer import (  # noqa: E402
    MODE_SCALE_RATIO,
    MODE_STRETCH,
    SCOPE_COLLECTION,
    SCOPE_SOURCE,
    resize_collection,
    source_choices,
    undo_resize,
)


def collection() -> dict:
    return {
        "name": "Resize Test",
        "resolution": {"x": 100, "y": 100},
        "current_scene": "Main",
        "scene_order": [{"name": "Main"}],
        "sources": [
            {
                "name": "Main",
                "id": "scene",
                "settings": {
                    "items": [
                        {
                            "name": "Background",
                            "source_uuid": "background-uuid",
                            "bounds_type": 0,
                            "pos": {"x": 10.0, "y": 20.0},
                            "scale": {"x": 1.0, "y": 1.0},
                            "bounds": {"x": 30.0, "y": 40.0},
                            "scale_ref": {"x": 100.0, "y": 100.0},
                        },
                        {
                            "name": "Logo",
                            "bounds_type": 2,
                            "source_uuid": "logo-uuid",
                            "pos": {"x": 50.0, "y": 25.0},
                            "scale": {"x": 1.0, "y": 1.0},
                            "bounds": {"x": 10.0, "y": 10.0},
                            "scale_ref": {"x": 100.0, "y": 100.0},
                        },
                    ]
                },
            },
            {"name": "Background", "uuid": "background-uuid", "id": "image_source", "settings": {}},
            {"name": "Logo", "uuid": "logo-uuid", "id": "image_source", "settings": {}},
        ],
    }


class ResizerTests(unittest.TestCase):
    def _write_collection(self, root: Path) -> Path:
        path = root / "Resize Test.json"
        path.write_text(json.dumps(collection()), encoding="utf-8")
        return path

    def test_stretch_resizes_every_item_and_creates_undo_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self._write_collection(Path(temp))

            result = resize_collection(
                path,
                scope=SCOPE_COLLECTION,
                selected_name=None,
                mode=MODE_STRETCH,
                target_width=200,
                selected_uuid=None,
                target_height=300,
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.changed_items, 2)
            self.assertTrue(result.canvas_changed)
            self.assertTrue(result.backup_path.is_file())
            resized = json.loads(path.read_text(encoding="utf-8"))
            item = resized["sources"][0]["settings"]["items"][0]
            self.assertEqual(resized["resolution"], {"x": 200, "y": 300})
            self.assertEqual(item["pos"], {"x": 20.0, "y": 60.0})
            self.assertEqual(item["scale"], {"x": 2.0, "y": 3.0})
            self.assertEqual(item["bounds"], {"x": 30.0, "y": 40.0})
            logo = resized["sources"][0]["settings"]["items"][1]
            self.assertEqual(logo["scale"], {"x": 1.0, "y": 1.0})
            self.assertEqual(logo["bounds"], {"x": 20.0, "y": 30.0})

            self.assertIsNone(undo_resize(path, result.backup_path))
            self.assertFalse(result.backup_path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), collection())

    def test_scale_ratio_centers_and_limits_changes_to_selected_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = self._write_collection(Path(temp))

            result = resize_collection(
                path,
                scope=SCOPE_SOURCE,
                selected_name="Background",
                mode=MODE_SCALE_RATIO,
                target_width=200,
                target_height=300,
                selected_uuid="background-uuid",
            )

            self.assertTrue(result.success, result.error)
            self.assertEqual(result.changed_items, 1)
            self.assertFalse(result.canvas_changed)
            resized = json.loads(path.read_text(encoding="utf-8"))
            background, logo = resized["sources"][0]["settings"]["items"]
            self.assertEqual(background["pos"], {"x": 20.0, "y": 90.0})
            self.assertEqual(background["scale"], {"x": 2.0, "y": 2.0})
            self.assertEqual(logo["pos"], {"x": 50.0, "y": 25.0})
            self.assertEqual(background["scale_ref"], {"x": 100.0, "y": 100.0})
            self.assertEqual(resized["resolution"], {"x": 100, "y": 100})


    def test_source_choices_include_uuid_in_display_name(self) -> None:
        choices = source_choices(collection())

        self.assertEqual(
            [choice.label for choice in choices],
            ["Background (background-uuid)", "Logo (logo-uuid)"],
        )

    def test_duplicate_source_names_resize_only_selected_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data = collection()
            data["sources"].append(
                {
                    "name": "Background",
                    "uuid": "background-second-uuid",
                    "id": "image_source",
                    "settings": {},
                }
            )
            data["sources"][0]["settings"]["items"].append(
                {
                    "name": "Background",
                    "source_uuid": "background-second-uuid",
                    "bounds_type": 0,
                    "pos": {"x": 5.0, "y": 5.0},
                    "scale": {"x": 1.0, "y": 1.0},
                    "bounds": {"x": 0.0, "y": 0.0},
                    "scale_ref": {"x": 100.0, "y": 100.0},
                }
            )
            path = Path(temp) / "Duplicate.json"
            path.write_text(json.dumps(data), encoding="utf-8")

            result = resize_collection(
                path,
                scope=SCOPE_SOURCE,
                selected_name="Background (background-second-uuid)",
                selected_uuid="background-second-uuid",
                mode=MODE_STRETCH,
                target_width=200,
                target_height=200,
            )

            self.assertTrue(result.success, result.error)
            resized = json.loads(path.read_text(encoding="utf-8"))
            first, _logo, second = resized["sources"][0]["settings"]["items"]
            self.assertEqual(first["pos"], {"x": 10.0, "y": 20.0})
            self.assertEqual(second["pos"], {"x": 10.0, "y": 10.0})
            self.assertEqual(second["scale"], {"x": 2.0, "y": 2.0})

if __name__ == "__main__":
    unittest.main()
