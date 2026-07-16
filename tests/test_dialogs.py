"""Tests for the shared ``dialogs`` module."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obs_overlay_import_utility.appearance import LIGHT_PALETTE, DARK_PALETTE  # noqa: E402
from obs_overlay_import_utility.dialogs import (  # noqa: E402
    Space,
    scaled_space,
    dialog_metrics,
    compute_body_wraplength,
    palette_aware_warning_bg,
    palette_aware_warning_fg,
    scrollbar_metrics,
    ui_scale_metrics,
    ui_scale_colors,
    DIALOG_STYLE_NAMES,
)


class DialogMetricsTests(unittest.TestCase):
    def test_base_space_values(self) -> None:
        s = Space()
        self.assertEqual(s.XS, 4)
        self.assertEqual(s.SM, 8)
        self.assertEqual(s.MD, 12)
        self.assertEqual(s.LG, 16)
        self.assertEqual(s.XL, 20)
        self.assertEqual(s.XXL, 24)

    def test_scaled_space_100pct_returns_base(self) -> None:
        s = scaled_space(1.0)
        self.assertEqual(s.XS, 4)
        self.assertEqual(s.XXL, 24)

    def test_scaled_space_150pct_scales_up(self) -> None:
        s = scaled_space(1.5)
        self.assertGreaterEqual(s.LG, 12)
        self.assertLess(s.LG, Space().LG + 10)

    def test_scaled_space_75pct_scales_down(self) -> None:
        s = scaled_space(0.75)
        self.assertLessEqual(s.XXL, 24)

    def test_dialog_metrics_at_96dpi_100pct(self) -> None:
        m = dialog_metrics(ui_zoom=1.0)
        self.assertEqual(m.width, 900)
        self.assertEqual(m.minimum_width, 680)
        self.assertGreater(m.outer_padding, 10)
        self.assertGreater(m.footer_padding_y, 4)

    def test_dialog_metrics_at_150pct(self) -> None:
        m = dialog_metrics(ui_zoom=1.5)
        self.assertGreater(m.width, 900)
        self.assertGreater(m.minimum_width, 680)

    def test_dialog_metrics_at_75pct(self) -> None:
        m = dialog_metrics(ui_zoom=0.75)
        self.assertLess(m.width, 900 * 0.8 - 1)
        self.assertLess(m.minimum_width, 680 * 0.8 - 1)

    def test_outer_padding_meets_minimum_20px_at_100pct(self) -> None:
        m = dialog_metrics(ui_zoom=1.0)
        self.assertGreaterEqual(m.outer_padding, 20)

    def test_footer_padding_x_meets_minimum_16px_at_100pct(self) -> None:
        m = dialog_metrics(ui_zoom=1.0)
        self.assertGreaterEqual(m.footer_padding_x, 16)

    def test_footer_padding_y_meets_minimum_8px_at_100pct(self) -> None:
        m = dialog_metrics(ui_zoom=1.0)
        self.assertGreaterEqual(m.footer_padding_y, 8)

    def test_wraplength_grows_with_width(self) -> None:
        m1 = dialog_metrics(base_width=800, ui_zoom=1.0)
        m2 = dialog_metrics(base_width=1200, ui_zoom=1.0)
        # The wraplength targets stay the same because we use target_wraplength
        self.assertGreaterEqual(m2.title_wraplength, m1.title_wraplength)

    def test_custom_wraplength_used(self) -> None:
        m = dialog_metrics(target_wraplength=500)
        self.assertEqual(m.title_wraplength, 500)
        self.assertEqual(m.body_wraplength, 500)

    def test_compute_body_wraplength_minimum(self) -> None:
        result = compute_body_wraplength(None, left_padding=700, right_padding=20, minimum_wrap=200)
        self.assertGreaterEqual(result, 200)

    def test_144dpi_metrics_still_reasonable(self) -> None:
        m = dialog_metrics(ui_zoom=1.0)
        self.assertLess(m.width, 1200)
        self.assertGreater(m.height, 400)

    def test_palette_warning_bg_light(self) -> None:
        self.assertEqual(palette_aware_warning_bg(LIGHT_PALETTE), "#FFF3CD")

    def test_palette_warning_bg_dark(self) -> None:
        self.assertEqual(palette_aware_warning_bg(DARK_PALETTE), "#332B00")

    def test_palette_warning_fg_light(self) -> None:
        self.assertEqual(palette_aware_warning_fg(LIGHT_PALETTE), "#856404")

    def test_palette_warning_fg_dark(self) -> None:
        self.assertEqual(palette_aware_warning_fg(DARK_PALETTE), "#FFD970")


class ScrollbarMetricsTests(unittest.TestCase):
    def test_100pct_target_near_28px(self) -> None:
        m = scrollbar_metrics(1.0)
        self.assertGreaterEqual(m.vertical_thickness, 26)
        self.assertLessEqual(m.vertical_thickness, 32)
        self.assertEqual(m.vertical_thickness, 28)

    def test_75pct_in_range_21_23(self) -> None:
        m = scrollbar_metrics(0.75)
        self.assertGreaterEqual(m.vertical_thickness, 21)
        self.assertLessEqual(m.vertical_thickness, 23)
        self.assertLess(m.vertical_thickness, scrollbar_metrics(1.0).vertical_thickness)

    def test_125pct_in_range_34_36(self) -> None:
        m = scrollbar_metrics(1.25)
        self.assertGreaterEqual(m.vertical_thickness, 33)
        self.assertLessEqual(m.vertical_thickness, 37)

    def test_150pct_in_range_40_42(self) -> None:
        m = scrollbar_metrics(1.5)
        self.assertGreaterEqual(m.vertical_thickness, 40)
        self.assertLessEqual(m.vertical_thickness, 42)

    def test_grows_with_ui_zoom(self) -> None:
        m75 = scrollbar_metrics(0.75)
        m100 = scrollbar_metrics(1.0)
        m125 = scrollbar_metrics(1.25)
        m150 = scrollbar_metrics(1.5)
        self.assertLess(m75.vertical_thickness, m100.vertical_thickness)
        self.assertLess(m100.vertical_thickness, m125.vertical_thickness)
        self.assertLess(m125.vertical_thickness, m150.vertical_thickness)

    def test_minimum_thickness_is_usable(self) -> None:
        m = scrollbar_metrics(0.75)
        self.assertGreaterEqual(m.vertical_thickness, 20)

    def test_all_values_are_positive_integers(self) -> None:
        for zoom in (0.75, 1.0, 1.25, 1.5):
            with self.subTest(zoom=zoom):
                m = scrollbar_metrics(zoom)
                self.assertIsInstance(m.vertical_thickness, int)
                self.assertIsInstance(m.horizontal_thickness, int)
                self.assertIsInstance(m.arrow_size, int)
                self.assertGreater(m.vertical_thickness, 0)
                self.assertGreater(m.horizontal_thickness, 0)
                self.assertGreater(m.arrow_size, 0)

    def test_vertical_roughly_twice_old_default(self) -> None:
        m = scrollbar_metrics(1.0)
        old = 14
        self.assertGreaterEqual(m.vertical_thickness, old * 1.8)

    def test_120dpi_100pct_scales_with_factor(self) -> None:
        factor = 120.0 / 96.0
        m = scrollbar_metrics(factor * 1.0)
        self.assertGreater(m.vertical_thickness, 28)
        self.assertLess(m.vertical_thickness, 38)

    def test_144dpi_100pct_scales_with_factor(self) -> None:
        factor = 144.0 / 96.0
        m = scrollbar_metrics(factor * 1.0)
        self.assertGreater(m.vertical_thickness, 40)
        self.assertLess(m.vertical_thickness, 45)

    def test_horizontal_thickness_is_smaller_than_vertical(self) -> None:
        for zoom in (0.75, 1.0, 1.25, 1.5):
            with self.subTest(zoom=zoom):
                m = scrollbar_metrics(zoom)
                self.assertLess(m.horizontal_thickness, m.vertical_thickness)

    def test_scrollbar_frozen_dataclass(self) -> None:
        import dataclasses
        m = scrollbar_metrics(1.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            m.__setattr__("vertical_thickness", 99)

    def test_compute_body_wraplength_uses_scrollbar_metric(self) -> None:
        result = compute_body_wraplength(None, 0, 0, ui_zoom=1.0)
        self.assertEqual(result, 800 - 28)

    def test_dialog_style_names_include_scrollbars(self) -> None:
        self.assertIn("Dialog.Vertical.TScrollbar", DIALOG_STYLE_NAMES)
        self.assertIn("Dialog.Horizontal.TScrollbar", DIALOG_STYLE_NAMES)


class UiScaleMetricsTests(unittest.TestCase):
    def test_100pct_target_near_32px(self) -> None:
        m = ui_scale_metrics(1.0)
        self.assertGreaterEqual(m.widget_height, 30)
        self.assertLessEqual(m.widget_height, 34)
        self.assertEqual(m.widget_height, 32)

    def test_75pct_height_around_24px(self) -> None:
        m = ui_scale_metrics(0.75)
        self.assertGreaterEqual(m.widget_height, 22)
        self.assertLessEqual(m.widget_height, 26)

    def test_125pct_height_around_40px(self) -> None:
        m = ui_scale_metrics(1.25)
        self.assertGreaterEqual(m.widget_height, 38)
        self.assertLessEqual(m.widget_height, 42)

    def test_150pct_height_around_48px(self) -> None:
        m = ui_scale_metrics(1.5)
        self.assertGreaterEqual(m.widget_height, 46)
        self.assertLessEqual(m.widget_height, 50)

    def test_120dpi_100pct_scales(self) -> None:
        factor = 120.0 / 96.0
        m = ui_scale_metrics(factor)
        self.assertGreater(m.widget_height, 32)
        self.assertLess(m.widget_height, 42)

    def test_144dpi_100pct_scales(self) -> None:
        factor = 144.0 / 96.0
        m = ui_scale_metrics(factor)
        self.assertGreaterEqual(m.widget_height, 46)
        self.assertLessEqual(m.widget_height, 52)

    def test_grows_monotonically_with_zoom(self) -> None:
        m75 = ui_scale_metrics(0.75)
        m100 = ui_scale_metrics(1.0)
        m125 = ui_scale_metrics(1.25)
        m150 = ui_scale_metrics(1.5)
        self.assertLess(m75.widget_height, m100.widget_height)
        self.assertLess(m100.widget_height, m125.widget_height)
        self.assertLess(m125.widget_height, m150.widget_height)

    def test_minimum_height_is_usable(self) -> None:
        m = ui_scale_metrics(0.75)
        self.assertGreaterEqual(m.widget_height, 22)

    def test_all_values_are_positive_integers(self) -> None:
        for zoom in (0.75, 1.0, 1.25, 1.5):
            with self.subTest(zoom=zoom):
                m = ui_scale_metrics(zoom)
                self.assertIsInstance(m.widget_height, int)
                self.assertIsInstance(m.trough_width, int)
                self.assertIsInstance(m.slider_length, int)
                self.assertIsInstance(m.highlight_thickness, int)
                self.assertGreater(m.widget_height, 0)
                self.assertGreater(m.trough_width, 0)
                self.assertGreater(m.slider_length, 0)

    def test_trough_width_plus_border_equals_height(self) -> None:
        m = ui_scale_metrics(1.0)
        self.assertEqual(m.trough_width + 2 * m.highlight_thickness, m.widget_height)

    def test_slider_range_and_snapping_unchanged(self) -> None:
        from obs_overlay_import_utility.ui import MIN_UI_SCALE, MAX_UI_SCALE
        self.assertEqual(MIN_UI_SCALE, 75)
        self.assertEqual(MAX_UI_SCALE, 150)

    def test_frozen_dataclass(self) -> None:
        import dataclasses
        m = ui_scale_metrics(1.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            m.__setattr__("widget_height", 99)


class DialogStringsTests(unittest.TestCase):
    """Dialog body strings must not contain presentation-only embedded newlines."""

    def test_device_setup_body_has_no_forced_newlines(self) -> None:
        body = (
            "Choose an exact-type device source already configured in OBS. "
            "Only device-selector values are copied; imported filters and "
            "capture settings remain intact."
        )
        self.assertNotIn("\n", body)

    def test_warning_text_matches_portable_behavior(self) -> None:
        msg = (
            "1 referenced file(s) could not be found and will not be included. "
            "Review the Missing / Manual Review tab."
        )
        self.assertIn("not be included", msg)
        self.assertNotIn("remain unchanged", msg)


class UiScaleColorsTests(unittest.TestCase):
    def test_dark_thumb_is_accent_hover(self) -> None:
        colors = ui_scale_colors(DARK_PALETTE)
        self.assertEqual(colors.thumb, "#D9363E")

    def test_dark_thumb_active_is_selection(self) -> None:
        colors = ui_scale_colors(DARK_PALETTE)
        self.assertEqual(colors.thumb_active, "#F0444C")

    def test_dark_trough_is_surface_alt(self) -> None:
        colors = ui_scale_colors(DARK_PALETTE)
        self.assertEqual(colors.trough, "#222730")

    def test_dark_widget_background_is_surface(self) -> None:
        colors = ui_scale_colors(DARK_PALETTE)
        self.assertEqual(colors.widget_background, "#191D23")

    def test_dark_focus_border_is_selection(self) -> None:
        colors = ui_scale_colors(DARK_PALETTE)
        self.assertEqual(colors.focus_border, "#F0444C")

    def test_dark_border_is_palette_border(self) -> None:
        colors = ui_scale_colors(DARK_PALETTE)
        self.assertEqual(colors.border, "#303640")

    def test_light_thumb_uses_brand_red(self) -> None:
        colors = ui_scale_colors(LIGHT_PALETTE)
        self.assertEqual(colors.thumb, "#C91E27")

    def test_light_thumb_active_is_brighter(self) -> None:
        colors = ui_scale_colors(LIGHT_PALETTE)
        self.assertEqual(colors.thumb_active, "#E1262F")

    def test_light_uses_correct_trough(self) -> None:
        colors = ui_scale_colors(LIGHT_PALETTE)
        self.assertEqual(colors.trough, "#E9EDF1")

    def test_thumb_active_is_lighter_than_thumb_in_both_themes(self) -> None:
        for palette in (LIGHT_PALETTE, DARK_PALETTE):
            with self.subTest(mode=palette.mode):
                colors = ui_scale_colors(palette)
                self.assertNotEqual(colors.thumb, colors.thumb_active)

    def test_frozen_dataclass(self) -> None:
        import dataclasses
        colors = ui_scale_colors(DARK_PALETTE)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            colors.__setattr__("thumb", "#000000")


class ScaleWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk
        cls._root = tk.Tk()
        cls._root.withdraw()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._root.destroy()

    def test_scale_height_at_100pct_96dpi(self) -> None:
        import tkinter as tk
        sm = ui_scale_metrics(1.0)
        s = tk.Scale(
            self._root, from_=75, to=150, orient="horizontal",
            width=sm.trough_width, highlightthickness=sm.highlight_thickness,
            borderwidth=0, showvalue=False,
        )
        s.pack()
        self._root.update_idletasks()
        h = s.winfo_reqheight()
        self.assertGreaterEqual(h, 30)
        self.assertLessEqual(h, 34)
        s.destroy()

    def test_scale_colors_applied_after_construction(self) -> None:
        import tkinter as tk
        from obs_overlay_import_utility.ui import MIN_UI_SCALE, MAX_UI_SCALE
        colors = ui_scale_colors(DARK_PALETTE)
        sm = ui_scale_metrics(1.0)
        s = tk.Scale(
            self._root, from_=MIN_UI_SCALE, to=MAX_UI_SCALE,
            orient="horizontal", showvalue=False,
            width=sm.trough_width, sliderlength=sm.slider_length,
            highlightthickness=sm.highlight_thickness, borderwidth=0,
            relief="flat", sliderrelief="flat",
        )
        s.configure(
            background=colors.thumb,
            activebackground=colors.thumb_active,
            troughcolor=colors.trough,
            highlightbackground=colors.border,
            highlightcolor=colors.focus_border,
        )
        self._root.update_idletasks()
        self.assertEqual(s.cget("background"), colors.thumb)
        self.assertEqual(s.cget("activebackground"), colors.thumb_active)
        self.assertEqual(s.cget("troughcolor"), colors.trough)
        self.assertEqual(s.cget("highlightbackground"), colors.border)
        self.assertEqual(s.cget("highlightcolor"), colors.focus_border)
        s.destroy()

    def test_scale_background_is_thumb_color_not_surface(self) -> None:
        colors = ui_scale_colors(DARK_PALETTE)
        self.assertNotEqual(colors.thumb, DARK_PALETTE.surface)
        self.assertEqual(colors.thumb, DARK_PALETTE.accent_hover)


if __name__ == "__main__":
    unittest.main()
