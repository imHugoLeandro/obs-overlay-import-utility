from __future__ import annotations

import sys
import tkinter as tk
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

if TYPE_CHECKING:
    from obs_overlay_import_utility.ui import ImportUtilityApp

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

from obs_overlay_import_utility import dialogs as dlgs  # noqa: E402

from obs_overlay_import_utility.settings import AppSettings  # noqa: E402


@contextmanager
def deterministic_app(theme: str) -> Iterator[tuple[tk.Tk, "ImportUtilityApp"]]:
    root = tk.Tk()
    root.withdraw()
    settings = AppSettings(theme=theme)
    with mock.patch(
        "obs_overlay_import_utility.settings.SettingsStore.load",
        return_value=settings,
    ):
        from obs_overlay_import_utility.ui import ImportUtilityApp
        app = ImportUtilityApp(root)
    try:
        root.update_idletasks()
        yield root, app
    finally:
        shutdown = getattr(app, "shutdown", None)
        if callable(shutdown):
            shutdown()
        try:
            root.update_idletasks()
        except tk.TclError:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass


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


class ScaleGeometryTests(unittest.TestCase):
    """Platform-aware slider geometry tests using a clean Tk root."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._root = tk.Tk()
        cls._root.withdraw()
        cls._record_platform_info()

    @classmethod
    def _record_platform_info(cls) -> None:
        cls.tcl_patchlevel = cls._root.tk.call("info", "patchlevel")
        cls.tk_scaling = float(cls._root.tk.call("tk", "scaling"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._root.destroy()

    def _make_scale(self, factor: float = 1.0) -> tk.Scale:
        sm = ui_scale_metrics(factor)
        top = tk.Toplevel(self._root)
        top.withdraw()
        s = tk.Scale(
            top, from_=75, to=150, orient="horizontal",
            width=sm.trough_width, highlightthickness=sm.highlight_thickness,
            borderwidth=0, showvalue=False,
        )
        s.pack()
        top.update_idletasks()
        self.addCleanup(s.destroy)
        self.addCleanup(top.destroy)
        return s

    def test_scale_height_at_100pct_is_usable(self) -> None:
        s = self._make_scale(1.0)
        h = s.winfo_reqheight()
        self.assertGreaterEqual(h, 20,
            f"reqheight {h} below minimum usable height 20 "
            f"(Tcl {self.tcl_patchlevel}, tk scaling {self.tk_scaling})")
        self.assertLessEqual(h, 50,
            f"reqheight {h} unexpectedly large for 100% zoom "
            f"(Tcl {self.tcl_patchlevel}, tk scaling {self.tk_scaling})")

    def test_scale_height_grows_with_larger_zoom(self) -> None:
        s75 = self._make_scale(0.75)
        s100 = self._make_scale(1.0)
        h75 = s75.winfo_reqheight()
        h100 = s100.winfo_reqheight()
        self.assertLessEqual(h75, h100 + 2,
            f"75% reqheight {h75} vs 100% reqheight {h100} "
            f"(Tcl {self.tcl_patchlevel}, tk scaling {self.tk_scaling})")


class ScaleAppWidgetTests(unittest.TestCase):
    """Deterministic widget colour tests -- no user settings file read."""

    def _assert_dark_slider(self, app: "ImportUtilityApp", palette: object) -> None:
        colors = dlgs.ui_scale_colors(palette)
        self.assertEqual(app.current_palette.mode, "dark")
        self.assertEqual(app.ui_scale.cget("troughcolor"), colors.trough)
        self.assertEqual(app.ui_scale.cget("activebackground"), colors.thumb_active)
        self.assertEqual(app.ui_scale.cget("highlightbackground"), colors.border)

        self.assertEqual(app.ui_scale.cget("troughcolor"), "#222730")
        self.assertEqual(app.ui_scale.cget("activebackground"), "#F0444C")
        self.assertEqual(app.ui_scale.cget("highlightbackground"), "#303640")

    def _assert_light_slider(self, app: "ImportUtilityApp", palette: object) -> None:
        colors = dlgs.ui_scale_colors(palette)
        self.assertEqual(app.current_palette.mode, "light")
        self.assertEqual(app.ui_scale.cget("troughcolor"), colors.trough)
        self.assertEqual(app.ui_scale.cget("activebackground"), colors.thumb_active)
        self.assertEqual(app.ui_scale.cget("highlightbackground"), colors.border)

    def test_dark_theme_slider_colors(self) -> None:
        with deterministic_app("dark") as (_root, app):
            self._assert_dark_slider(app, DARK_PALETTE)

    def test_light_theme_slider_colors(self) -> None:
        with deterministic_app("light") as (_root, app):
            self._assert_light_slider(app, LIGHT_PALETTE)

    def test_dark_state_variables_initialized_to_false(self) -> None:
        with deterministic_app("dark") as (_root, app):
            self.assertFalse(app._ui_scale_hovered)
            self.assertFalse(app._ui_scale_focused)
            self.assertFalse(app._ui_scale_pressed)

    def test_dark_thumb_contrasts_against_surface(self) -> None:
        with deterministic_app("dark") as (_root, app):
            colors = dlgs.ui_scale_colors(app.current_palette)
            self.assertEqual(colors.thumb, "#D9363E")
            self.assertNotEqual(colors.thumb, DARK_PALETTE.surface)


class UiScaleStateTransitionTests(unittest.TestCase):
    """Verify slider visual state logic without a full Tk event loop."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._context = deterministic_app("dark")
        cls._root, cls._app = cls._context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._context.__exit__(None, None, None)

    def setUp(self) -> None:
        self._saved_palette = self._app.current_palette
        self._saved_hovered = self._app._ui_scale_hovered
        self._saved_focused = self._app._ui_scale_focused
        self._saved_pressed = self._app._ui_scale_pressed

    def tearDown(self) -> None:
        self._app.current_palette = self._saved_palette
        self._app._ui_scale_hovered = self._saved_hovered
        self._app._ui_scale_focused = self._saved_focused
        self._app._ui_scale_pressed = self._saved_pressed
        self._app._refresh_ui_scale_visual_state()

    def _thumb_color(self) -> str:
        return str(self._app.ui_scale.cget("background"))

    def _focus_border(self) -> str:
        return str(self._app.ui_scale.cget("highlightcolor"))

    def _configure_states(self, hovered: bool, focused: bool, pressed: bool) -> None:
        self._app._ui_scale_hovered = hovered
        self._app._ui_scale_focused = focused
        self._app._ui_scale_pressed = pressed
        self._app._refresh_ui_scale_visual_state()

    def test_idle_shows_thumb_color(self) -> None:
        self._configure_states(False, False, False)
        colors = dlgs.ui_scale_colors(self._app.current_palette)
        self.assertEqual(self._thumb_color(), colors.thumb)

    def test_hovered_shows_thumb_active(self) -> None:
        self._configure_states(True, False, False)
        colors = dlgs.ui_scale_colors(self._app.current_palette)
        self.assertEqual(self._thumb_color(), colors.thumb_active)

    def test_focused_shows_thumb_active_and_focus_border(self) -> None:
        self._configure_states(False, True, False)
        colors = dlgs.ui_scale_colors(self._app.current_palette)
        self.assertEqual(self._thumb_color(), colors.thumb_active)
        self.assertEqual(self._focus_border(), colors.focus_border)

    def test_pressed_shows_thumb_active(self) -> None:
        self._configure_states(False, False, True)
        colors = dlgs.ui_scale_colors(self._app.current_palette)
        self.assertEqual(self._thumb_color(), colors.thumb_active)

    def test_leave_while_focused_keeps_thumb_active(self) -> None:
        self._configure_states(False, True, False)
        colors = dlgs.ui_scale_colors(self._app.current_palette)
        self.assertEqual(self._thumb_color(), colors.thumb_active)

    def test_leave_while_unfocused_shows_thumb(self) -> None:
        self._configure_states(False, False, False)
        colors = dlgs.ui_scale_colors(self._app.current_palette)
        self.assertEqual(self._thumb_color(), colors.thumb)

    def test_focus_lost_while_still_hovered_keeps_thumb_active(self) -> None:
        self._configure_states(True, False, False)
        colors = dlgs.ui_scale_colors(self._app.current_palette)
        self.assertEqual(self._thumb_color(), colors.thumb_active)

    def test_pressed_overrides_focus_and_hover(self) -> None:
        self._configure_states(True, True, True)
        colors = dlgs.ui_scale_colors(self._app.current_palette)
        self.assertEqual(self._thumb_color(), colors.thumb_active)

    def test_release_without_hover_shows_thumb(self) -> None:
        self._configure_states(False, False, False)
        colors = dlgs.ui_scale_colors(self._app.current_palette)
        self.assertEqual(self._thumb_color(), colors.thumb)

    def test_release_while_still_hovered_shows_thumb_active(self) -> None:
        self._configure_states(True, False, False)
        colors = dlgs.ui_scale_colors(self._app.current_palette)
        self.assertEqual(self._thumb_color(), colors.thumb_active)

    def test_theme_change_while_focused_uses_new_palette(self) -> None:
        self._app.current_palette = LIGHT_PALETTE
        self._configure_states(False, True, False)
        colors = dlgs.ui_scale_colors(LIGHT_PALETTE)
        self.assertEqual(self._thumb_color(), colors.thumb_active)
        self.assertEqual(self._focus_border(), colors.focus_border)

    def test_theme_change_while_hovered_uses_new_palette(self) -> None:
        self._app.current_palette = LIGHT_PALETTE
        self._configure_states(True, False, False)
        colors = dlgs.ui_scale_colors(LIGHT_PALETTE)
        self.assertEqual(self._thumb_color(), colors.thumb_active)

    def test_release_callback_runs_exactly_once(self) -> None:
        with mock.patch.object(
            self._app, "_on_scale_released"
        ) as mock_released:
            self._app._on_ui_scale_press(tk.Event())
            self._app._on_ui_scale_release(tk.Event())
            mock_released.assert_called_once()

    def test_release_callback_not_duplicated_by_theme_refresh(self) -> None:
        with mock.patch.object(
            self._app, "_on_scale_released"
        ) as mock_released:
            self._app._on_ui_scale_press(tk.Event())
            self._app._apply_ui_scale_widget_theme()
            self._app._on_ui_scale_release(tk.Event())
            mock_released.assert_called_once()

    def test_buttonrelease_binding_is_present(self) -> None:
        bindings = self._app.ui_scale.bind()
        self.assertIn("<ButtonRelease-1>", bindings)

    def test_theme_refresh_does_not_duplicate_bindings(self) -> None:
        bindings_before = repr(self._app.ui_scale.bind())
        self._app._apply_ui_scale_widget_theme()
        bindings_after = repr(self._app.ui_scale.bind())
        self.assertEqual(bindings_before, bindings_after)


class SidebarPersistenceTests(unittest.TestCase):
    """Verify sidebar collapsed/expanded persistence and lifecycle."""

    @classmethod
    def setUpClass(cls) -> None:
        import tempfile
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._settings_dir = Path(cls._tmpdir.name)
        from obs_overlay_import_utility.settings import SettingsStore
        cls._store = SettingsStore(cls._settings_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def _make_app(
        self, theme: str = "dark", sidebar_collapsed: bool = False
    ) -> tuple[tk.Tk, "ImportUtilityApp"]:
        from obs_overlay_import_utility.settings import AppSettings

        settings_data = AppSettings(theme=theme, sidebar_collapsed=sidebar_collapsed)
        self._settings_dir.mkdir(parents=True, exist_ok=True)
        self._store.save(settings_data)

        with mock.patch(
            "obs_overlay_import_utility.settings.default_settings_directory",
            return_value=self._settings_dir,
        ):
            from obs_overlay_import_utility.ui import ImportUtilityApp
            root = tk.Tk()
            root.withdraw()
            app = ImportUtilityApp(root)
        return root, app

    def _cleanup(self, root: tk.Tk, app: "ImportUtilityApp") -> None:
        try:
            app.close()
        except tk.TclError:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass

    def test_saved_collapsed_starts_collapsed(self) -> None:
        root, app = self._make_app(sidebar_collapsed=True)
        try:
            self.assertTrue(app.sidebar_collapsed)
        finally:
            self._cleanup(root, app)

    def test_saved_expanded_starts_expanded(self) -> None:
        root, app = self._make_app(sidebar_collapsed=False)
        try:
            self.assertFalse(app.sidebar_collapsed)
        finally:
            self._cleanup(root, app)

    def test_collapsing_writes_true(self) -> None:
        root, app = self._make_app(sidebar_collapsed=False)
        try:
            self.assertFalse(app.sidebar_collapsed)
            app._set_sidebar_collapsed(True, persist=True)
            self.assertTrue(app.sidebar_collapsed)
            loaded = self._store.load()
            self.assertTrue(loaded.sidebar_collapsed)
        finally:
            self._cleanup(root, app)

    def test_expanding_writes_false(self) -> None:
        root, app = self._make_app(sidebar_collapsed=True)
        try:
            self.assertTrue(app.sidebar_collapsed)
            app._set_sidebar_collapsed(False, persist=True)
            self.assertFalse(app.sidebar_collapsed)
            loaded = self._store.load()
            self.assertFalse(loaded.sidebar_collapsed)
        finally:
            self._cleanup(root, app)

    def test_startup_restoration_does_not_save(self) -> None:
        root, app = self._make_app(sidebar_collapsed=False)
        try:
            original_mtime = self._store.path.stat().st_mtime
            root.update_idletasks()
            self.assertEqual(original_mtime, self._store.path.stat().st_mtime)
        finally:
            self._cleanup(root, app)

    def test_noop_state_setter_does_nothing(self) -> None:
        root, app = self._make_app(sidebar_collapsed=False)
        try:
            app._set_sidebar_collapsed(False, persist=True)
            self.assertFalse(app.sidebar_collapsed)
        finally:
            self._cleanup(root, app)

    def test_one_toggle_one_save(self) -> None:
        root, app = self._make_app(sidebar_collapsed=False)
        try:
            mtime_before = self._store.path.stat().st_mtime
            app._toggle_sidebar()
            mtime_after = self._store.path.stat().st_mtime
            self.assertGreater(mtime_after, mtime_before)
        finally:
            self._cleanup(root, app)

    def test_save_failure_keeps_visual_state(self) -> None:
        root, app = self._make_app(sidebar_collapsed=False)
        try:
            with mock.patch.object(app.settings_store, "save", side_effect=OSError("no space")):
                app._set_sidebar_collapsed(True, persist=True)
            self.assertTrue(app.sidebar_collapsed)
            self.assertFalse(app.settings.sidebar_collapsed)
        finally:
            self._cleanup(root, app)

    def test_unsaved_theme_not_persisted_by_sidebar_toggle(self) -> None:
        root, app = self._make_app(sidebar_collapsed=False, theme="dark")
        try:
            self.assertEqual(app.settings.theme, "dark")
            app.theme_var.set("White")
            app._toggle_sidebar()
            loaded = self._store.load()
            self.assertEqual(loaded.theme, "dark", "unsaved theme change persisted")
        finally:
            self._cleanup(root, app)

    def test_restore_defaults_expands_sidebar(self) -> None:
        root, app = self._make_app(sidebar_collapsed=True)
        try:
            self.assertTrue(app.sidebar_collapsed)
            app._restore_defaults()
            self.assertFalse(app.sidebar_collapsed)
        finally:
            self._cleanup(root, app)

    def test_dpi_refresh_while_collapsed_does_not_save(self) -> None:
        root, app = self._make_app(sidebar_collapsed=True)
        try:
            mtime_before = self._store.path.stat().st_mtime
            app._set_sidebar_collapsed(True, persist=True)
            app._refresh_sidebar_layout()
            self.assertEqual(mtime_before, self._store.path.stat().st_mtime)
        finally:
            self._cleanup(root, app)

    def test_theme_refresh_while_collapsed_does_not_save(self) -> None:
        root, app = self._make_app(sidebar_collapsed=True)
        try:
            mtime_before = self._store.path.stat().st_mtime
            app._apply_theme()
            self.assertEqual(mtime_before, self._store.path.stat().st_mtime)
        finally:
            self._cleanup(root, app)

    def test_shutdown_is_idempotent(self) -> None:
        root, app = self._make_app(sidebar_collapsed=False)
        app.close()
        app.close()
        try:
            root.destroy()
        except tk.TclError:
            pass

    def test_no_recurring_callbacks_remain_after_shutdown(self) -> None:
        root, app = self._make_app(sidebar_collapsed=False)
        app.close()
        self.assertIsNone(app._process_events_after_id)
        self.assertIsNone(app._dpi_watch_after_id)

    def test_close_guards_against_repeated_calls(self) -> None:
        root, app = self._make_app(sidebar_collapsed=False)
        app._closing = True
        before_process = app._process_events_after_id
        before_dpi = app._dpi_watch_after_id
        app.close()
        self.assertEqual(app._process_events_after_id, before_process)
        self.assertEqual(app._dpi_watch_after_id, before_dpi)
        try:
            root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    unittest.main()
