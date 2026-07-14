from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility.models import UtilityError  # noqa: E402
from obs_overlay_import_utility.device_setup import (  # noqa: E402
    DeviceCandidate,
    apply_device_choices,
    available_device_candidates,
    collection_device_requirements,
)


def collection(
    name: str, source_name: str, source_id: str, settings: dict, uuid: str
) -> dict:
    return {
        "name": name,
        "current_scene": "Main",
        "scene_order": [{"name": "Main"}],
        "sources": [
            {"name": "Main", "id": "scene", "settings": {"items": []}},
            {
                "name": source_name,
                "uuid": uuid,
                "id": source_id,
                "settings": settings,
                "enabled": True,
            },
        ],
    }


class DeviceSetupTests(unittest.TestCase):
    def test_uses_local_camera_settings_for_imported_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scenes = root / "obs" / "basic" / "scenes"
            scenes.mkdir(parents=True)
            (scenes / "Current.json").write_text(
                json.dumps(
                    collection(
                        "Current",
                        "My Logitech Camera",
                        "av_capture_input",
                        {"device_id": "local-camera-id", "resolution": "1920x1080"},
                        "local-camera",
                    )
                ),
                encoding="utf-8",
            )
            imported = scenes / "Imported.json"
            imported.write_text(
                json.dumps(
                    collection(
                        "Imported",
                        "Camera",
                        "av_capture_input",
                        {"device_id": "", "resolution": "1280x720", "fps": 30},
                        "imported-camera",
                    )
                ),
                encoding="utf-8",
            )

            requirements = collection_device_requirements(imported)
            candidates = available_device_candidates(
                scenes, exclude_collection=imported
            )

            self.assertEqual(requirements[0].kind, "Camera or capture device")
            candidate = candidates["av_capture_input"][0]
            self.assertIsNone(
                apply_device_choices(imported, {requirements[0].key: candidate})
            )
            updated = json.loads(imported.read_text(encoding="utf-8"))
            source = updated["sources"][1]
            self.assertEqual(
                source["settings"],
                {"device_id": "local-camera-id", "resolution": "1280x720", "fps": 30},
            )
            self.assertEqual(source["id"], "av_capture_input")

    def test_rejects_incompatible_source_type_without_changing_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "Imported.json"
            original = collection(
                "Imported",
                "Camera",
                "av_capture_input",
                {"device_id": "", "resolution": "1280x720"},
                "imported-camera",
            )
            path.write_text(json.dumps(original), encoding="utf-8")
            requirement = collection_device_requirements(path)[0]
            incompatible = DeviceCandidate(
                label="Game capture — Current",
                source_id="game_capture",
                kind="Display, window, or game capture",
                settings={"window": "example"},
            )

            error = apply_device_choices(path, {requirement.key: incompatible})

            self.assertIn("not compatible", error)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_can_disable_an_unavailable_device_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "Imported.json"
            path.write_text(
                json.dumps(
                    collection(
                        "Imported",
                        "Mic",
                        "wasapi_input_capture",
                        {"device_id": "missing"},
                        "imported-mic",
                    )
                ),
                encoding="utf-8",
            )
            requirement = collection_device_requirements(path)[0]

            self.assertIsNone(apply_device_choices(path, {requirement.key: "disable"}))
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(updated["sources"][1]["enabled"])


    def test_invalid_collection_is_reported_instead_of_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "Broken.json"
            path.write_text('{"name": "not an OBS collection"}', encoding="utf-8")
            with self.assertRaisesRegex(UtilityError, "recognized OBS scene collection"):
                collection_device_requirements(path)
if __name__ == "__main__":
    unittest.main()
