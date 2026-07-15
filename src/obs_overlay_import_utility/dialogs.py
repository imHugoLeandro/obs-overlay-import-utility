"""Reusable dialog creation helpers for themed Tk secondary windows."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable

from .appearance import Palette


# ---------------------------------------------------------------------------
# Spacing scale
# ---------------------------------------------------------------------------

def spacing_scale(ui_zoom: float) -> dict[str, int]:
    return {
        "XS": max(2, round(4 * ui_zoom)),
        "SM": max(4, round(8 * ui_zoom)),
        "MD": max(6, round(12 * ui_zoom)),
        "LG": max(8, round(16 * ui_zoom)),
        "XL": max(12, round(24 * ui_zoom)),
    }


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
    section_gap: int
    control_gap: int
    footer_padding: int
    wrap_length: int


def dialog_metrics(
    base_width: int = 900,
    base_height: int = 650,
    base_min_width: int = 680,
    base_min_height: int = 420,
    ui_zoom: float = 1.0,
) -> DialogMetrics:
    space = spacing_scale(ui_zoom)
    return DialogMetrics(
        width=round(base_width * ui_zoom),
        height=round(base_height * ui_zoom),
        minimum_width=round(base_min_width * ui_zoom),
        minimum_height=round(base_min_height * ui_zoom),
        outer_padding=space["SM"],
        section_gap=space["XS"],
        control_gap=max(3, round(5 * ui_zoom)),
        footer_padding=space["SM"],
        wrap_length=max(200, round(760 * ui_zoom)),
    )


# ---------------------------------------------------------------------------
# Dialog theme styles
# ---------------------------------------------------------------------------

DIALOG_STYLE_NAMES = [
    "Dialog.TFrame",
    "DialogSurface.TFrame",
    "DialogHeader.TFrame",
    "DialogFooter.TFrame",
    "DialogTitle.TLabel",
    "DialogSubtitle.TLabel",
    "DialogMuted.TLabel",
    "DialogWarning.TFrame",
    "DialogWarning.TLabel",
    "DialogError.TLabel",
    "DialogSection.TLabel",
    "DialogPrimary.TButton",
]


def configure_dialog_styles(style: ttk.Style, palette: Palette, ui_zoom: float) -> None:
    base_font_size = round(10 * ui_zoom)
    title_font_size = round(12 * ui_zoom)
    small_font_size = round(9 * ui_zoom)

    style.configure("Dialog.TFrame", background=palette.background)
    style.configure("DialogSurface.TFrame", background=palette.surface)
    style.configure("DialogHeader.TFrame", background=palette.background)
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
        "DialogMuted.TLabel",
        background=palette.background,
        foreground=palette.muted,
        font=("TkDefaultFont", small_font_size),
    )
    style.configure(
        "DialogWarning.TFrame",
        background="#FFF3CD",
    )
    style.configure(
        "DialogWarning.TLabel",
        background="#FFF3CD",
        foreground="#856404",
        font=("TkDefaultFont", base_font_size),
    )
    style.configure(
        "DialogError.TLabel",
        background=palette.background,
        foreground=palette.accent,
        font=("TkDefaultFont", base_font_size),
    )
    style.configure(
        "DialogSection.TLabel",
        background=palette.background,
        foreground=palette.foreground,
        font=("TkDefaultFont", base_font_size, "bold"),
    )
    style.configure(
        "DialogPrimary.TButton",
        background=palette.accent,
        foreground="#FFFFFF",
        font=("TkDefaultFont", base_font_size),
    )


# ---------------------------------------------------------------------------
# Shared dialog creation
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


def create_dialog(
    parent: tk.Tk | tk.Toplevel,
    title: str,
    palette: Palette,
    *,
    icon_path: str | None = None,
    ui_zoom: float = 1.0,
    theme_callback: Callable[[Palette, float], None] | None = None,
) -> tk.Toplevel:
    metrics = dialog_metrics(ui_zoom=ui_zoom)

    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.configure(background=palette.background)
    dialog.minsize(metrics.minimum_width, metrics.minimum_height)

    dialog.geometry(f"{metrics.width}x{metrics.height}")

    try:
        _center_over_parent(dialog, parent)
    except Exception:
        pass

    try:
        _clamp_to_monitor(dialog)
    except Exception:
        pass

    if icon_path and icon_path.endswith(".ico"):
        try:
            dialog.iconbitmap(icon_path)
        except Exception:
            pass

    register_open_dialog(dialog)

    def _on_destroy() -> None:
        unregister_open_dialog(dialog)

    dialog.protocol("WM_DELETE_WINDOW", _default_close_handler(dialog))

    def _original_destroy() -> None:
        _on_destroy()
        if hasattr(tk.Toplevel, "destroy"):
            tk.Toplevel.destroy(dialog)

    dialog._real_destroy = _original_destroy  # type: ignore[attr-defined]

    dialog.bind("<Escape>", lambda _event: _default_close_handler(dialog)())

    return dialog


def _center_over_parent(dialog: tk.Toplevel, parent: tk.Tk | tk.Toplevel) -> None:
    dialog.update_idletasks()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    dw = dialog.winfo_width()
    dh = dialog.winfo_height()
    x = px + (pw - dw) // 2
    y = py + (ph - dh) // 2
    dialog.geometry(f"+{max(0, x)}+{max(0, y)}")


def _clamp_to_monitor(dialog: tk.Toplevel) -> None:
    dialog.update_idletasks()
    screen_width = dialog.winfo_screenwidth()
    screen_height = dialog.winfo_screenheight()
    dw = dialog.winfo_width()
    dh = dialog.winfo_height()
    x = dialog.winfo_x()
    y = dialog.winfo_y()
    if dw > screen_width:
        dw = screen_width - 40
    if dh > screen_height:
        dh = screen_height - 40
    x = max(0, min(x, screen_width - dw))
    y = max(0, min(y, screen_height - dh))
    dialog.geometry(f"{dw}x{dh}+{x}+{y}")


def _default_close_handler(dialog: tk.Toplevel) -> Callable[[], None]:
    def _handler() -> None:
        try:
            dialog.grab_release()
        except tk.TclError:
            pass
        try:
            dialog.destroy()
        except tk.TclError:
            pass

    return _handler


def safe_dialog_close(dialog: tk.Toplevel, on_close: Callable[[], None] | None = None) -> None:
    try:
        dialog.grab_release()
    except tk.TclError:
        pass
    if on_close:
        try:
            on_close()
        except Exception:
            pass
    try:
        dialog.destroy()
    except tk.TclError:
        pass


def refresh_dialog_theme(
    dialog: tk.Toplevel, palette: Palette, ui_zoom: float
) -> None:
    try:
        if not dialog.winfo_exists():
            return
        dialog.configure(background=palette.background)
        _clamp_to_monitor(dialog)
    except tk.TclError:
        pass
