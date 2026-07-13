from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility.settings import AppSettings, SettingsStore  # noqa: E402


class SettingsTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            expected = AppSettings(
                theme="dark",
                ui_scale=125,
                use_custom_obs=True,
                obs_path=r"D:\OBS\obs64.exe",
                remember_last_folder=False,
            )
            store.save(expected)
            self.assertEqual(store.load(), expected)

    def test_invalid_file_returns_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            store.path.write_text("not-json", encoding="utf-8")
            self.assertEqual(store.load(), AppSettings())
            self.assertIsNotNone(store.last_error)

    def test_unknown_values_are_normalized(self) -> None:
        settings = AppSettings.from_dict(
            {
                "theme": "neon",
                "ui_scale": 900,
                "python_path": 42,
                "unknown_future_setting": True,
            }
        )
        self.assertEqual(settings.theme, "system")
        self.assertEqual(settings.ui_scale, 150)
        self.assertEqual(settings.python_path, "")

    def test_saved_json_contains_no_unknown_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            store.save(AppSettings())
            data = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 1)
            self.assertNotIn("unknown", data)



    def test_default_matching_options_are_safe(self) -> None:
        settings = AppSettings()
        self.assertTrue(settings.strict_validation)
        self.assertTrue(settings.case_sensitive_matching)
if __name__ == "__main__":
    unittest.main()
