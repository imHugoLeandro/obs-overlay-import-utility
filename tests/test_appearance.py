from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility import appearance  # noqa: E402


def relative_luminance(color: str) -> float:
    values = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in values
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


class AppearanceTests(unittest.TestCase):
    def test_light_and_dark_palettes_keep_readable_contrast(self) -> None:
        for palette in (appearance.LIGHT_PALETTE, appearance.DARK_PALETTE):
            with self.subTest(theme=palette.mode):
                self.assertGreaterEqual(
                    contrast_ratio(palette.foreground, palette.background), 4.5
                )
                self.assertGreaterEqual(
                    contrast_ratio(palette.muted, palette.background), 4.5
                )
                self.assertGreaterEqual(contrast_ratio("#FFFFFF", palette.accent), 4.5)
                self.assertGreaterEqual(
                    contrast_ratio(palette.sidebar_foreground, palette.sidebar), 4.5
                )
                self.assertGreaterEqual(
                    contrast_ratio(palette.sidebar_muted, palette.sidebar), 4.5
                )
                self.assertGreaterEqual(
                    contrast_ratio(
                        palette.console_foreground, palette.console_background
                    ),
                    4.5,
                )

    def test_system_theme_resolves_without_changing_saved_preference(self) -> None:
        with mock.patch.object(appearance, "system_theme_mode", return_value="dark"):
            self.assertIs(appearance.palette_for("system"), appearance.DARK_PALETTE)
        with mock.patch.object(appearance, "system_theme_mode", return_value="light"):
            self.assertIs(appearance.palette_for("system"), appearance.LIGHT_PALETTE)

    def test_zero_window_handle_uses_standard_dpi(self) -> None:
        self.assertEqual(appearance.window_dpi(0), 96)

    def test_portable_build_embeds_per_monitor_v2_manifest(self) -> None:
        manifest = ROOT / "scripts" / "app.manifest"
        ET.parse(manifest)
        text = manifest.read_text(encoding="utf-8")
        self.assertIn("PerMonitorV2,PerMonitor,System", text)
        self.assertIn("true/pm", text)
        build_script = (ROOT / "scripts" / "build_portable_tk.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '--manifest (Join-Path $Root "scripts\\app.manifest")', build_script
        )

    def test_ui_keeps_a_dependency_free_portable_runtime(self) -> None:
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore[no-redef]
            except ImportError:
                self.skipTest("tomllib/tomli not available on this Python")
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        deps = project["project"]["dependencies"]
        self.assertEqual(deps, [], f"unexpected runtime dependencies: {deps}")
        source = (ROOT / "src" / "obs_overlay_import_utility" / "ui.py").read_text(
            encoding="utf-8"
        )
        for heavyweight in ("PySide", "PyQt", "customtkinter", "ttkbootstrap"):
            self.assertNotIn(heavyweight, source)
        self.assertNotIn("ctypes", source)
        self.assertNotIn("MDI_CODEPOINTS", source)
        self.assertNotIn("_register_mdi_font", source)
        self.assertNotIn("materialdesignicons-webfont.ttf", source)
        self.assertNotIn("from .svg_renderer import", source)


if __name__ == "__main__":
    unittest.main()
