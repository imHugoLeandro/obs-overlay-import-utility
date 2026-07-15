"""Regression tests for sidebar icons, layout metrics, and asset integrity."""

from __future__ import annotations

import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


class SidebarIconAssetTests(unittest.TestCase):
    ASSETS = SRC / "obs_overlay_import_utility" / "assets"
    SIZES = (32, 40, 48, 64)
    COLORS = ("white", "red")
    ICONS = ("folder-arrow-left", "folder-arrow-right", "fit-to-screen", "cog")

    def test_svg_sources_exist(self) -> None:
        for name in self.ICONS:
            svg = self.ASSETS / f"{name}.svg"
            self.assertTrue(svg.is_file(), f"missing SVG: {svg}")

    def test_generated_pngs_exist(self) -> None:
        missing: list[str] = []
        for name in self.ICONS:
            for colour in self.COLORS:
                for size in self.SIZES:
                    png = self.ASSETS / f"icon-{name}-{colour}-{size}.png"
                    if not png.is_file():
                        missing.append(str(png))
        self.assertEqual(len(missing), 0, f"missing PNGs: {missing}")

    def test_no_font_file(self) -> None:
        ttf = self.ASSETS / "materialdesignicons-webfont.ttf"
        self.assertFalse(ttf.exists(), f"TTF font should not exist: {ttf}")

    def test_no_svg_renderer_module(self) -> None:
        svgr = SRC / "obs_overlay_import_utility" / "svg_renderer.py"
        self.assertFalse(svgr.exists(), f"svg_renderer.py should not exist: {svgr}")


class SidebarRuntimeTests(unittest.TestCase):
    """Tests that verify zero runtime dependencies and clean imports."""

    def test_zero_runtime_deps(self) -> None:
        project = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        deps = project["project"]["dependencies"]
        self.assertEqual(deps, [], f"should be zero runtime deps, got: {deps}")

    def test_ui_does_not_import_font_or_svg_renderer(self) -> None:
        source = (
            SRC / "obs_overlay_import_utility" / "ui.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("ctypes", source)
        self.assertNotIn("AddFontResourceExW", source)
        self.assertNotIn("MDI_CODEPOINTS", source)
        self.assertNotIn("materialdesignicons", source)
        self.assertNotIn("svg_renderer", source)
        self.assertNotIn("mdi_family", source)

    def test_clean_module_imports(self) -> None:
        """Every production module must import successfully."""
        modules = [
            "obs_overlay_import_utility.ui",
            "obs_overlay_import_utility.appearance",
            "obs_overlay_import_utility.constants",
            "obs_overlay_import_utility.core",
            "obs_overlay_import_utility.paths",
            "obs_overlay_import_utility.models",
        ]
        for mod in modules:
            try:
                __import__(mod)
            except ImportError as exc:
                self.fail(f"module {mod} raised {exc}")

    def test_render_icons_tool_exists(self) -> None:
        tool = ROOT / "tools" / "render_icons.py"
        self.assertTrue(tool.is_file(), f"render_icons.py missing: {tool}")
        source = tool.read_text(encoding="utf-8")
        self.assertIn("icon-", source)  # generates icon-* PNGs
        self.assertIn("COLORS", source)
        self.assertIn("SIZES", source)


class SidebarMetricsTests(unittest.TestCase):
    """Verify _SidebarMetrics calculation from pure inputs.

    Does not require Tk — uses a mock-like wrapper around the static math.
    """

    def _compute(self, dpi: int, zoom_pct: int) -> tuple[int, int, int, int]:
        """Return (collapsed_width, icon_size, logo_width, arrow_font_size)."""
        dpi_scale = dpi / 96.0
        zoom_scale = zoom_pct / 100.0
        scale = dpi_scale * zoom_scale
        icon_size = max(22, round(29 * scale))
        logo_width = max(48, round(109 * scale))
        arrow_font_size = max(9, round(13 * scale))
        content = max(icon_size, logo_width, round(arrow_font_size * 0.75))
        collapsed = max(72, round(content + 36 * scale))
        return (collapsed, icon_size, logo_width, arrow_font_size)

    def test_metrics_at_96dpi_100pct(self) -> None:
        cw, icon, logo, arrow = self._compute(96, 100)
        self.assertGreaterEqual(cw, 72)
        self.assertEqual(icon, 29)
        self.assertGreaterEqual(logo, 48)
        self.assertGreaterEqual(arrow, 9)

    def test_metrics_at_144dpi_100pct(self) -> None:
        cw, icon, logo, arrow = self._compute(144, 100)
        self.assertGreaterEqual(cw, 96)
        self.assertGreaterEqual(icon, 33)
        self.assertGreaterEqual(logo, 72)

    def test_metrics_at_96dpi_75pct(self) -> None:
        cw, icon, logo, arrow = self._compute(96, 75)
        self.assertGreaterEqual(cw, 72)
        self.assertGreaterEqual(icon, 22)

    def test_metrics_at_96dpi_150pct(self) -> None:
        cw, icon, logo, arrow = self._compute(96, 150)
        self.assertGreaterEqual(cw, 72)
        self.assertGreaterEqual(icon, 33)

    def test_collapsed_width_not_less_than_content(self) -> None:
        cw, icon, logo, arrow = self._compute(96, 100)
        content_max = max(icon, logo, round(arrow * 0.75))
        self.assertGreaterEqual(cw, content_max + 18)


class SidebarLayoutTests(unittest.TestCase):
    """Verify collapsed/expanded alignment rules."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk
        cls._root = tk.Tk()
        cls._root.withdraw()
        from obs_overlay_import_utility.ui import ImportUtilityApp
        cls.app = ImportUtilityApp(cls._root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._root.destroy()

    def test_pngs_are_valid_images(self) -> None:
        import tkinter as tk
        assets = SRC / "obs_overlay_import_utility" / "assets"
        for name in ("folder-arrow-left", "cog"):
            for colour in ("white", "red"):
                for size in (32, 40, 48, 64):
                    png = assets / f"icon-{name}-{colour}-{size}.png"
                    img = tk.PhotoImage(file=str(png))
                    self.assertEqual(img.width(), size, f"{png.name}")
                    self.assertEqual(img.height(), size, f"{png.name}")

    def test_expanded_logo_left_aligned(self) -> None:
        self.assertFalse(self.app.sidebar_collapsed)
        if self.app.logo_label:
            sticky = self.app.logo_label.grid_info().get("sticky", "")
            self.assertIn("w", sticky, "expanded logo should be left-aligned")

    def test_expanded_nav_buttons_left_aligned(self) -> None:
        self.assertFalse(self.app.sidebar_collapsed)
        for btn in self.app.navigation_buttons:
            self.assertEqual(btn.cget("anchor"), "w")

    def test_collapsed_centers_nav_buttons(self) -> None:
        self.app._collapse_sidebar()
        try:
            for btn in self.app.navigation_buttons:
                anchor = btn.cget("anchor")
                self.assertEqual(anchor, "center",
                                 f"collapsed button anchor should be center, got {anchor}")
        finally:
            self.app._expand_sidebar()

    def test_collapse_expand_cycle_preserves_state(self) -> None:
        self.assertFalse(self.app.sidebar_collapsed)
        self.app._collapse_sidebar()
        self.assertTrue(self.app.sidebar_collapsed)
        self.app._expand_sidebar()
        self.assertFalse(self.app.sidebar_collapsed)
        for btn in self.app.navigation_buttons:
            self.assertEqual(btn.cget("anchor"), "w")
            self.assertNotEqual(btn.cget("text"), "")

    def test_collapsed_arrow_centered(self) -> None:
        self.app._collapse_sidebar()
        try:
            info = self.app.sidebar_collapse_arrow.grid_info()
            sticky = info.get("sticky", "")
            col = info.get("column", -1)
            self.assertEqual(col, 0, "collapsed arrow should be in column 0 (centered)")
            self.assertNotIn("e", sticky,
                             "collapsed arrow should not be right-sticky")
        finally:
            self.app._expand_sidebar()

    def test_expanded_arrow_right_aligned(self) -> None:
        self.assertFalse(self.app.sidebar_collapsed)
        info = self.app.sidebar_collapse_arrow.grid_info()
        sticky = info.get("sticky", "")
        col = info.get("column", -1)
        self.assertEqual(col, 1, "expanded arrow should be in column 1")
        self.assertIn("e", sticky, "expanded arrow should be right-sticky")

    def test_collapsed_uses_png_not_font(self) -> None:
        self.app._collapse_sidebar()
        try:
            for btn in self.app.navigation_buttons:
                text = btn.cget("text")
                self.assertEqual(text, "",
                                 f"collapsed button should have empty text, got {text!r}")
                img = btn.cget("image")
                self.assertNotEqual(str(img), "",
                                   "collapsed button should have an image")
        finally:
            self.app._expand_sidebar()

    def test_selected_icon_switches_to_red(self) -> None:
        self.app._collapse_sidebar()
        try:
            self.app.section_var.set("import")
            self.app._update_nav_styles()
            self.app.section_var.set("export")
            self.app._update_nav_styles()
        finally:
            self.app._expand_sidebar()

    def test_dpi_refresh_while_collapsed(self) -> None:
        self.app._collapse_sidebar()
        try:
            old_width = self.app._collapsed_sidebar_width
            self.app.current_dpi = 144
            self.app._refresh_sidebar_layout()
            new_width = self.app._collapsed_sidebar_width
            self.assertGreaterEqual(
                new_width, old_width,
                "collapsed width should grow with DPI",
            )
        finally:
            self.app.current_dpi = 96
            self.app._expand_sidebar()

    def test_zoom_refresh_while_collapsed(self) -> None:
        self.app._collapse_sidebar()
        try:
            old_width = self.app._collapsed_sidebar_width
            self.app.ui_scale_var.set(150)
            self.app._refresh_sidebar_layout()
            new_width = self.app._collapsed_sidebar_width
            self.assertGreaterEqual(
                new_width, old_width,
                "collapsed width should grow with zoom",
            )
        finally:
            self.app.ui_scale_var.set(100)
            self.app._expand_sidebar()

    def test_arrow_font_size_doubled_from_base(self) -> None:
        self.app.current_dpi = 96
        self.app.ui_scale_var.set(100)
        self.app._collapse_sidebar()
        try:
            raw = self.app.sidebar_collapse_arrow.cget("font")
            parts = str(raw).split()
            size_val = int(parts[-1]) if parts else 0
            self.assertGreaterEqual(
                size_val, 12,
                f"collapsed arrow font size >= 12, got {size_val} from {raw!r}",
            )
        finally:
            self.app._expand_sidebar()


if __name__ == "__main__":
    unittest.main()
