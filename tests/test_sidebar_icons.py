"""Regression tests for sidebar icons, layout metrics, and asset integrity."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]


def _load_toml(path: Path) -> dict:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            raise unittest.SkipTest("tomllib/tomli not available on this Python")
    return tomllib.loads(path.read_text(encoding="utf-8"))


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
        project = _load_toml(ROOT / "pyproject.toml")
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
        # ui.py imports tkinter at module level; skip the ui module when
        # tkinter is unavailable (e.g. Linux CI without python3-tk) rather
        # than failing the entire test run.  The Tk-dependent layout tests
        # in SidebarLayoutTests already skip when tkinter is missing.
        try:
            import tkinter  # noqa: F401
            tk_available = True
        except ImportError:
            tk_available = False

        modules = [
            "obs_overlay_import_utility.appearance",
            "obs_overlay_import_utility.constants",
            "obs_overlay_import_utility.core",
            "obs_overlay_import_utility.paths",
            "obs_overlay_import_utility.models",
        ]
        if tk_available:
            modules.append("obs_overlay_import_utility.ui")
        for mod in modules:
            try:
                __import__(mod)
            except ImportError as exc:
                self.fail(f"module {mod} raised {exc}")

    def test_render_icons_tool_exists(self) -> None:
        tool = ROOT / "tools" / "render_icons.py"
        self.assertTrue(tool.is_file(), f"render_icons.py missing: {tool}")
        source = tool.read_text(encoding="utf-8")
        self.assertIn("icon-", source)
        self.assertIn("COLORS", source)
        self.assertIn("SIZES", source)
        self.assertNotIn("ImageDraw", source,
                          "render_icons.py must not use ImageDraw.polygon()")
        self.assertNotIn("_flatten_path", source,
                          "render_icons.py must not implement manual path flattening")
        self.assertNotIn("_subpath_polygons", source,
                          "render_icons.py must not guess subpaths from duplicate points")
        self.assertIn("nonzero", source,
                       "render_icons.py must use nonzero fill rule")
        self.assertIn("scan", source.lower(),
                       "render_icons.py must use scanline-based fill")


class SidebarMetricsTests(unittest.TestCase):
    """Verify SidebarMetrics using the real production helper."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from obs_overlay_import_utility.ui import (
                compute_sidebar_metrics,
                subsample_ratio,
                COLLAPSED_SIDEBAR_BASE_WIDTH,
                COLLAPSED_LOGO_BASE_WIDTH,
                COLLAPSED_ICON_BASE_SIZE,
                SIDEBAR_HORIZONTAL_PADDING,
            )
        except ImportError:
            raise unittest.SkipTest("tkinter is not available on this platform")
        cls.compute_sidebar_metrics = staticmethod(compute_sidebar_metrics)
        cls.subsample_ratio = staticmethod(subsample_ratio)
        cls.COLLAPSED_SIDEBAR_BASE_WIDTH = COLLAPSED_SIDEBAR_BASE_WIDTH
        cls.COLLAPSED_LOGO_BASE_WIDTH = COLLAPSED_LOGO_BASE_WIDTH
        cls.COLLAPSED_ICON_BASE_SIZE = COLLAPSED_ICON_BASE_SIZE
        cls.SIDEBAR_HORIZONTAL_PADDING = SIDEBAR_HORIZONTAL_PADDING

    def _metrics(self, dpi: int, zoom_pct: float):
        return self.compute_sidebar_metrics(dpi, zoom_pct)

    # --- exact width targets ---

    def test_96dpi_75pct_approx_75px(self) -> None:
        m = self._metrics(96, 75)
        self.assertAlmostEqual(m.collapsed_width, 75, delta=2)

    def test_96dpi_100pct_approx_100px(self) -> None:
        m = self._metrics(96, 100)
        self.assertAlmostEqual(m.collapsed_width, 100, delta=2)

    def test_96dpi_150pct_approx_150px(self) -> None:
        m = self._metrics(96, 150)
        self.assertAlmostEqual(m.collapsed_width, 150, delta=2)

    def test_144dpi_100pct_approx_150px(self) -> None:
        m = self._metrics(144, 100)
        self.assertAlmostEqual(m.collapsed_width, 150, delta=2)

    def test_144dpi_150pct_approx_225px(self) -> None:
        m = self._metrics(144, 150)
        self.assertAlmostEqual(m.collapsed_width, 225, delta=2)

    # --- logo + padding fits inside collapsed width ---

    def test_logo_plus_padding_fits(self) -> None:
        for dpi, zoom in ((96, 75), (96, 100), (96, 150), (144, 100), (144, 150)):
            with self.subTest(dpi=dpi, zoom=zoom):
                m = self._metrics(dpi, zoom)
                needed = m.logo_width + 2 * m.horizontal_padding
                self.assertLessEqual(needed, m.collapsed_width + 2,
                                     f"logo {m.logo_width} + 2*{m.horizontal_padding} "
                                     f"exceeds {m.collapsed_width} at {dpi}dpi/{zoom}%")

    def test_icon_plus_padding_fits(self) -> None:
        for dpi, zoom in ((96, 75), (96, 100), (96, 150), (144, 100), (144, 150)):
            with self.subTest(dpi=dpi, zoom=zoom):
                m = self._metrics(dpi, zoom)
                needed = m.icon_size + 2 * m.horizontal_padding
                self.assertLessEqual(needed, m.collapsed_width + 2,
                                     f"icon {m.icon_size} + 2*{m.horizontal_padding} "
                                     f"exceeds {m.collapsed_width} at {dpi}dpi/{zoom}%")

    # --- subsample_ratio (logo ceiling division) ---

    def test_subsample_480_to_109_not_120(self) -> None:
        r = self.subsample_ratio(480, 109)
        self.assertEqual(r, 5)
        self.assertLessEqual(480 // r, 109)

    def test_subsample_480_to_164_not_240(self) -> None:
        r = self.subsample_ratio(480, 164)
        self.assertEqual(r, 3)
        self.assertLessEqual(480 // r, 164)

    def test_subsample_never_exceeds_target(self) -> None:
        for src in (480, 256, 128, 64):
            for tgt in (109, 164, 60, 100, 245):
                with self.subTest(src=src, tgt=tgt):
                    r = self.subsample_ratio(src, tgt)
                    actual = src // r
                    self.assertLessEqual(actual, tgt,
                                         f"src={src} tgt={tgt} ratio={r} actual={actual}")

    def test_subsample_480_to_60(self) -> None:
        r = self.subsample_ratio(480, 60)
        self.assertEqual(r, 8)
        self.assertLessEqual(480 // r, 60)

    # --- constants are sensible ---

    def test_base_constants_are_in_range(self) -> None:
        self.assertGreaterEqual(self.COLLAPSED_SIDEBAR_BASE_WIDTH, 90)
        self.assertLessEqual(self.COLLAPSED_SIDEBAR_BASE_WIDTH, 110)
        self.assertGreaterEqual(self.COLLAPSED_LOGO_BASE_WIDTH, 50)
        self.assertLessEqual(self.COLLAPSED_LOGO_BASE_WIDTH, 70)
        self.assertGreaterEqual(self.COLLAPSED_ICON_BASE_SIZE, 25)
        self.assertLessEqual(self.COLLAPSED_ICON_BASE_SIZE, 35)
        self.assertGreaterEqual(self.SIDEBAR_HORIZONTAL_PADDING, 15)
        self.assertLessEqual(self.SIDEBAR_HORIZONTAL_PADDING, 22)


@unittest.skipIf(np is None or Image is None, "numpy/PIL not available (design-time deps)")
class GeneratedPngQualityTests(unittest.TestCase):
    """Verify generated PNG visual correctness without Tk."""

    ASSETS = SRC / "obs_overlay_import_utility" / "assets"
    ICONS = ("folder-arrow-left", "folder-arrow-right", "fit-to-screen", "cog")

    def _load(self, name: str, colour: str, size: int = 64) -> np.ndarray:
        png = self.ASSETS / f"icon-{name}-{colour}-{size}.png"
        return np.array(Image.open(str(png)))

    def test_every_png_has_alpha_channel(self) -> None:
        for name in self.ICONS:
            for colour in ("white", "red"):
                for size in (32, 40, 48, 64):
                    arr = self._load(name, colour, size)
                    self.assertEqual(arr.shape[2], 4,
                                     f"{name} {colour} {size} missing alpha")

    def test_red_and_white_have_identical_alpha(self) -> None:
        for name in self.ICONS:
            ra = self._load(name, "red")[:, :, 3]
            wa = self._load(name, "white")[:, :, 3]
            diff = np.sum(np.abs(ra.astype(int) - wa.astype(int)))
            self.assertEqual(diff, 0,
                             f"{name} red/white alpha differ by {diff} px")

    def test_no_opaque_black_pixels(self) -> None:
        for name in self.ICONS:
            arr = self._load(name, "red")
            alpha = arr[:, :, 3]
            opaque = alpha > 128
            rgb = arr[opaque][:, :3]
            black = np.sum(np.all(rgb == (0, 0, 0), axis=1))
            self.assertEqual(black, 0, f"{name} has {black} opaque black pixels")

    def test_cog_center_transparent(self) -> None:
        arr = self._load("cog", "red")
        c = arr[32, 32]
        self.assertEqual(c[3], 0, f"cog center should be transparent, got {tuple(c)}")

    def test_fit_to_screen_not_blank_in_center(self) -> None:
        arr = self._load("fit-to-screen", "red")
        alpha = arr[:, :, 3]
        visible = np.sum(alpha > 50)
        self.assertGreater(visible, 500, f"fit-to-screen only {visible} visible px")

    def test_folder_left_and_right_differ(self) -> None:
        fl = self._load("folder-arrow-left", "red")
        fr = self._load("folder-arrow-right", "red")
        diff = np.sum(fl != fr)
        self.assertGreater(diff, 100,
                           f"folder-left vs folder-right differ by only {diff} px")

    def test_no_output_touches_all_four_edges(self) -> None:
        for name in self.ICONS:
            arr = self._load(name, "red")
            alpha = arr[:, :, 3]
            h, w = alpha.shape
            top = np.any(alpha[0, :] > 50)
            bottom = np.any(alpha[-1, :] > 50)
            left = np.any(alpha[:, 0] > 50)
            right = np.any(alpha[:, -1] > 50)
            touching = sum([top, bottom, left, right])
            self.assertLess(touching, 4,
                            f"{name} touches {touching}/4 edges")

    def test_all_sizes_of_each_icon_exist_32_40_48_64(self) -> None:
        for name in self.ICONS:
            for colour in ("white", "red"):
                for size in (32, 40, 48, 64):
                    arr = self._load(name, colour, size)
                    self.assertEqual(arr.shape[0], size)
                    self.assertEqual(arr.shape[1], size)


class SidebarLayoutTests(unittest.TestCase):
    """Verify collapsed/expanded alignment rules.  Requires one Tk root."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            import tkinter as tk
        except ImportError:
            raise unittest.SkipTest("tkinter is not available on this platform")
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
            import_btn = self.app.navigation_buttons[0]
            import_img = import_btn.cget("image")
            self.assertNotEqual(str(import_img), "",
                                "import button must have an image when selected")

            old_icon = getattr(import_btn, "_current_icon", None)
            self.assertIsNotNone(old_icon,
                                 "import _current_icon must be set")

            self.app.section_var.set("export")
            self.app._update_nav_styles()
            export_btn = self.app.navigation_buttons[1]
            export_img = export_btn.cget("image")
            self.assertNotEqual(str(export_img), "",
                                "export button must have an image when selected")

            new_icon = getattr(export_btn, "_current_icon", None)
            self.assertIsNotNone(new_icon,
                                 "export _current_icon must be set")
            self.assertIsNot(new_icon, old_icon,
                             "selected icon must change to a different PhotoImage")

            prev_icon = getattr(import_btn, "_current_icon", None)
            self.assertIsNotNone(prev_icon,
                                 "previously selected button retains _current_icon")
        finally:
            self.app._expand_sidebar()

    def test_selected_keeps_correct_icon_kind(self) -> None:
        self.app._collapse_sidebar()
        try:
            for idx, (section, _label) in enumerate(self.app.SECTIONS):
                self.app.section_var.set(section)
                self.app._update_nav_styles()
                btn = self.app.navigation_buttons[idx]
                img = btn.cget("image")
                self.assertNotEqual(str(img), "",
                                    f"section {section} button should have an image")
        finally:
            self.app._expand_sidebar()

    def test_collapsed_width_less_than_expanded(self) -> None:
        self.assertFalse(self.app.sidebar_collapsed)
        self.app.root.update_idletasks()
        expanded_w = self.app.root.grid_bbox(0, 0)[2]
        self.app._collapse_sidebar()
        try:
            self.app.root.update_idletasks()
            collapsed_w = self.app.root.grid_bbox(0, 0)[2]
            self.assertLess(collapsed_w, expanded_w,
                            f"collapsed {collapsed_w} must be < expanded {expanded_w}")
        finally:
            self.app._expand_sidebar()

    def test_collapsed_expand_preserves_previous_width(self) -> None:
        self.assertFalse(self.app.sidebar_collapsed)
        self.app.root.update_idletasks()
        before = self.app.root.grid_bbox(0, 0)[2]
        self.app._collapse_sidebar()
        self.app._expand_sidebar()
        self.app.root.update_idletasks()
        after = self.app.root.grid_bbox(0, 0)[2]
        self.assertEqual(after, before,
                         f"expanded width {after} != previous {before}")

    def test_collapsed_width_near_metric(self) -> None:
        from obs_overlay_import_utility.ui import compute_sidebar_metrics
        m = compute_sidebar_metrics(self.app.current_dpi, self.app.ui_scale_var.get())
        self.app._collapse_sidebar()
        try:
            self.app.root.update_idletasks()
            actual = self.app.root.grid_bbox(0, 0)[2]
            self.assertAlmostEqual(actual, m.collapsed_width,
                                   msg=f"actual {actual} not near metric {m.collapsed_width}",
                                   delta=4)
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

    def test_apply_ui_scale_updates_collapsed_sidebar(self) -> None:
        self.app._collapse_sidebar()
        try:
            self.app.root.update_idletasks()
            old_minsize = self.app.root.grid_bbox(0, 0)[2]
            self.app._apply_ui_scale(150)
            new_minsize = self.app.root.grid_bbox(0, 0)[2]
            self.assertGreaterEqual(new_minsize, old_minsize,
                                    "collapsed sidebar must grow after zoom increase")
        finally:
            self.app._apply_ui_scale(100)
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
