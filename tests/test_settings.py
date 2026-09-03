"""Tests for application settings persistence and schema migration."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility.settings import (  # noqa: E402
    AppSettings,
    SettingsStore,
    CURRENT_SCHEMA_VERSION,
    normalized_bool,
)


class SettingsTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            expected = AppSettings(
                theme="dark",
                ui_scale=125,
                sidebar_collapsed=True,
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
        self.assertEqual(settings.sidebar_collapsed, False)

    def test_saved_json_contains_correct_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            store.save(AppSettings())
            data = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], CURRENT_SCHEMA_VERSION)
            self.assertNotIn("unknown", data)

    def test_default_matching_options_are_safe(self) -> None:
        settings = AppSettings()
        self.assertTrue(settings.strict_validation)
        self.assertTrue(settings.case_sensitive_matching)

    # --- sidebar_collapsed schema migration ---

    def test_default_sidebar_is_expanded(self) -> None:
        self.assertFalse(AppSettings().sidebar_collapsed)

    def test_v1_settings_without_sidebar_field_load_as_expanded(self) -> None:
        settings = AppSettings.from_dict({"theme": "light", "schema_version": 1})
        self.assertFalse(settings.sidebar_collapsed)
        self.assertEqual(settings.schema_version, CURRENT_SCHEMA_VERSION)

    def test_v2_collapsed_round_trips(self) -> None:
        settings = AppSettings.from_dict(
            {"sidebar_collapsed": True, "schema_version": 2}
        )
        self.assertTrue(settings.sidebar_collapsed)

    def test_v2_expanded_round_trips(self) -> None:
        settings = AppSettings.from_dict(
            {"sidebar_collapsed": False, "schema_version": 2}
        )
        self.assertFalse(settings.sidebar_collapsed)

    def test_string_false_not_true(self) -> None:
        settings = AppSettings.from_dict({"sidebar_collapsed": "false"})
        self.assertFalse(settings.sidebar_collapsed)

    def test_string_true_not_true(self) -> None:
        settings = AppSettings.from_dict({"sidebar_collapsed": "true"})
        self.assertFalse(settings.sidebar_collapsed)

    def test_int_zero_not_true(self) -> None:
        settings = AppSettings.from_dict({"sidebar_collapsed": 0})
        self.assertFalse(settings.sidebar_collapsed)

    def test_none_uses_default(self) -> None:
        settings = AppSettings.from_dict({"sidebar_collapsed": None})
        self.assertFalse(settings.sidebar_collapsed)

    def test_list_uses_default(self) -> None:
        settings = AppSettings.from_dict({"sidebar_collapsed": ["true"]})
        self.assertFalse(settings.sidebar_collapsed)

    def test_existing_settings_survive_schema_migration(self) -> None:
        settings = AppSettings.from_dict(
            {
                "theme": "dark",
                "ui_scale": 130,
                "remember_last_folder": False,
                "schema_version": 1,
            }
        )
        self.assertEqual(settings.theme, "dark")
        self.assertEqual(settings.ui_scale, 130)
        self.assertFalse(settings.remember_last_folder)
        self.assertFalse(settings.sidebar_collapsed)
        self.assertEqual(settings.schema_version, CURRENT_SCHEMA_VERSION)

    def test_atomic_save_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = SettingsStore(Path(temp))
            expected = AppSettings(sidebar_collapsed=True)
            store.save(expected)
            loaded = store.load()
            self.assertTrue(loaded.sidebar_collapsed)
            self.assertEqual(loaded.schema_version, CURRENT_SCHEMA_VERSION)

    # --- normalized_bool ---

    def test_normalized_bool_true(self) -> None:
        self.assertTrue(normalized_bool(True, False))
        self.assertTrue(normalized_bool(True, True))  # bool True returns True

    def test_normalized_bool_false(self) -> None:
        self.assertFalse(normalized_bool(False, True))

    def test_normalized_bool_non_bool_returns_default(self) -> None:
        self.assertFalse(normalized_bool("true", False))
        self.assertTrue(normalized_bool("anything", True))
        self.assertFalse(normalized_bool(1, False))
        self.assertTrue(normalized_bool(None, True))
        self.assertFalse(normalized_bool([], False))
        self.assertTrue(normalized_bool({}, True))


class ShowToolLogsSettingsTests(unittest.TestCase):
    def test_defaults_to_on(self) -> None:
        self.assertTrue(AppSettings().show_tool_logs)
        self.assertTrue(AppSettings.from_dict({}).show_tool_logs)

    def test_can_be_disabled(self) -> None:
        self.assertFalse(AppSettings.from_dict({"show_tool_logs": False}).show_tool_logs)
        self.assertTrue(AppSettings.from_dict({"show_tool_logs": True}).show_tool_logs)

    def test_non_bool_value_falls_back_to_on(self) -> None:
        self.assertTrue(AppSettings.from_dict({"show_tool_logs": "no"}).show_tool_logs)

    def test_save_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory))
            store.save(AppSettings(show_tool_logs=False))
            self.assertFalse(store.load().show_tool_logs)
            store.save(AppSettings(show_tool_logs=True))
            self.assertTrue(store.load().show_tool_logs)
