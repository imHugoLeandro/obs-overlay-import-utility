"""Reusable themed-dialog framework for OBS Overlay Import Utility.

Provides a ``ThemedDialog`` base, spacing tokens, responsive wrap-length
calculation, dialog style configuration, and an open-dialog registry.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable

from .appearance import Palette


# ---------------------------------------------------------------------------
# Spacing scale  (base values at 100 % zoom / 96 DPI)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Space:
    XS: int = 4
    SM: int = 8
    MD: int = 12
    LG: int = 16
    XL: int = 20
    XXL: int = 24


def scaled_space(ui_zoom: float) -> Space:
    return Space(
        XS=max(2, round(4 * ui_zoom)),
        SM=max(4, round(8 * ui_zoom)),
        MD=max(6, round(12 * ui_zoom)),
        LG=max(8, round(16 * ui_zoom)),
        XL=max(12, round(20 * ui_zoom)),
        XXL=max(14, round(24 * ui_zoom)),
    )


# ---------------------------------------------------------------------------
# Dialog metrics
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DialogMetrics:
    width: int
    height: int
    minimum_width: int
    minimum_height: int
    outer_padding: int
    header_padding: int
    content_padding: int
    section_gap: int
    row_gap: int
    control_gap: int
    footer_padding_x: int
    footer_padding_y: int
    safe_right_gutter: int
    title_wraplength: int
    body_wraplength: int


def dialog_metrics(
    base_width: int = 900,
    base_height: int = 650,
    base_min_width: int = 680,
    base_min_height: int = 420,
    ui_zoom: float = 1.0,
    target_wraplength: int | None = None,
) -> DialogMetrics:
    space = scaled_space(ui_zoom)
    width = round(base_width * ui_zoom)
    body_wrap = target_wraplength or max(200, round(760 * ui_zoom))
    return DialogMetrics(
        width=width,
        height=round(base_height * ui_zoom),
        minimum_width=round(base_min_width * ui_zoom),
        minimum_height=round(base_min_height * ui_zoom),
        outer_padding=space.XXL,
        header_padding=space.XXL,
        content_padding=space.LG,
        section_gap=space.MD,
        row_gap=space.SM,
        control_gap=space.XS,
        footer_padding_x=space.LG,
        footer_padding_y=space.MD,
        safe_right_gutter=space.MD,
        title_wraplength=body_wrap,
        body_wraplength=body_wrap,
    )


@dataclass(frozen=True)
class ScrollbarMetrics:
    vertical_thickness: int
    horizontal_thickness: int
    arrow_size: int


def scrollbar_metrics(ui_zoom: float = 1.0) -> ScrollbarMetrics:
    return ScrollbarMetrics(
        vertical_thickness=max(20, round(28 * ui_zoom)),
        horizontal_thickness=max(12, round(18 * ui_zoom)),
        arrow_size=max(10, round(16 * ui_zoom)),
    )


@dataclass(frozen=True)
class UiScaleMetrics:
    widget_height: int
    trough_width: int
    slider_length: int
    highlight_thickness: int


def ui_scale_metrics(dimension_factor: float = 1.0) -> UiScaleMetrics:
    h = max(1, round(1 * dimension_factor))
    target = max(24, round(32 * dimension_factor))
    width = target - 2 * h
    return UiScaleMetrics(
        widget_height=target,
        trough_width=max(22, width),
        slider_length=max(24, round(30 * dimension_factor)),
        highlight_thickness=h,
    )


@dataclass(frozen=True)
class UiScaleColors:
    widget_background: str
    trough: str
    thumb: str
    thumb_active: str
    border: str
    focus_border: str


def ui_scale_colors(palette: Palette) -> UiScaleColors:
    return UiScaleColors(
        widget_background=palette.surface,
        trough=palette.surface_alt,
        thumb=palette.accent_hover,
        thumb_active=palette.selection,
        border=palette.border,
        focus_border=palette.selection,
    )


def compute_body_wraplength(
    dialog: tk.Toplevel | None = None,
    left_padding: int = 0,
    right_padding: int = 0,
    scrollbar_width: int | None = None,
    minimum_wrap: int = 200,
    ui_zoom: float = 1.0,
) -> int:
    if scrollbar_width is None:
        scrollbar_width = scrollbar_metrics(ui_zoom).vertical_thickness
    try:
        dw = dialog.winfo_width() if dialog else 800
    except tk.TclError:
        dw = 800
    return max(minimum_wrap, dw - left_padding - right_padding - scrollbar_width)


# ---------------------------------------------------------------------------
# Style names exported for other modules
# ---------------------------------------------------------------------------

DIALOG_STYLE_NAMES = [
    "Dialog.TFrame",
    "DialogHeader.TFrame",
    "DialogBody.TFrame",
    "DialogSurface.TFrame",
    "DialogFooter.TFrame",
    "DialogTitle.TLabel",
    "DialogSubtitle.TLabel",
    "DialogBody.TLabel",
    "DialogMuted.TLabel",
    "DialogSection.TLabel",
    "DialogWarning.TFrame",
    "DialogWarning.TLabel",
    "DialogError.TFrame",
    "DialogError.TLabel",
    "DialogPrimary.TButton",
    "DialogSecondary.TButton",
    "Dialog.TCombobox",
    "Dialog.Treeview",
    "Dialog.Treeview.Heading",
    "Dialog.TNotebook",
    "Dialog.TNotebook.Tab",
    "Dialog.Vertical.TScrollbar",
    "Dialog.Horizontal.TScrollbar",
]


def configure_dialog_styles(style: ttk.Style, palette: Palette, ui_zoom: float) -> None:
    base_font_size = round(10 * ui_zoom)
    title_font_size = max(14, round(16 * ui_zoom))
    small_font_size = round(9 * ui_zoom)

    style.configure("Dialog.TFrame", background=palette.background)
    style.configure("DialogHeader.TFrame", background=palette.background)
    style.configure("DialogBody.TFrame", background=palette.background)
    style.configure("DialogSurface.TFrame", background=palette.surface)
    style.configure("DialogFooter.TFrame", background=palette.surface_alt)

    style.configure(
        "DialogTitle.TLabel",
        background=palette.background,
        foreground=palette.foreground,
        font=("TkDefaultFont", title_font_size, "bold"),
    )
    style.configure(
        "DialogSubtitle.TLabel",
        background=palette.background,
        foreground=palette.muted,
        font=("TkDefaultFont", base_font_size),
    )
    style.configure(
        "DialogBody.TLabel",
        background=palette.background,
        foreground=palette.foreground,
        font=("TkDefaultFont", base_font_size),
    )
    style.configure(
        "DialogMuted.TLabel",
        background=palette.background,
        foreground=palette.muted,
        font=("TkDefaultFont", small_font_size),
    )
    style.configure(
        "DialogSection.TLabel",
        background=palette.background,
        foreground=palette.foreground,
        font=("TkDefaultFont", base_font_size, "bold"),
    )
    style.configure(
        "DialogWarning.TFrame",
        background=palette_aware_warning_bg(palette),
    )
    style.configure(
        "DialogWarning.TLabel",
        background=palette_aware_warning_bg(palette),
        foreground=palette_aware_warning_fg(palette),
        font=("TkDefaultFont", base_font_size),
    )
    style.configure(
        "DialogError.TFrame",
        background=palette.background,
    )
    style.configure(
        "DialogError.TLabel",
        background=palette.background,
        foreground=palette.accent,
        font=("TkDefaultFont", base_font_size),
    )
    style.configure(
        "DialogPrimary.TButton",
        background=palette.accent,
        foreground="#FFFFFF",
        font=("TkDefaultFont", base_font_size, "bold"),
    )
    style.map(
        "DialogPrimary.TButton",
        background=[
            ("pressed", palette.accent_pressed),
            ("active", palette.accent_hover),
            ("disabled", palette.disabled),
        ],
        foreground=[("disabled", palette.muted)],
    )
    style.configure(
        "DialogSecondary.TButton",
        background=palette.surface_alt,
        foreground=palette.foreground,
        font=("TkDefaultFont", base_font_size),
    )
    style.map(
        "DialogSecondary.TButton",
        background=[
            ("pressed", palette.disabled),
            ("active", palette.border),
            ("disabled", palette.disabled),
        ],
    )
    style.configure(
        "Dialog.TCombobox",
        fieldbackground=palette.field,
        background=palette.surface_alt,
        foreground=palette.foreground,
        arrowcolor=palette.muted,
        bordercolor=palette.border,
        focuscolor=palette.accent,
    )
    style.map(
        "Dialog.TCombobox",
        fieldbackground=[
            ("readonly", palette.field),
            ("disabled", palette.disabled),
        ],
        foreground=[("readonly", palette.foreground), ("disabled", palette.muted)],
        bordercolor=[("focus", palette.accent)],
        arrowcolor=[("active", palette.foreground)],
    )
    style.configure(
        "Dialog.Treeview",
        background=palette.field,
        fieldbackground=palette.field,
        foreground=palette.foreground,
        bordercolor=palette.border,
        font=("TkDefaultFont", base_font_size),
    )
    style.map(
        "Dialog.Treeview",
        background=[("selected", palette.selection)],
        foreground=[("selected", "#FFFFFF")],
    )
    style.configure(
        "Dialog.Treeview.Heading",
        background=palette.surface_alt,
        foreground=palette.foreground,
        font=("TkDefaultFont", base_font_size, "bold"),
        relief="flat",
    )
    style.configure(
        "Dialog.TNotebook",
        background=palette.background,
        bordercolor=palette.border,
    )
    style.configure(
        "Dialog.TNotebook.Tab",
        background=palette.surface_alt,
        foreground=palette.foreground,
        font=("TkDefaultFont", base_font_size),
    )
    style.map(
        "Dialog.TNotebook.Tab",
        background=[
            ("selected", palette.background),
            ("active", palette.surface),
        ],
    )
    sb = scrollbar_metrics(ui_zoom)
    style.configure(
        "Dialog.Vertical.TScrollbar",
        background=palette.surface_alt,
        troughcolor=palette.surface,
        arrowcolor=palette.muted,
        bordercolor=palette.surface,
        sliderthickness=sb.vertical_thickness,
        arrowsize=sb.arrow_size,
    )
    style.configure(
        "Dialog.Horizontal.TScrollbar",
        background=palette.surface_alt,
        troughcolor=palette.surface,
        arrowcolor=palette.muted,
        bordercolor=palette.surface,
        sliderthickness=sb.horizontal_thickness,
        arrowsize=sb.arrow_size,
    )


def palette_aware_warning_bg(palette: Palette) -> str:
    if palette.mode == "dark":
        return "#332B00"
    return "#FFF3CD"


def palette_aware_warning_fg(palette: Palette) -> str:
    if palette.mode == "dark":
        return "#FFD970"
    return "#856404"


# ---------------------------------------------------------------------------
# Open-dialog registry
# ---------------------------------------------------------------------------

_OPEN_DIALOGS: list[tk.Toplevel] = []


def register_open_dialog(dialog: tk.Toplevel) -> None:
    _OPEN_DIALOGS.append(dialog)


def unregister_open_dialog(dialog: tk.Toplevel) -> None:
    try:
        _OPEN_DIALOGS.remove(dialog)
    except ValueError:
        pass


def open_dialogs() -> list[tk.Toplevel]:
    _OPEN_DIALOGS[:] = [d for d in _OPEN_DIALOGS if d.winfo_exists()]
    return list(_OPEN_DIALOGS)


def refresh_all_open_dialogs(palette: Palette, ui_zoom: float) -> None:
    for dialog in open_dialogs():
        if hasattr(dialog, "_apply_theme"):
            try:
                dialog._apply_theme(palette, ui_zoom)  # type: ignore[operator]
            except Exception:
                pass


# ---------------------------------------------------------------------------
# ThemedDialog – base for all custom secondary windows
# ---------------------------------------------------------------------------

class ThemedDialog:
    """Reusable themed ``tk.Toplevel`` wrapper.

    Usage::

        dlg = ThemedDialog(parent, "Title", palette, ui_zoom=1.0)
        dlg.header("Dialog Title", "Optional subtitle")
        # build body in dlg.body
        dlg.footer_buttons([("Cancel", dlg.cancel, False), ("OK", on_ok, True)])
        dlg.show()
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel,
        title: str,
        palette: Palette,
        *,
        ui_zoom: float = 1.0,
        width: int = 900,
        height: int = 650,
        min_width: int = 680,
        min_height: int = 420,
        modal: bool = True,
        icon_path: str | None = None,
    ) -> None:
        self._parent = parent
        self._palette = palette
        self._ui_zoom = ui_zoom
        self._modal = modal
        self._completed = False

        self.metrics = dialog_metrics(
            base_width=width,
            base_height=height,
            base_min_width=min_width,
            base_min_height=min_height,
            ui_zoom=ui_zoom,
        )

        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.transient(parent)
        self.dialog.configure(background=palette.background)
        self.dialog.minsize(self.metrics.minimum_width, self.metrics.minimum_height)
        self.dialog.geometry(f"{self.metrics.width}x{self.metrics.height}")

        self._center_and_clamp()

        if icon_path and icon_path.endswith(".ico"):
            try:
                self.dialog.iconbitmap(icon_path)
            except Exception:
                pass

        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.bind("<Escape>", lambda _e: self.close())

        self._on_close_callback: Callable[[], None] | None = None

        # Main grid structure
        self.dialog.columnconfigure(0, weight=1)

        self._header_frame: ttk.Frame | None = None
        self._body_frame: ttk.Frame | None = None
        self._footer_frame: ttk.Frame | None = None

        register_open_dialog(self.dialog)

    def _center_and_clamp(self) -> None:
        try:
            self.dialog.update_idletasks()
            pw = self._parent.winfo_width()
            ph = self._parent.winfo_height()
            px = self._parent.winfo_rootx()
            py = self._parent.winfo_rooty()
            dw = self.dialog.winfo_width()
            dh = self.dialog.winfo_height()
            x = px + (pw - dw) // 2
            y = py + (ph - dh) // 2
            x = max(0, x)
            y = max(0, y)

            sw = self.dialog.winfo_screenwidth()
            sh = self.dialog.winfo_screenheight()
            if dw > sw:
                dw = sw - 40
            if dh > sh:
                dh = sh - 40
            x = max(0, min(x, sw - dw))
            y = max(0, min(y, sh - dh))

            self.dialog.geometry(f"{dw}x{dh}+{x}+{y}")
        except Exception:
            pass

    # -- region builders --

    def header(self, title_text: str, subtitle: str = "") -> ttk.Frame:
        frame = ttk.Frame(self.dialog, style="DialogHeader.TFrame")
        frame.grid(row=0, column=0, sticky="ew")
        p = self.metrics.header_padding
        frame.configure(padding=(p, p, p, self.metrics.section_gap))
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text=title_text,
            style="DialogTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")

        if subtitle:
            ttk.Label(
                frame,
                text=subtitle,
                style="DialogSubtitle.TLabel",
                wraplength=self.metrics.title_wraplength,
            ).grid(row=1, column=0, sticky="w", pady=(self.metrics.control_gap, 0))

        self._header_frame = frame
        return frame

    @property
    def body(self) -> ttk.Frame:
        if self._body_frame is None:
            self._body_frame = ttk.Frame(
                self.dialog,
                style="DialogBody.TFrame",
                padding=(self.metrics.content_padding, self.metrics.section_gap,
                         self.metrics.content_padding, self.metrics.section_gap),
            )
            self._body_frame.grid(row=1, column=0, sticky="nsew")
            self._body_frame.columnconfigure(0, weight=1)
            self.dialog.rowconfigure(1, weight=1)
        return self._body_frame

    @property
    def footer(self) -> ttk.Frame:
        if self._footer_frame is None:
            self._footer_frame = ttk.Frame(self.dialog, style="DialogFooter.TFrame")
            self._footer_frame.grid(row=2, column=0, sticky="ew")
            px = self.metrics.footer_padding_x
            py = self.metrics.footer_padding_y
            self._footer_frame.configure(padding=(px, py, px, py))
            self._footer_frame.columnconfigure(0, weight=1)
        return self._footer_frame

    def footer_buttons(
        self,
        buttons: list[tuple[str, Callable[[], None], bool]],
    ) -> None:
        footer = self.footer
        col = len(buttons) + 1
        for idx, (label, command, primary) in enumerate(buttons):
            btn_col = col - len(buttons) + idx
            style = "DialogPrimary.TButton" if primary else "DialogSecondary.TButton"
            btn = ttk.Button(footer, text=label, command=command, style=style)
            btn.grid(row=0, column=btn_col, padx=(self.metrics.control_gap, 0))

    # -- show / close --

    def show(self) -> None:
        if self._modal:
            self.dialog.grab_set()
        self.dialog.focus_set()

    def close(self) -> None:
        if self._completed:
            return
        self._completed = True
        try:
            self.dialog.grab_release()
        except tk.TclError:
            pass
        if self._on_close_callback:
            try:
                self._on_close_callback()
            except Exception:
                pass
        unregister_open_dialog(self.dialog)
        try:
            self.dialog.destroy()
        except tk.TclError:
            pass

    def cancel(self) -> None:
        self.close()

    def set_on_close(self, callback: Callable[[], None]) -> None:
        self._on_close_callback = callback

    # -- theme refresh --

    def _apply_theme(self, palette: Palette, ui_zoom: float) -> None:
        self._palette = palette
        self._ui_zoom = ui_zoom
        self.metrics = dialog_metrics(
            base_width=self.metrics.width,
            base_height=self.metrics.height,
            base_min_width=self.metrics.minimum_width,
            base_min_height=self.metrics.minimum_height,
            ui_zoom=ui_zoom,
        )
        try:
            if self.dialog.winfo_exists():
                self.dialog.configure(background=palette.background)
                self._center_and_clamp()
        except tk.TclError:
            pass
