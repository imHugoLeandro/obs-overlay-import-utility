"""Lightweight DPI and color support for the portable Tk interface."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Literal


ThemeMode = Literal["light", "dark"]


@dataclass(frozen=True)
class Palette:
    """Semantic colors used by the ttk design system."""

    mode: ThemeMode
    background: str
    surface: str
    surface_alt: str
    foreground: str
    muted: str
    border: str
    field: str
    disabled: str
    accent: str
    accent_hover: str
    accent_pressed: str
    sidebar: str
    sidebar_hover: str
    sidebar_selected: str
    sidebar_foreground: str
    sidebar_muted: str
    console_background: str
    console_foreground: str
    selection: str


LIGHT_PALETTE = Palette(
    mode="light",
    background="#F3F5F7",
    surface="#FFFFFF",
    surface_alt="#E9EDF1",
    foreground="#171A1F",
    muted="#626A75",
    border="#D4DAE1",
    field="#FFFFFF",
    disabled="#E5E9EE",
    accent="#E1262F",
    accent_hover="#C91E27",
    accent_pressed="#A91820",
    sidebar="#15181D",
    sidebar_hover="#252A32",
    sidebar_selected="#343A45",
    sidebar_foreground="#F7F8FA",
    sidebar_muted="#A8B0BC",
    console_background="#111419",
    console_foreground="#E9EDF2",
    selection="#E1262F",
)

DARK_PALETTE = Palette(
    mode="dark",
    background="#101318",
    surface="#191D23",
    surface_alt="#222730",
    foreground="#F4F6F8",
    muted="#AAB2BE",
    border="#303640",
    field="#15191F",
    disabled="#2A3038",
    accent="#E1262F",
    accent_hover="#D9363E",
    accent_pressed="#B71F28",
    sidebar="#0A0C10",
    sidebar_hover="#1C2128",
    sidebar_selected="#2B313B",
    sidebar_foreground="#F7F8FA",
    sidebar_muted="#A8B0BC",
    console_background="#090B0E",
    console_foreground="#E9EDF2",
    selection="#F0444C",
)


def system_theme_mode() -> ThemeMode:
    """Return the Windows app theme, falling back to light elsewhere."""
    if os.name != "nt":
        return "light"
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if int(value) else "dark"
    except (OSError, TypeError, ValueError):
        return "light"


def palette_for(theme: str) -> Palette:
    """Resolve an application theme name to a concrete semantic palette."""
    mode = system_theme_mode() if theme == "system" else theme
    return DARK_PALETTE if mode == "dark" else LIGHT_PALETTE


def enable_high_dpi_awareness() -> bool:
    """Enable the best Windows DPI mode available before Tk is created."""
    if os.name != "nt":
        return False
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return True
    except (AttributeError, OSError):
        pass
    try:
        return ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0
    except (AttributeError, OSError):
        pass
    try:
        return bool(ctypes.windll.user32.SetProcessDPIAware())
    except (AttributeError, OSError):
        return False


def window_dpi(window_handle: int) -> int:
    """Return a top-level window's current DPI, or the 96-DPI baseline."""
    if os.name != "nt" or not window_handle:
        return 96
    try:
        dpi = int(ctypes.windll.user32.GetDpiForWindow(window_handle))
    except (AttributeError, OSError, TypeError, ValueError):
        return 96
    return dpi if dpi > 0 else 96
