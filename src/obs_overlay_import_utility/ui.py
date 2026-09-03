"""Tkinter interface for customers importing OBS overlay packages."""

from __future__ import annotations

import math
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk


from .appearance import (
    Palette,
    enable_high_dpi_awareness,
    palette_for,
    window_dpi,
)
from .constants import APP_TITLE, TOOL_LOG_HEIGHT, TOOL_LOG_HEADING, __version__
from .core import (
    convert_collection,
    find_scene_collections,
    install_scene_collection,
    load_json,
)
from .device_setup import auto_apply_device_choices
from .exporter import (
    ExportResult,
    ExportInventory,
    active_obs_scene_collection,
    list_obs_scene_collections,
)
from . import dialogs as dlgs
from .obs_live import (
    ObsAuthenticationRequired,
    ObsLiveError,
    ObsWebSocketClient,
    is_obs_running,
)
from .live_resize import (
    LiveResizeOutcome,
    LiveResizeSnapshot,
    resize_active_collection,
    undo_live_resize,
)
from .models import ConversionResult, UtilityError
from .obs_profile import active_profile_canvas
from .resizer import (
    MODE_SCALE_RATIO,
    MODE_STRETCH,
    SCOPE_COLLECTION,
    SCOPE_SCENE,
    SCOPE_SOURCE,
    ResizeResult,
    resize_collection,
    scene_names,
    source_choices,
    undo_resize,
)
from .streamlabs import (
    StreamlabsImportResult,
    default_obs_scenes_directory,
    extract_zip_archive,
    import_streamlabs_overlay,
)
from .settings import (
    MAX_UI_SCALE,
    MIN_UI_SCALE,
    AppSettings,
    SettingsStore,
    detect_default_obs_path,
)


THEME_LABELS = {
    "Windows default": "system",
    "White": "light",
    "Dark": "dark",
}
THEME_NAMES = {value: label for label, value in THEME_LABELS.items()}

_ICON_SIZES = (32, 40, 48, 64)

COLLAPSED_SIDEBAR_BASE_WIDTH = 127  # wide enough for the collapsed logo at 130% of icon size (91px) + 2×18 padding
COLLAPSED_LOGO_BASE_WIDTH = 60
COLLAPSED_ICON_BASE_SIZE = 29
COLLAPSED_ARROW_BASE_SIZE = 13
SIDEBAR_HORIZONTAL_PADDING = 18


@dataclass(frozen=True)
class SidebarMetrics:
    collapsed_width: int
    icon_size: int
    logo_width: int
    arrow_font_size: int
    horizontal_padding: int


def compute_sidebar_metrics(dpi: int, zoom_percent: float) -> SidebarMetrics:
    dpi_scale = max(1.0, dpi / 96.0)
    zoom_scale = max(0.75, min(1.5, zoom_percent / 100.0))
    scale = dpi_scale * zoom_scale

    collapsed_width = round(COLLAPSED_SIDEBAR_BASE_WIDTH * scale)
    logo_width = round(COLLAPSED_LOGO_BASE_WIDTH * scale)
    icon_size = max(22, round(COLLAPSED_ICON_BASE_SIZE * scale))
    arrow_font_size = max(9, round(COLLAPSED_ARROW_BASE_SIZE * scale))
    horizontal_padding = round(SIDEBAR_HORIZONTAL_PADDING * scale)

    return SidebarMetrics(
        collapsed_width=collapsed_width,
        icon_size=icon_size,
        logo_width=logo_width,
        arrow_font_size=arrow_font_size,
        horizontal_padding=horizontal_padding,
    )


def subsample_ratio(source_width: int, target_width: int) -> int:
    """Ceiling division so the subsampled image never exceeds *target_width*."""
    return max(1, math.ceil(source_width / target_width))


def _pick_icon_size(desired: int) -> int:
    """Return the nearest available pre-rendered icon size >= *desired*."""
    for sz in _ICON_SIZES:
        if sz >= desired:
            return sz
    return _ICON_SIZES[-1]


def _nav_icon_path(assets_dir: Path, kind: str, size: int, red: bool) -> Path:
    colour = "red" if red else "white"
    return assets_dir / f"icon-{kind}-{colour}-{size}.png"


class _NavIcons:
    """Loads and caches pre-rendered icon PNGs at the needed size."""

    def __init__(self, assets_dir: Path, base_size: int = 29) -> None:
        self._assets = assets_dir
        self._base = base_size
        self._images: dict[tuple[str, bool], tk.PhotoImage] = {}

    def load(self, kind: str, red: bool, scale: float = 1.0) -> tk.PhotoImage:
        size = _pick_icon_size(max(16, round(self._base * scale)))
        key = (kind, red)
        if key in self._images:
            existing = self._images[key]
            if existing.width() == size:
                return existing
        path = _nav_icon_path(self._assets, kind, size, red)
        if not path.is_file():
            raise FileNotFoundError(f"Icon asset missing: {path}")
        img = tk.PhotoImage(file=str(path))
        self._images[key] = img
        return img

    def clear(self) -> None:
        self._images.clear()


def bundled_asset(name: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "obs_overlay_import_utility" / "assets" / name
    return Path(__file__).resolve().parent / "assets" / name


def format_file_size(size: int) -> str:
    """Format a byte count for compact inventory display."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _is_zip_path(path: Path) -> bool:
    return path.is_file() and path.suffix.casefold() == ".zip"


class ImportUtilityApp:
    SECTIONS = (
        ("import", "Import Overlay"),
        ("export", "Export Overlay"),
        ("resizer", "Auto Resizer"),
        ("settings", "Settings"),
    )

    @property
    def ui_zoom(self) -> float:
        return max(0.75, min(1.5, self.ui_scale_var.get() / 100.0))

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_TITLE} {__version__}")
        self.root.update_idletasks()
        self.current_dpi = window_dpi(self.root.winfo_id())
        self.root.tk.call("tk", "scaling", self.current_dpi / 72.0)
        self._set_initial_window_size()
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self.detected_obs_path = detect_default_obs_path()

        initial_folder = (
            self.settings.last_overlay_folder
            if self.settings.remember_last_folder
            and Path(self.settings.last_overlay_folder).is_dir()
            else ""
        )
        self.folder_var = tk.StringVar(value=initial_folder)
        self.collection_var = tk.StringVar()
        self.import_method_var = tk.StringVar(value="obs")
        self.pending_obs_conversion = False
        self.scale_to_canvas_var = tk.BooleanVar(value=True)
        self.streamlabs_file_var = tk.StringVar()
        self.export_collection_var = tk.StringVar()
        self.export_destination_var = tk.StringVar()
        self.export_compress_var = tk.BooleanVar(value=True)
        self.export_status_var = tk.StringVar(
            value="Choose a scene collection and destination folder."
        )
        self.resize_collection_var = tk.StringVar()
        self.resize_scope_var = tk.StringVar(value=SCOPE_COLLECTION)
        self.resize_name_var = tk.StringVar()
        self.resize_mode_var = tk.StringVar(value=MODE_STRETCH)
        self.resize_size_mode_var = tk.StringVar(value="screen")
        self.resize_width_var = tk.StringVar(value="1920")
        self.resize_height_var = tk.StringVar(value="1080")
        self.resize_screen_size_var = tk.StringVar(
            value="Screen size: checking OBS profile…"
        )
        self.resize_status_var = tk.StringVar(
            value="Choose what to resize and a target size."
        )
        self.section_var = tk.StringVar(value="import")
        self.theme_var = tk.StringVar(
            value=THEME_NAMES.get(self.settings.theme, "Windows default")
        )
        self.ui_scale_var = tk.DoubleVar(value=self.settings.ui_scale)
        self.ui_scale_label_var = tk.StringVar(value=f"{self.settings.ui_scale}%")
        self.use_custom_python_var = tk.BooleanVar(
            value=self.settings.use_custom_python
        )
        self.python_path_var = tk.StringVar(value=self.settings.python_path)
        self.use_custom_obs_var = tk.BooleanVar(value=self.settings.use_custom_obs)
        self.obs_path_var = tk.StringVar(value=self.settings.obs_path)
        self.remember_folder_var = tk.BooleanVar(
            value=self.settings.remember_last_folder
        )
        self.open_output_var = tk.BooleanVar(
            value=self.settings.open_output_after_conversion
        )
        self.tool_logs_var = tk.BooleanVar(value=self.settings.show_tool_logs)
        self.settings_status_var = tk.StringVar(
            value=self.settings_store.last_error
            or "Settings are saved for this Windows user."
        )
        self.status_var = tk.StringVar(
            value="Choose the extracted overlay folder to begin."
        )
        self.collections: dict[str, Path] = {}
        self.export_collections: dict[str, Path] = {}
        self.export_controls: list[tk.Widget] = []
        self.resize_collections: dict[str, Path] = {}
        self.resize_source_choices: dict[str, str] = {}
        self.resizer_controls: list[tk.Widget] = []
        self.last_resize_collection: Path | None = None
        self.last_resize_backup: Path | None = None
        self.last_output: Path | None = None
        self.last_live_resize_snapshot: LiveResizeSnapshot | None = None
        self.obs_websocket_password: str | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.navigation_buttons: list[tk.Label] = []
        self.logo_source: tk.PhotoImage | None = None
        self.logo_image: tk.PhotoImage | None = None
        self.logo_label: ttk.Label | None = None
        self.font_family = self._preferred_font_family()
        self.mono_font_family = self._preferred_mono_font_family()
        self.fonts = self._create_fonts()
        self.current_palette: Palette = palette_for(self.settings.theme)
        self.scaled_widget_paddings: list[tuple[tk.Widget, tuple[int, ...]]] = []

        self._apply_theme()
        self._build_interface()
        self._capture_scalable_ui()
        self._apply_ui_scale(self.settings.ui_scale)
        self._apply_theme()
        self._update_custom_path_states()
        self._set_sidebar_collapsed(self.settings.sidebar_collapsed, persist=False)
        self._process_events_after_id: str | None = None
        self._dpi_watch_after_id: str | None = None
        self._process_events_after_id = self.root.after(100, self._process_events)
        self._dpi_watch_after_id = self.root.after(750, self._watch_window_dpi)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def shutdown(self) -> None:
        for attribute in ("_process_events_after_id", "_dpi_watch_after_id"):
            callback_id = getattr(self, attribute, None)
            if callback_id is None:
                continue
            try:
                self.root.after_cancel(callback_id)
            except tk.TclError:
                pass
            setattr(self, attribute, None)

    def close(self) -> None:
        if getattr(self, "_closing", False):
            return
        self._closing = True
        self.shutdown()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _set_initial_window_size(self) -> None:
        dpi_factor = max(1.0, self.current_dpi / 96.0)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(round(1040 * dpi_factor), round(screen_width * 0.92))
        height = min(round(720 * dpi_factor), round(screen_height * 0.9))
        minimum_width = min(round(860 * dpi_factor), width)
        minimum_height = min(round(600 * dpi_factor), height)
        self.root.minsize(minimum_width, minimum_height)
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _preferred_font_family(self) -> str:
        available = {family.casefold(): family for family in tkfont.families(self.root)}
        for candidate in ("Segoe UI Variable", "Segoe UI", "Arial"):
            if candidate.casefold() in available:
                return available[candidate.casefold()]
        return "TkDefaultFont"

    def _preferred_mono_font_family(self) -> str:
        available = {family.casefold(): family for family in tkfont.families(self.root)}
        for candidate in ("Cascadia Mono", "Cascadia Code", "Consolas", "Courier New"):
            if candidate.casefold() in available:
                return available[candidate.casefold()]
        return "TkFixedFont"

    def _create_fonts(self) -> dict[str, tkfont.Font]:
        return {
            "body": tkfont.Font(
                root=self.root, family=self.font_family, size=10, name="AppBodyFont"
            ),
            "body_bold": tkfont.Font(
                root=self.root,
                family=self.font_family,
                size=10,
                weight="bold",
                name="AppBodyBoldFont",
            ),
            "title": tkfont.Font(
                root=self.root,
                family=self.font_family,
                size=22,
                weight="bold",
                name="AppTitleFont",
            ),
            "section": tkfont.Font(
                root=self.root,
                family=self.font_family,
                size=11,
                weight="bold",
                name="AppSectionFont",
            ),
            "small": tkfont.Font(
                root=self.root, family=self.font_family, size=9, name="AppSmallFont"
            ),
            "mono": tkfont.Font(
                root=self.root,
                family=self.mono_font_family,
                size=9,
                name="AppMonoFont",
            ),
            "arrow": tkfont.Font(
                root=self.root,
                family=self.font_family,
                size=20,
                name="AppArrowFont",
            ),
        }

    def _watch_window_dpi(self) -> None:
        try:
            dpi = window_dpi(self.root.winfo_id())
            if dpi != self.current_dpi:
                self.current_dpi = dpi
                self.root.tk.call("tk", "scaling", dpi / 72.0)
                self._apply_ui_scale(self.ui_scale_var.get())
        except tk.TclError:
            return
        self._dpi_watch_after_id = self.root.after(750, self._watch_window_dpi)

    def _compute_sidebar_metrics(self) -> SidebarMetrics:
        return compute_sidebar_metrics(
            dpi=getattr(self, "current_dpi", 96),
            zoom_percent=self.ui_scale_var.get(),
        )

    def _refresh_sidebar_layout(self) -> None:
        m = self._compute_sidebar_metrics()
        if getattr(self, "sidebar_collapsed", False):
            self._collapsed_sidebar_width = m.collapsed_width
            self.root.columnconfigure(
                0, weight=0, minsize=m.collapsed_width
            )
            self._apply_collapsed_layout(m)
        self._update_nav_styles()

    def _build_interface(self) -> None:
        nav_font = self.fonts["body_bold"]
        text_widths = [nav_font.measure(label) for _, label in self.SECTIONS]
        max_text_width = max(text_widths) if text_widths else 0
        self._min_sidebar_width = max(max_text_width + 56, 160)
        initial_width = max(
            self._min_sidebar_width,
            round(214 * max(1.0, self.current_dpi / 96.0)),
        )
        self._max_sidebar_width = round(self.root.winfo_screenwidth() * 0.35)
        self._sidebar_dragging = False

        self.root.columnconfigure(0, weight=0, minsize=initial_width)
        self.root.columnconfigure(1, weight=0)
        self.root.columnconfigure(2, weight=1)
        self.root.rowconfigure(0, weight=1)

        navigation = ttk.Frame(
            self.root,
            padding=(18, 22),
            style="Sidebar.TFrame",
        )
        self.navigation_frame = navigation
        navigation.grid(row=0, column=0, sticky="nsew")
        navigation.columnconfigure(0, weight=1)
        navigation.rowconfigure(len(self.SECTIONS) + 1, weight=1)

        self.sidebar_handle = tk.Frame(
            self.root,
            width=5,
            cursor="sb_h_double_arrow",
            bg=self.current_palette.border,
        )
        self.sidebar_handle.grid(row=0, column=1, sticky="ns")
        self.sidebar_handle.bind("<Button-1>", self._start_sidebar_drag)
        self.sidebar_handle.bind("<B1-Motion>", self._sidebar_drag)
        self.root.bind("<ButtonRelease-1>", self._stop_sidebar_drag)

        logo_path = bundled_asset("social-space-logo.png")
        try:
            self.logo_source = tk.PhotoImage(file=logo_path)
            self.logo_label = ttk.Label(navigation, style="Sidebar.TLabel")
            self.logo_label.grid(row=0, column=0, sticky="w", pady=(0, 18))
        except tk.TclError:
            self.logo_label = None
        self.sidebar_caption_label = ttk.Label(
            navigation,
            text="OVERLAY TOOLS",
            style="SidebarCaption.TLabel",
        )
        self.sidebar_caption_label.grid(row=1, column=0, sticky="w", pady=(0, 8))

        self._nav_icon_kinds = {
            "import": "folder-arrow-left",
            "export": "folder-arrow-right",
            "resizer": "fit-to-screen",
            "settings": "cog",
        }
        self._nav_icons = _NavIcons(bundled_asset("."), base_size=COLLAPSED_ICON_BASE_SIZE)
        for row0, (section, label) in enumerate(self.SECTIONS, start=2):
            # Settings is pinned to the row directly above the sidebar bottom bar.
            row = len(self.SECTIONS) + 2 if section == "settings" else row0
            button = tk.Label(
                navigation,
                text=label,
                compound="left",
                anchor="w",
                padx=14,
                pady=10,
                cursor="hand2",
                font=self.fonts["body_bold"],
            )
            button.grid(row=row, column=0, sticky="ew", pady=(0, 6))
            # Selected-item accent: 3px red bar overlaying the left edge
            accent = tk.Frame(navigation, width=3, height=1, bg=self.current_palette.sidebar)
            accent.grid(row=row, column=0, sticky="wns", pady=(0, 6))
            button._nav_accent = accent  # type: ignore[attr-defined]
            button.bind(
                "<Button-1>", lambda _e, s=section: self._select_section(s)
            )
            button.bind(
                "<Enter>", lambda _e, s=section: self._hover_nav(s, True)
            )
            button.bind(
                "<Leave>", lambda _e, s=section: self._hover_nav(s, False)
            )
            self.navigation_buttons.append(button)

        self.sidebar_collapsed = False
        self._collapsed_sidebar_width = self._compute_sidebar_metrics().collapsed_width
        self._last_expanded_sidebar_width = 0

        sidebar_bottom = ttk.Frame(navigation, style="Sidebar.TFrame")
        sidebar_bottom.grid(row=len(self.SECTIONS) + 3, column=0, sticky="ew")
        sidebar_bottom.columnconfigure(0, weight=1)

        self.sidebar_version_label = ttk.Label(
            sidebar_bottom,
            text=f"v{__version__}",
            style="SidebarMuted.TLabel",
        )
        self.sidebar_version_label.grid(row=0, column=0, sticky="w")

        expanded_arrow_size = max(8, round(12 * max(1.0, self.current_dpi / 96.0)))
        self.sidebar_collapse_arrow = tk.Label(
            sidebar_bottom,
            text="◀",
            font=(self.font_family, expanded_arrow_size),
            bg=self.current_palette.sidebar,
            fg=self.current_palette.sidebar_muted,
            cursor="hand2",
        )
        self.sidebar_collapse_arrow.grid(row=0, column=1, sticky="e")
        self.sidebar_collapse_arrow.bind(
            "<Button-1>", lambda e: self._toggle_sidebar()
        )

        # Content area: a canvas + scrollbar so pages never resize the window.
        # Pages stretch to the canvas width; overflow scrolls vertically.
        self.page_canvas = tk.Canvas(
            self.root,
            bg=self.current_palette.background,
            highlightthickness=0,
            borderwidth=0,
        )
        self.page_canvas.grid(row=0, column=2, sticky="nsew")
        self.page_scrollbar = ttk.Scrollbar(
            self.root, orient="vertical", command=self.page_canvas.yview
        )
        self.page_canvas.configure(yscrollcommand=self.page_scrollbar.set)
        self.page_container = ttk.Frame(self.page_canvas, style="Page.TFrame")
        self._page_window_id = self.page_canvas.create_window(
            (0, 0), window=self.page_container, anchor="nw"
        )
        self.page_container.columnconfigure(0, weight=1)
        self.page_container.rowconfigure(0, weight=1)
        self.page_canvas.bind("<Configure>", self._on_page_canvas_configure)
        self.page_container.bind("<Configure>", self._on_page_container_configure)
        self.root.bind("<MouseWheel>", self._on_page_mousewheel, add="+")

        frame = ttk.Frame(self.page_container, padding=26, style="Page.TFrame")
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(6, weight=1)
        self.import_page = frame

        ttk.Label(frame, text="Import Overlay", style="PageTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            frame,
            text="Select one import option, expand it with the arrow, then run it from this page.",
            wraplength=760,
            style="PageSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        methods = ttk.Frame(frame, padding=1)
        methods.grid(row=2, column=0, sticky="ew")
        methods.columnconfigure(0, weight=1)
        self.method_controls: list[tk.Widget] = []
        self.method_options: dict[str, ttk.Frame] = {}
        self.method_arrows: dict[str, ttk.Button] = {}
        self.method_accents: dict[str, tk.Frame] = {}
        self.method_labels: dict[str, ttk.Label] = {}
        self.method_expanded = {"obs": True, "streamlabs": False}

        obs_card = ttk.LabelFrame(
            methods,
            text="Import OBS Scene Collection File",
            padding=14,
            style="Card.TLabelframe",
        )
        obs_card.grid(row=0, column=0, sticky="ew")
        obs_card.columnconfigure(0, weight=1)
        obs_header = tk.Frame(obs_card, bg=self.current_palette.surface, cursor="hand2")
        obs_header.grid(row=0, column=0, sticky="ew")
        obs_header.columnconfigure(1, weight=1)
        self.obs_accent = tk.Frame(obs_header, width=4, bg=self.current_palette.border)
        self.obs_accent.grid(row=0, column=0, sticky="ns")
        self.method_accents["obs"] = self.obs_accent
        self.obs_label = ttk.Label(
            obs_header,
            text="Repair an exported OBS scene collection and its local asset paths",
            wraplength=600,
            style="MethodSelector.TLabel",
        )
        self.obs_label.grid(row=0, column=1, sticky="w", padx=(10, 8), pady=14)
        self.method_labels["obs"] = self.obs_label
        self.obs_arrow = ttk.Button(
            obs_header,
            text="▾",
            width=3,
            command=lambda: self._toggle_import_method("obs"),
            style="Arrow.TButton",
        )
        self.obs_arrow.grid(row=0, column=2, sticky="e")
        self.method_arrows["obs"] = self.obs_arrow
        self.method_controls.append(self.obs_arrow)
        obs_header.bind("<Button-1>", lambda e: self._select_import_method("obs"))
        self.obs_label.bind("<Button-1>", lambda e: self._select_import_method("obs"))
        obs_options = ttk.Frame(obs_card)
        obs_options.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        obs_options.columnconfigure(0, weight=1)
        self.method_options["obs"] = obs_options
        ttk.Label(obs_options, text="Overlay Folder path").grid(
            row=0, column=0, sticky="w"
        )
        obs_folder_row = ttk.Frame(obs_options)
        obs_folder_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        obs_folder_row.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(obs_folder_row, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.browse_button = ttk.Button(
            obs_folder_row, text="Browse…", command=self._browse
        )
        self.browse_button.grid(row=0, column=1)
        self.method_controls.extend((self.folder_entry, self.browse_button))
        ttk.Label(
            obs_options,
            text="The scene collection export is found automatically inside this folder, or inside a ZIP archive if one is selected.",
            style="Muted.TLabel",
            wraplength=700,
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.scale_to_canvas_check = ttk.Checkbutton(
            obs_options,
            text="Scale layout to my OBS canvas after import (aspect-preserving)",
            variable=self.scale_to_canvas_var,
        )
        self.scale_to_canvas_check.grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.method_controls.append(self.scale_to_canvas_check)

        streamlabs_card = ttk.LabelFrame(
            methods,
            text="Import Streamlabs Scene File",
            padding=14,
            style="Card.TLabelframe",
        )
        streamlabs_card.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        streamlabs_card.columnconfigure(0, weight=1)
        streamlabs_header = tk.Frame(streamlabs_card, bg=self.current_palette.surface, cursor="hand2")
        streamlabs_header.grid(row=0, column=0, sticky="ew")
        streamlabs_header.columnconfigure(1, weight=1)
        self.streamlabs_accent = tk.Frame(streamlabs_header, width=4, bg=self.current_palette.border)
        self.streamlabs_accent.grid(row=0, column=0, sticky="ns")
        self.method_accents["streamlabs"] = self.streamlabs_accent
        self.streamlabs_label = ttk.Label(
            streamlabs_header,
            text="Extract, convert, and import a Streamlabs package into OBS",
            wraplength=600,
            style="MethodSelector.TLabel",
        )
        self.streamlabs_label.grid(row=0, column=1, sticky="w", padx=(10, 8), pady=14)
        self.method_labels["streamlabs"] = self.streamlabs_label
        self.streamlabs_arrow = ttk.Button(
            streamlabs_header,
            text="▸",
            width=3,
            command=lambda: self._toggle_import_method("streamlabs"),
            style="Arrow.TButton",
        )
        self.streamlabs_arrow.grid(row=0, column=2, sticky="e")
        self.method_arrows["streamlabs"] = self.streamlabs_arrow
        self.method_controls.append(self.streamlabs_arrow)
        streamlabs_header.bind("<Button-1>", lambda e: self._select_import_method("streamlabs"))
        self.streamlabs_label.bind("<Button-1>", lambda e: self._select_import_method("streamlabs"))
        streamlabs_options = ttk.Frame(streamlabs_card)
        streamlabs_options.columnconfigure(0, weight=1)
        self.method_options["streamlabs"] = streamlabs_options
        streamlabs_options.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(streamlabs_options, text="Streamlabs .overlay file").grid(
            row=0, column=0, sticky="w"
        )
        streamlabs_file_row = ttk.Frame(streamlabs_options)
        streamlabs_file_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        streamlabs_file_row.columnconfigure(0, weight=1)
        self.streamlabs_file_entry = ttk.Entry(
            streamlabs_file_row, textvariable=self.streamlabs_file_var
        )
        self.streamlabs_file_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.streamlabs_browse_button = ttk.Button(
            streamlabs_file_row, text="Browse…", command=self._browse_streamlabs
        )
        self.streamlabs_browse_button.grid(row=0, column=1)
        self.method_controls.extend(
            (self.streamlabs_file_entry, self.streamlabs_browse_button)
        )
        ttk.Label(
            streamlabs_options,
            text="Files are extracted beside the selected package and a new OBS collection is created automatically.",
            style="Muted.TLabel",
            wraplength=700,
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.streamlabs_scale_check = ttk.Checkbutton(
            streamlabs_options,
            text="Scale layout to my OBS canvas after import (aspect-preserving)",
            variable=self.scale_to_canvas_var,
        )
        self.streamlabs_scale_check.grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        self.method_controls.append(self.streamlabs_scale_check)

        run_row = ttk.Frame(frame)
        run_row.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        run_row.columnconfigure(0, weight=1)
        self.selected_method_label = ttk.Label(
            run_row,
            text="Selected: Import OBS Scene Collection File",
            style="PageMuted.TLabel",
        )
        self.selected_method_label.grid(row=0, column=0, sticky="w")
        self.run_button = ttk.Button(
            run_row,
            text="Run Import",
            command=self._run_selected_method,
            width=18,
            style="Primary.TButton",
        )
        self.run_button.grid(row=0, column=1, sticky="e")

        ttk.Separator(frame).grid(row=4, column=0, sticky="ew", pady=14)
        self.results_label = ttk.Label(
            frame, text=TOOL_LOG_HEADING, style="PageSection.TLabel"
        )
        self.results_label.grid(row=5, column=0, sticky="w")
        self.results = tk.Text(
            frame,
            height=TOOL_LOG_HEIGHT,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        self.results.grid(row=6, column=0, sticky="nsew", pady=(8, 0))
        self.results_scrollbar = ttk.Scrollbar(
            frame, orient="vertical", command=self.results.yview
        )
        self.results_scrollbar.grid(row=6, column=1, sticky="ns", pady=(8, 0))
        self.results.configure(yscrollcommand=self.results_scrollbar.set)
        ttk.Label(
            frame,
            text="The original export is never modified. An existing OBS collection is never overwritten.",
            style="PageMuted.TLabel",
        ).grid(row=7, column=0, sticky="w", pady=(10, 0))
        self._update_import_method_panels()
        self._build_export_page()

        self._build_resizer_page()
        self._build_settings_page()

        self._show_section()

    def _build_export_page(self) -> None:
        page = ttk.Frame(self.page_container, padding=26, style="Page.TFrame")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(6, weight=1)
        self.export_page = page

        ttk.Label(page, text="Export Overlay", style="PageTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            page,
            text="Package an OBS scene collection with its local media, plugin resources, and filter files.",
            wraplength=760,
            style="PageSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        options = ttk.LabelFrame(
            page, text="Export options", padding=16, style="Card.TLabelframe"
        )
        options.grid(row=2, column=0, sticky="ew")
        options.columnconfigure(0, weight=1)
        ttk.Label(options, text="OBS Scene Collection").grid(
            row=0, column=0, sticky="w"
        )
        collection_row = ttk.Frame(options)
        collection_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        collection_row.columnconfigure(0, weight=1)
        self.export_collection_combo = ttk.Combobox(
            collection_row,
            textvariable=self.export_collection_var,
            state="readonly",
        )
        self.export_collection_combo.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.refresh_export_button = ttk.Button(
            collection_row, text="Refresh", command=self._refresh_export_collections
        )
        self.refresh_export_button.grid(row=0, column=1)
        self.export_controls.extend(
            (self.export_collection_combo, self.refresh_export_button)
        )
        ttk.Label(
            options,
            text="The collection currently selected in OBS is chosen automatically when available.",
            style="Muted.TLabel",
            wraplength=700,
        ).grid(row=2, column=0, sticky="w", pady=(4, 12))

        ttk.Label(options, text="Export destination folder").grid(
            row=3, column=0, sticky="w"
        )
        destination_row = ttk.Frame(options)
        destination_row.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        destination_row.columnconfigure(0, weight=1)
        self.export_destination_entry = ttk.Entry(
            destination_row, textvariable=self.export_destination_var
        )
        self.export_destination_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.export_destination_browse_button = ttk.Button(
            destination_row, text="Browse…", command=self._browse_export_destination
        )
        self.export_destination_browse_button.grid(row=0, column=1)
        self.export_controls.extend(
            (self.export_destination_entry, self.export_destination_browse_button)
        )
        ttk.Label(
            options,
            text="A new organized package folder is created here, with images, videos, audio, other resources, and an OBS JSON export.",
            style="Muted.TLabel",
            wraplength=700,
        ).grid(row=5, column=0, sticky="w", pady=(4, 0))

        compress_frame = ttk.Frame(options)
        compress_frame.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        self.export_compress_check = ttk.Checkbutton(
            compress_frame,
            text="Compress exported package to ZIP",
            variable=self.export_compress_var,
        )
        self.export_compress_check.grid(row=0, column=0, sticky="w")
        self.export_controls.append(self.export_compress_check)

        run_row = ttk.Frame(page)
        run_row.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        run_row.columnconfigure(0, weight=1)
        ttk.Label(
            run_row, textvariable=self.export_status_var, style="PageMuted.TLabel"
        ).grid(row=0, column=0, sticky="w")
        self.export_run_button = ttk.Button(
            run_row,
            text="Run Export",
            command=self._export_overlay,
            width=18,
            style="Primary.TButton",
        )
        self.export_run_button.grid(row=0, column=1, sticky="e")
        self.export_controls.append(self.export_run_button)

        ttk.Separator(page).grid(row=4, column=0, sticky="ew", pady=14)
        self.export_log_label = ttk.Label(
            page, text=TOOL_LOG_HEADING, style="PageSection.TLabel"
        )
        self.export_log_label.grid(row=5, column=0, sticky="w")
        self.export_results = tk.Text(
            page,
            height=TOOL_LOG_HEIGHT,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        self.export_results.grid(row=6, column=0, sticky="nsew", pady=(8, 0))
        self.export_results_scrollbar = ttk.Scrollbar(
            page, orient="vertical", command=self.export_results.yview
        )
        self.export_results_scrollbar.grid(row=6, column=1, sticky="ns", pady=(8, 0))
        self.export_results.configure(yscrollcommand=self.export_results_scrollbar.set)
        self._refresh_export_collections()

    def _build_resizer_page(self) -> None:
        page = ttk.Frame(self.page_container, padding=26, style="Page.TFrame")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(6, weight=1)
        self.resizer_page = page

        ttk.Label(page, text="Auto Resizer", style="PageTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            page,
            text="Resize an entire collection, one scene, or one source. The selected OBS collection is overwritten with an undo backup.",
            wraplength=760,
            style="PageSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        options = ttk.LabelFrame(
            page, text="Resize options", padding=16, style="Card.TLabelframe"
        )
        options.grid(row=2, column=0, sticky="ew")
        options.columnconfigure(0, weight=1)
        options.columnconfigure(1, weight=1)

        ttk.Label(options, text="OBS Scene Collection").grid(
            row=0, column=0, sticky="w"
        )
        collection_row = ttk.Frame(options)
        collection_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 10))
        collection_row.columnconfigure(0, weight=1)
        self.resize_collection_combo = ttk.Combobox(
            collection_row, textvariable=self.resize_collection_var, state="readonly"
        )
        self.resize_collection_combo.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.resize_collection_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._refresh_resize_targets()
        )
        self.refresh_resize_button = ttk.Button(
            collection_row, text="Refresh", command=self._refresh_resize_collections
        )
        self.refresh_resize_button.grid(row=0, column=1)
        self.resizer_controls.extend(
            (self.resize_collection_combo, self.refresh_resize_button)
        )

        ttk.Label(options, text="Resize").grid(row=2, column=0, sticky="w")
        self.resize_scope_combo = ttk.Combobox(
            options,
            textvariable=self.resize_scope_var,
            values=(SCOPE_COLLECTION, SCOPE_SCENE, SCOPE_SOURCE),
            state="readonly",
        )
        self.resize_scope_combo.grid(
            row=3, column=0, sticky="ew", padx=(0, 8), pady=(4, 10)
        )
        self.resize_scope_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._refresh_resize_targets()
        )
        self.resizer_controls.append(self.resize_scope_combo)

        ttk.Label(options, text="Selected scene or source").grid(
            row=2, column=1, sticky="w"
        )
        self.resize_name_combo = ttk.Combobox(
            options, textvariable=self.resize_name_var, state="disabled"
        )
        self.resize_name_combo.grid(row=3, column=1, sticky="ew", pady=(4, 10))
        self.resizer_controls.append(self.resize_name_combo)

        ttk.Label(options, text="Resize behavior").grid(row=4, column=0, sticky="w")
        behavior_row = ttk.Frame(options)
        behavior_row.grid(row=5, column=0, sticky="w", pady=(4, 10))
        self.stretch_radio = ttk.Radiobutton(
            behavior_row,
            text="Stretch",
            value=MODE_STRETCH,
            variable=self.resize_mode_var,
        )
        self.stretch_radio.grid(row=0, column=0, sticky="w")
        self.scale_ratio_radio = ttk.Radiobutton(
            behavior_row,
            text="Scale Ratio",
            value=MODE_SCALE_RATIO,
            variable=self.resize_mode_var,
        )
        self.scale_ratio_radio.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.resizer_controls.extend((self.stretch_radio, self.scale_ratio_radio))

        ttk.Label(options, text="Target size").grid(row=4, column=1, sticky="w")
        size_row = ttk.Frame(options)
        size_row.grid(row=5, column=1, sticky="ew", pady=(4, 10))
        self.screen_size_radio = ttk.Radiobutton(
            size_row,
            text="Screen size",
            value="screen",
            variable=self.resize_size_mode_var,
            command=self._update_resize_size_mode,
        )
        self.screen_size_radio.grid(row=0, column=0, sticky="w")
        self.custom_size_radio = ttk.Radiobutton(
            size_row,
            text="Custom size",
            value="custom",
            variable=self.resize_size_mode_var,
            command=self._update_resize_size_mode,
        )
        self.custom_size_radio.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.resizer_controls.extend((self.screen_size_radio, self.custom_size_radio))

        ttk.Label(
            options,
            textvariable=self.resize_screen_size_var,
            style="Muted.TLabel",
            wraplength=330,
        ).grid(row=6, column=0, sticky="w")
        custom_row = ttk.Frame(options)
        custom_row.grid(row=6, column=1, sticky="ew")
        ttk.Label(custom_row, text="W").grid(row=0, column=0, padx=(0, 4))
        self.resize_width_entry = ttk.Entry(
            custom_row, textvariable=self.resize_width_var, width=8
        )
        self.resize_width_entry.grid(row=0, column=1, padx=(0, 8))
        ttk.Label(custom_row, text="H").grid(row=0, column=2, padx=(0, 4))
        self.resize_height_entry = ttk.Entry(
            custom_row, textvariable=self.resize_height_var, width=8
        )
        self.resize_height_entry.grid(row=0, column=3)
        self.resizer_controls.extend(
            (self.resize_width_entry, self.resize_height_entry)
        )
        ttk.Label(
            options,
            text="Collection scope changes the canvas. Scene and Source scopes change only the selected layout and preserve the current canvas. Scale Ratio preserves aspect ratio and centers the resized layout.",
            style="Muted.TLabel",
            wraplength=700,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        run_row = ttk.Frame(page)
        run_row.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        run_row.columnconfigure(0, weight=1)
        ttk.Label(
            run_row, textvariable=self.resize_status_var, style="PageMuted.TLabel"
        ).grid(row=0, column=0, sticky="w")
        self.undo_resize_button = ttk.Button(
            run_row, text="Undo", command=self._undo_resize, width=12, state="disabled"
        )
        self.undo_resize_button.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.resize_run_button = ttk.Button(
            run_row,
            text="Run Resize",
            command=self._run_resize,
            width=18,
            style="Primary.TButton",
        )
        self.resize_run_button.grid(row=0, column=2, sticky="e")
        self.resizer_controls.extend((self.undo_resize_button, self.resize_run_button))

        ttk.Separator(page).grid(row=4, column=0, sticky="ew", pady=14)
        self.resize_log_label = ttk.Label(
            page, text=TOOL_LOG_HEADING, style="PageSection.TLabel"
        )
        self.resize_log_label.grid(row=5, column=0, sticky="w")
        self.resize_results = tk.Text(
            page,
            height=TOOL_LOG_HEIGHT,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        self.resize_results.grid(row=6, column=0, sticky="nsew", pady=(8, 0))
        self.resize_results_scrollbar = ttk.Scrollbar(
            page, orient="vertical", command=self.resize_results.yview
        )
        self.resize_results_scrollbar.grid(row=6, column=1, sticky="ns", pady=(8, 0))
        self.resize_results.configure(yscrollcommand=self.resize_results_scrollbar.set)
        self._refresh_resize_collections()
        self._update_resize_size_mode()

    def _build_settings_page(self) -> None:
        page = ttk.Frame(self.page_container, padding=26, style="Page.TFrame")
        page.columnconfigure(0, weight=1)
        self.settings_page = page

        ttk.Label(page, text="Settings", style="PageTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            page,
            text="Customize how the portable utility looks and finds local applications.",
            style="PageMuted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        appearance = ttk.LabelFrame(
            page, text="Appearance", padding=16, style="Card.TLabelframe"
        )
        appearance.grid(row=2, column=0, sticky="ew")
        appearance.columnconfigure(1, weight=1)
        ttk.Label(appearance, text="Theme").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        self.theme_combo = ttk.Combobox(
            appearance,
            textvariable=self.theme_var,
            values=list(THEME_LABELS),
            state="readonly",
            width=22,
        )
        self.theme_combo.grid(row=0, column=1, sticky="w")
        self.theme_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._apply_theme()
        )

        ttk.Label(appearance, text="UI size").grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=(12, 0)
        )
        scale_row = ttk.Frame(appearance)
        scale_row.grid(row=1, column=1, sticky="ew", pady=(12, 0))
        scale_row.columnconfigure(0, weight=1)
        sm = dlgs.ui_scale_metrics(self.ui_zoom * max(1.0, self.current_dpi / 96.0))
        self.ui_scale = tk.Scale(
            scale_row,
            from_=MIN_UI_SCALE,
            to=MAX_UI_SCALE,
            orient="horizontal",
            variable=self.ui_scale_var,
            command=self._on_scale_drag,
            showvalue=False,
            resolution=1,
            takefocus=True,
            borderwidth=0,
            highlightthickness=sm.highlight_thickness,
            relief="flat",
            sliderrelief="flat",
            width=sm.trough_width,
            sliderlength=sm.slider_length,
        )
        self.ui_scale.grid(row=0, column=0, sticky="ew")
        self._ui_scale_hovered = False
        self._ui_scale_focused = False
        self._ui_scale_pressed = False
        self._bind_ui_scale_interactions()
        self._apply_ui_scale_widget_theme()
        ttk.Label(scale_row, textvariable=self.ui_scale_label_var, width=6).grid(
            row=0, column=1, padx=(10, 0)
        )
        ttk.Button(
            scale_row,
            text="Windows size (100%)",
            command=lambda: self._set_scale(100),
        ).grid(row=0, column=2, padx=(6, 0))

        paths = ttk.LabelFrame(
            page, text="Application paths", padding=16, style="Card.TLabelframe"
        )
        paths.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        paths.columnconfigure(0, weight=1)

        self.custom_python_check = ttk.Checkbutton(
            paths,
            text="Use a custom Python executable",
            variable=self.use_custom_python_var,
            command=self._update_custom_path_states,
        )
        self.custom_python_check.grid(row=0, column=0, sticky="w")
        ttk.Label(
            paths,
            text="The portable app already includes Python. Enable this only for a future tool that requires another installation.",
            style="Muted.TLabel",
            wraplength=690,
        ).grid(row=1, column=0, sticky="w", pady=(3, 6))
        python_row = ttk.Frame(paths)
        python_row.grid(row=2, column=0, sticky="ew")
        python_row.columnconfigure(0, weight=1)
        self.python_path_entry = ttk.Entry(
            python_row, textvariable=self.python_path_var
        )
        self.python_path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.python_browse_button = ttk.Button(
            python_row, text="Browse…", command=self._browse_python
        )
        self.python_browse_button.grid(row=0, column=1)

        self.custom_obs_check = ttk.Checkbutton(
            paths,
            text="OBS is installed in a custom location",
            variable=self.use_custom_obs_var,
            command=self._update_custom_path_states,
        )
        self.custom_obs_check.grid(row=3, column=0, sticky="w", pady=(14, 0))
        detected_text = (
            f"Automatically detected: {self.detected_obs_path}"
            if self.detected_obs_path
            else "OBS was not found in the standard Windows locations. Import Overlay does not require OBS to be open."
        )
        ttk.Label(
            paths,
            text=detected_text,
            style="Muted.TLabel",
            wraplength=690,
        ).grid(row=4, column=0, sticky="w", pady=(3, 6))
        obs_row = ttk.Frame(paths)
        obs_row.grid(row=5, column=0, sticky="ew")
        obs_row.columnconfigure(0, weight=1)
        self.obs_path_entry = ttk.Entry(obs_row, textvariable=self.obs_path_var)
        self.obs_path_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.obs_browse_button = ttk.Button(
            obs_row, text="Browse…", command=self._browse_obs
        )
        self.obs_browse_button.grid(row=0, column=1)

        behavior = ttk.LabelFrame(
            page, text="Import behavior", padding=16, style="Card.TLabelframe"
        )
        behavior.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Checkbutton(
            behavior,
            text="Remember the last overlay folder",
            variable=self.remember_folder_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            behavior,
            text="Open the output folder after a successful conversion",
            variable=self.open_output_var,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))

        program = ttk.LabelFrame(
            page, text="Program settings", padding=16, style="Card.TLabelframe"
        )
        program.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        ttk.Checkbutton(
            program,
            text="Show tool logs",
            variable=self.tool_logs_var,
            command=self._apply_tool_logs,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            program,
            text=(
                "Show the black log consoles on the Import, Export, and Resize pages. "
                "Turn this off for a cleaner look; results still appear in the status text."
            ),
            style="Muted.TLabel",
            wraplength=690,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        actions = ttk.Frame(page)
        actions.grid(row=6, column=0, sticky="ew", pady=(14, 0))
        ttk.Button(
            actions,
            text="Save settings",
            command=self._save_settings,
            style="Primary.TButton",
        ).grid(row=0, column=0)
        ttk.Button(
            actions, text="Restore defaults", command=self._restore_defaults
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(
            actions, textvariable=self.settings_status_var, style="PageMuted.TLabel"
        ).grid(row=0, column=2, sticky="w", padx=(14, 0))
        self._apply_tool_logs()

    def _select_section(self, section: str) -> None:
        self.section_var.set(section)
        self._show_section()
        self._update_nav_styles()

    def _show_section(self) -> None:
        section = self.section_var.get()
        self.import_page.grid_remove()
        self.export_page.grid_remove()
        self.resizer_page.grid_remove()
        self.settings_page.grid_remove()
        if section == "import":
            self.import_page.grid(row=0, column=0, sticky="nsew")
            return
        if section == "export":
            self._refresh_export_collections()
            self.export_page.grid(row=0, column=0, sticky="nsew")
            return
        if section == "resizer":
            self._refresh_resize_collections()
            self.resizer_page.grid(row=0, column=0, sticky="nsew")
            return
        if section == "settings":
            self.settings_page.grid(row=0, column=0, sticky="nsew")
            return

    def _on_page_canvas_configure(self, event: tk.Event) -> None:
        self.page_canvas.itemconfigure(self._page_window_id, width=event.width)
        self._update_page_scrollregion()

    def _on_page_container_configure(self, _event: tk.Event) -> None:
        self._update_page_scrollregion()

    def _update_page_scrollregion(self) -> None:
        self.page_canvas.configure(scrollregion=self.page_canvas.bbox("all"))
        bounds = self.page_canvas.bbox("all")
        needs_scroll = (
            bounds is not None
            and bounds[3] > self.page_canvas.winfo_height() + 8
        )
        if needs_scroll and not self.page_scrollbar.winfo_ismapped():
            self.page_scrollbar.grid(row=0, column=3, sticky="ns")
        elif not needs_scroll and self.page_scrollbar.winfo_ismapped():
            self.page_scrollbar.grid_remove()

    def _on_page_mousewheel(self, event: tk.Event) -> str | None:
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None and widget is not self.root:
            if widget is self.page_canvas or widget is self.page_container:
                self.page_canvas.yview_scroll(-(event.delta // 120), "units")
                return "break"
            widget = widget.master
        return None

    def _start_sidebar_drag(self, event: tk.Event) -> None:
        self._sidebar_dragging = True

    def _sidebar_drag(self, event: tk.Event) -> None:
        if not self._sidebar_dragging or self.sidebar_collapsed:
            return
        new_width = event.x_root - self.root.winfo_rootx()
        new_width = max(self._min_sidebar_width, min(new_width, self._max_sidebar_width))
        self.root.columnconfigure(0, weight=0, minsize=new_width)

    def _stop_sidebar_drag(self, _event: tk.Event | None = None) -> None:
        if not self._sidebar_dragging:
            return
        self._sidebar_dragging = False
        if not self.sidebar_collapsed:
            self._last_expanded_sidebar_width = (
                self.root.grid_bbox(0, 0)[2]
            )

    def _set_sidebar_collapsed(
        self, collapsed: bool, *, persist: bool
    ) -> None:
        if self.sidebar_collapsed == collapsed:
            return
        if collapsed:
            self._collapse_sidebar()
        else:
            self._expand_sidebar()
        if persist:
            self._persist_sidebar_state()

    def _persist_sidebar_state(self) -> bool:
        from dataclasses import replace
        updated = replace(self.settings, sidebar_collapsed=self.sidebar_collapsed)
        try:
            self.settings_store.save(updated)
        except OSError:
            self.settings_status_var.set("Could not save sidebar state.")
            return False
        self.settings = updated
        return True

    def _toggle_sidebar(self) -> None:
        self._set_sidebar_collapsed(
            not self.sidebar_collapsed, persist=True
        )

    def _apply_collapsed_layout(self, m: SidebarMetrics | None = None) -> None:
        if m is None:
            m = self._compute_sidebar_metrics()
        scale = (
            max(1.0, getattr(self, "current_dpi", 96) / 96.0)
            * max(0.75, min(1.5, self.ui_scale_var.get() / 100.0))
        )
        for section, button in zip(
            (s for s, _ in self.SECTIONS), self.navigation_buttons
        ):
            kind = self._nav_icon_kinds.get(section, "")
            if not kind:
                button.configure(
                    text=section[:1], font=self.fonts["body_bold"],
                    compound="center", anchor="center", padx=0, pady=8,
                )
                continue
            try:
                is_selected = section == self.section_var.get()
                icon = self._nav_icons.load(kind, red=is_selected, scale=scale)
                button.configure(
                    image=icon, text="", compound="center",
                    anchor="center", padx=0, pady=8,
                )
                button._current_icon = icon
            except (FileNotFoundError, tk.TclError, OSError):
                button.configure(
                    text="?", font=self.fonts["body_bold"],
                    compound="center", anchor="center", padx=0, pady=8,
                )
        self.sidebar_collapse_arrow.configure(
            font=(self.font_family, m.arrow_font_size)
        )
        if self.logo_label:
            self.logo_label.grid_configure(sticky="")
        if self.logo_source:
            # Collapsed logo is 130% of icon height (always bigger than the
            # nav icons), capped to the bar's content width so the
            # auto-centered layout never overflows (key rule).
            aspect = self.logo_source.width() / self.logo_source.height()
            content_w = m.collapsed_width - 2 * m.horizontal_padding
            self._update_logo_to_width(
                min(round(m.icon_size * aspect * 1.3), content_w)
            )

    def _collapse_sidebar(self) -> None:
        self.root.update_idletasks()
        self._last_expanded_sidebar_width = self.root.grid_bbox(0, 0)[2]
        self.sidebar_collapsed = True
        m = self._compute_sidebar_metrics()
        self._collapsed_sidebar_width = m.collapsed_width
        self.root.columnconfigure(0, weight=0, minsize=m.collapsed_width)
        self.sidebar_version_label.grid_remove()
        self.sidebar_caption_label.grid_remove()
        self.sidebar_collapse_arrow.configure(text="\u25b6")
        self.sidebar_handle.configure(cursor="arrow")
        self.sidebar_collapse_arrow.grid_configure(column=0, sticky="")
        self.sidebar_collapse_arrow.master.columnconfigure(0, weight=1, uniform="")
        self.sidebar_collapse_arrow.master.columnconfigure(
            1, weight=0, minsize=0
        )
        self._apply_collapsed_layout(m)
        self._update_nav_styles()

    def _expand_sidebar(self) -> None:
        self.sidebar_collapsed = False
        restored = max(
            self._min_sidebar_width,
            getattr(self, "_last_expanded_sidebar_width", 0),
        )
        self.root.columnconfigure(0, weight=0, minsize=restored)
        self.sidebar_version_label.grid()
        self.sidebar_caption_label.grid()
        self.sidebar_collapse_arrow.configure(text="\u25c0")
        self.sidebar_handle.configure(cursor="sb_h_double_arrow")
        self.sidebar_collapse_arrow.grid_configure(column=1, sticky="e")
        self.sidebar_collapse_arrow.master.columnconfigure(0, weight=1, uniform="")
        self.sidebar_collapse_arrow.master.columnconfigure(
            1,             weight=0, minsize=0
        )
        self.sidebar_collapse_arrow.configure(
            font=(self.font_family, max(9, round(12 * (
                max(1.0, getattr(self, "current_dpi", 96) / 96.0)
                * max(0.75, min(1.5, self.ui_scale_var.get() / 100.0))
            ))))
        )
        if self.logo_label:
            self.logo_label.grid_configure(sticky="w")
            scale = (
                max(1.0, getattr(self, "current_dpi", 96) / 96.0)
                * max(0.75, min(1.5, self.ui_scale_var.get() / 100.0))
            )
            self._update_logo_scale(scale)  # restore the expanded-size logo
        for (section, label), button in zip(self.SECTIONS, self.navigation_buttons):
            button.configure(
                image="", text=label, font=self.fonts["body_bold"],
                compound="left", anchor="w", padx=14, pady=10,
            )
        self._nav_icons.clear()
        self._update_nav_styles()
        self._apply_ui_scale(self.ui_scale_var.get())

    def _update_nav_styles(self) -> None:
        """Apply selection/hover background colors to nav labels."""
        palette = self.current_palette
        selected = self.section_var.get()
        is_collapsed = getattr(self, "sidebar_collapsed", False)
        scale = (
            max(1.0, getattr(self, "current_dpi", 96) / 96.0)
            * max(0.75, min(1.5, self.ui_scale_var.get() / 100.0))
        )
        for section, btn in zip((s for s, _ in self.SECTIONS), self.navigation_buttons):
            is_selected = section == selected
            hovering = getattr(btn, "_is_hovering", False) and not is_selected
            bg = (
                palette.sidebar_hover
                if hovering
                else (palette.sidebar_selected if is_selected else palette.sidebar)
            )
            btn.configure(bg=bg, fg=palette.sidebar_foreground)
            accent = getattr(btn, "_nav_accent", None)
            if accent is not None:
                accent.configure(bg=palette.accent if is_selected else bg)
            if is_collapsed:
                kind = self._nav_icon_kinds.get(section, "")
                if kind:
                    try:
                        icon = self._nav_icons.load(
                            kind, red=is_selected, scale=scale
                        )
                        btn.configure(image=icon)
                        btn._current_icon = icon
                    except (FileNotFoundError, tk.TclError, OSError):
                        pass

    def _hover_nav(self, section: str, entering: bool) -> None:
        for s, btn in zip((s for s, _ in self.SECTIONS), self.navigation_buttons):
            if s == section:
                btn._is_hovering = entering  # type: ignore[attr-defined]
        self._update_nav_styles()

    def _update_logo_to_width(self, target_w: int) -> None:
        if not self.logo_source or not self.logo_label:
            return
        src_w = self.logo_source.width()
        target_w = min(src_w, max(36, target_w))
        if target_w >= src_w:
            self.logo_image = self.logo_source
        else:
            ratio = subsample_ratio(src_w, target_w)
            self.logo_image = self.logo_source.subsample(ratio, ratio)
        self.logo_label.configure(image=self.logo_image)

    def _apply_theme(self) -> None:
        theme = THEME_LABELS.get(self.theme_var.get(), "system")
        palette = palette_for(theme)
        self.current_palette = palette
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            ".",
            background=palette.surface,
            foreground=palette.foreground,
            font=self.fonts["body"],
        )
        style.configure("TFrame", background=palette.surface)
        style.configure("Page.TFrame", background=palette.background)
        style.configure("Sidebar.TFrame", background=palette.sidebar)
        style.configure(
            "TLabel", background=palette.surface, foreground=palette.foreground
        )
        style.configure(
            "PageTitle.TLabel",
            background=palette.background,
            foreground=palette.foreground,
            font=self.fonts["title"],
        )
        style.configure(
            "PageSubtitle.TLabel",
            background=palette.background,
            foreground=palette.muted,
        )
        style.configure(
            "PageSection.TLabel",
            background=palette.background,
            foreground=palette.foreground,
            font=self.fonts["section"],
        )
        style.configure(
            "Muted.TLabel", background=palette.surface, foreground=palette.muted
        )
        style.configure(
            "PageMuted.TLabel",
            background=palette.background,
            foreground=palette.muted,
        )
        style.configure(
            "MethodSelector.TLabel",
            background=palette.surface,
            foreground=palette.foreground,
            font=self.fonts["body_bold"],
        )
        style.configure(
            "Sidebar.TLabel",
            background=palette.sidebar,
            foreground=palette.sidebar_foreground,
        )
        style.configure(
            "SidebarCaption.TLabel",
            background=palette.sidebar,
            foreground=palette.sidebar_muted,
            font=self.fonts["body_bold"],
        )
        style.configure(
            "SidebarMuted.TLabel",
            background=palette.sidebar,
            foreground=palette.sidebar_muted,
            font=self.fonts["small"],
        )
        style.configure(
            "TSeparator", background=palette.border, bordercolor=palette.border
        )
        style.configure(
            "Card.TLabelframe",
            background=palette.surface,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=palette.surface,
            foreground=palette.foreground,
            font=self.fonts["section"],
        )
        style.configure(
            "TButton",
            background=palette.surface_alt,
            foreground=palette.foreground,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            focuscolor=palette.accent,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[
                ("pressed", palette.disabled),
                ("active", palette.border),
                ("disabled", palette.disabled),
            ],
            foreground=[("disabled", palette.muted)],
            bordercolor=[("focus", palette.accent)],
        )
        style.configure(
            "Primary.TButton",
            background=palette.accent,
            foreground="#FFFFFF",
            bordercolor=palette.accent,
            lightcolor=palette.accent,
            darkcolor=palette.accent,
            font=self.fonts["body_bold"],
        )
        style.map(
            "Primary.TButton",
            background=[
                ("pressed", palette.accent_pressed),
                ("active", palette.accent_hover),
                ("disabled", palette.disabled),
            ],
            foreground=[("disabled", palette.muted)],
            bordercolor=[
                ("pressed", palette.accent_pressed),
                ("active", palette.accent_hover),
            ],
        )
        style.configure(
            "Icon.TButton",
            background=palette.surface,
            foreground=palette.muted,
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Icon.TButton",
            background=[
                ("pressed", palette.surface_alt),
                ("active", palette.surface_alt),
            ],
            foreground=[("active", palette.foreground)],
        )
        style.configure(
            "Arrow.TButton",
            background=palette.surface,
            foreground=palette.muted,
            borderwidth=0,
            relief="flat",
            font=self.fonts["arrow"],
        )
        style.map(
            "Arrow.TButton",
            background=[
                ("pressed", palette.surface_alt),
                ("active", palette.surface_alt),
            ],
            foreground=[("active", palette.foreground)],
        )
        style.configure(
            "TCheckbutton",
            background=palette.surface,
            foreground=palette.foreground,
            indicatorcolor=palette.field,
            indicatormargin=(2, 2, 3, 1),
            bordercolor=palette.border,
            focuscolor=palette.accent,
        )
        style.map(
            "TCheckbutton",
            background=[("active", palette.surface)],
            indicatorcolor=[
                ("selected", palette.accent),
                ("active", palette.accent_hover),
                ("disabled", palette.disabled),
            ],
            foreground=[("disabled", palette.muted)],
        )
        style.configure(
            "TRadiobutton",
            background=palette.surface,
            foreground=palette.foreground,
            indicatorcolor=palette.border,
            indicatormargin=(2, 2, 3, 1),
            bordercolor=palette.border,
            focuscolor=palette.accent,
        )
        style.map(
            "TRadiobutton",
            background=[("active", palette.surface)],
            indicatorcolor=[
                ("selected", palette.accent),
                ("active !selected", palette.foreground),
                ("disabled", palette.disabled),
            ],
            foreground=[("disabled", palette.muted)],
        )
        style.configure(
            "TEntry",
            fieldbackground=palette.field,
            foreground=palette.foreground,
            insertcolor=palette.foreground,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            focuscolor=palette.accent,
        )
        style.map(
            "TEntry",
            fieldbackground=[("disabled", palette.disabled)],
            foreground=[("disabled", palette.muted)],
            bordercolor=[("focus", palette.accent)],
        )
        style.configure(
            "TCombobox",
            fieldbackground=palette.field,
            background=palette.surface_alt,
            foreground=palette.foreground,
            arrowcolor=palette.muted,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            focuscolor=palette.accent,
        )
        style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", palette.field),
                ("disabled", palette.disabled),
            ],
            foreground=[("readonly", palette.foreground), ("disabled", palette.muted)],
            bordercolor=[("focus", palette.accent)],
            arrowcolor=[("active", palette.foreground)],
        )
        style.configure(
            "Horizontal.TScale",
            background=palette.accent,
            troughcolor=palette.surface_alt,
            bordercolor=palette.border,
            lightcolor=palette.accent,
            darkcolor=palette.accent,
            troughrelief="flat",
        )
        style.map(
            "Horizontal.TScale",
            background=[
                ("active", palette.accent_hover),
                ("disabled", palette.disabled),
            ],
        )
        sb_metrics = dlgs.scrollbar_metrics(self.ui_zoom)
        style.configure(
            "Vertical.TScrollbar",
            background=palette.surface_alt,
            troughcolor=palette.surface,
            arrowcolor=palette.muted,
            bordercolor=palette.surface,
            sliderthickness=sb_metrics.vertical_thickness,
            arrowsize=sb_metrics.arrow_size,
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=palette.surface_alt,
            troughcolor=palette.surface,
            arrowcolor=palette.muted,
            bordercolor=palette.surface,
            sliderthickness=sb_metrics.horizontal_thickness,
            arrowsize=sb_metrics.arrow_size,
        )
        style.configure(
            "Treeview",
            background=palette.field,
            fieldbackground=palette.field,
            foreground=palette.foreground,
            bordercolor=palette.border,
        )
        style.map(
            "Treeview",
            background=[("selected", palette.selection)],
            foreground=[("selected", "#FFFFFF")],
        )
        style.configure(
            "Treeview.Heading",
            background=palette.surface_alt,
            foreground=palette.foreground,
            font=self.fonts["body_bold"],
            relief="flat",
        )

        self.root.option_add("*TCombobox*Listbox.background", palette.field)
        self.root.option_add("*TCombobox*Listbox.foreground", palette.foreground)
        self.root.option_add("*TCombobox*Listbox.selectBackground", palette.selection)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        self.root.configure(background=palette.background)
        if hasattr(self, "page_canvas"):
            self.page_canvas.configure(background=palette.background)
        for text_widget_name in ("results", "export_results", "resize_results"):
            text_widget = getattr(self, text_widget_name, None)
            if text_widget is not None:
                text_widget.configure(
                    background=palette.console_background,
                    foreground=palette.console_foreground,
                    insertbackground=palette.console_foreground,
                    selectbackground=palette.selection,
                    selectforeground="#FFFFFF",
                    highlightbackground=palette.border,
                    highlightcolor=palette.accent,
                    font=self.fonts["mono"],
                )
        if hasattr(self, "sidebar_handle"):
            self.sidebar_handle.configure(bg=palette.border)
        if hasattr(self, "sidebar_collapse_arrow"):
            self.sidebar_collapse_arrow.configure(
                bg=palette.sidebar, fg=palette.sidebar_muted
            )
        if hasattr(self, "sidebar_collapsed") and self.sidebar_collapsed:
            m = self._compute_sidebar_metrics()
            self._apply_collapsed_layout(m)
            self._update_nav_styles()
        elif hasattr(self, "sidebar_collapsed") and not self.sidebar_collapsed:
            for (section, label), button in zip(
                self.SECTIONS, self.navigation_buttons
            ):
                button.configure(
                    image="", text=label, font=self.fonts["body_bold"],
                    compound="left", anchor="w", padx=14, pady=10,
                )
            self._nav_icons.clear()
            self._update_nav_styles()
        if hasattr(self, "method_accents") and self.method_accents:
            selected = self.import_method_var.get()
            for name, accent in self.method_accents.items():
                accent.configure(bg=palette.accent if name == selected else palette.border)
                header = accent.master
                if isinstance(header, tk.Frame):
                    header.configure(bg=palette.surface)

        dlgs.configure_dialog_styles(style, palette, self.ui_zoom)
        dlgs.refresh_all_open_dialogs(palette, self.ui_zoom)
        self._apply_ui_scale_widget_theme()

    def _capture_scalable_ui(self) -> None:
        def descendants(widget: tk.Misc) -> list[tk.Misc]:
            items: list[tk.Misc] = []
            for child in widget.winfo_children():
                items.append(child)
                items.extend(descendants(child))
            return items

        for widget in descendants(self.root):
            try:
                raw_padding = widget.cget("padding")
                parts = self.root.tk.splitlist(raw_padding)
                padding = tuple(int(float(part)) for part in parts)
            except (tk.TclError, TypeError, ValueError):
                padding = ()
            if padding:
                self.scaled_widget_paddings.append((widget, padding))

    def _on_scale_drag(self, value: str) -> None:
        self._snap_scale_label(float(value))

    def _on_scale_released(self, event: tk.Event | None = None) -> None:
        self._apply_ui_scale(self.ui_scale_var.get())

    def _set_scale(self, value: int) -> None:
        self.ui_scale_var.set(value)
        self._apply_ui_scale(value)

    def _bind_ui_scale_interactions(self) -> None:
        self.ui_scale.bind("<Enter>", self._on_ui_scale_enter, add="+")
        self.ui_scale.bind("<Leave>", self._on_ui_scale_leave, add="+")
        self.ui_scale.bind("<FocusIn>", self._on_ui_scale_focus_in, add="+")
        self.ui_scale.bind("<FocusOut>", self._on_ui_scale_focus_out, add="+")
        self.ui_scale.bind("<ButtonPress-1>", self._on_ui_scale_press, add="+")
        self.ui_scale.bind("<ButtonRelease-1>", self._on_ui_scale_release, add="+")

    def _on_ui_scale_enter(self, _event: tk.Event) -> None:
        self._ui_scale_hovered = True
        self._refresh_ui_scale_visual_state()

    def _on_ui_scale_leave(self, _event: tk.Event) -> None:
        if self._ui_scale_pressed:
            return
        self._ui_scale_hovered = False
        self._refresh_ui_scale_visual_state()

    def _on_ui_scale_focus_in(self, _event: tk.Event) -> None:
        self._ui_scale_focused = True
        self._refresh_ui_scale_visual_state()

    def _on_ui_scale_focus_out(self, _event: tk.Event) -> None:
        self._ui_scale_focused = False
        self._refresh_ui_scale_visual_state()

    def _on_ui_scale_press(self, _event: tk.Event) -> None:
        self._ui_scale_pressed = True
        self._refresh_ui_scale_visual_state()

    def _on_ui_scale_release(self, _event: tk.Event) -> None:
        self._ui_scale_pressed = False
        try:
            px = self.ui_scale.winfo_pointerx() - self.ui_scale.winfo_rootx()
            py = self.ui_scale.winfo_pointery() - self.ui_scale.winfo_rooty()
            over_widget = (
                0 <= px < self.ui_scale.winfo_width()
                and 0 <= py < self.ui_scale.winfo_height()
            )
            if over_widget:
                self._ui_scale_hovered = True
            else:
                self._ui_scale_hovered = False
        except tk.TclError:
            self._ui_scale_hovered = False
        self._refresh_ui_scale_visual_state()
        self._on_scale_released(_event)

    def _refresh_ui_scale_visual_state(self) -> None:
        if not hasattr(self, "ui_scale"):
            return
        active = (
            self._ui_scale_pressed
            or self._ui_scale_focused
            or self._ui_scale_hovered
        )
        colors = dlgs.ui_scale_colors(self.current_palette)
        try:
            self.ui_scale.configure(
                background=colors.thumb_active if active else colors.thumb,
                highlightcolor=colors.focus_border if self._ui_scale_focused else colors.border,
            )
        except tk.TclError:
            pass

    def _apply_ui_scale_widget_theme(self) -> None:
        if not hasattr(self, "ui_scale"):
            return
        sm = dlgs.ui_scale_metrics(self.ui_zoom * max(1.0, self.current_dpi / 96.0))
        colors = dlgs.ui_scale_colors(self.current_palette)
        try:
            self.ui_scale.configure(
                troughcolor=colors.trough,
                activebackground=colors.thumb_active,
                highlightbackground=colors.border,
                width=sm.trough_width,
                sliderlength=sm.slider_length,
                highlightthickness=sm.highlight_thickness,
            )
        except tk.TclError:
            return
        self._refresh_ui_scale_visual_state()

    def _snap_scale_label(self, value: float) -> None:
        percent = int(round(value / 5.0) * 5)
        percent = max(MIN_UI_SCALE, min(MAX_UI_SCALE, percent))
        self.ui_scale_label_var.set(f"{percent}%")
        if round(self.ui_scale_var.get()) != percent:
            self.ui_scale_var.set(percent)

    def _apply_ui_scale(self, value: float) -> None:
        percent = int(round(float(value) / 5.0) * 5)
        percent = max(MIN_UI_SCALE, min(MAX_UI_SCALE, percent))
        self.ui_scale_label_var.set(f"{percent}%")
        if round(self.ui_scale_var.get()) != percent:
            self.ui_scale_var.set(percent)

        user_factor = percent / 100.0
        dimension_factor = user_factor * max(1.0, self.current_dpi / 96.0)
        base_font_sizes = {
            "arrow": 20,
            "body": 10,
            "body_bold": 10,
            "title": 22,
            "section": 11,
            "small": 9,
            "mono": 9,
        }
        for name, base_size in base_font_sizes.items():
            self.fonts[name].configure(size=max(7, round(base_size * user_factor)))

        for widget, padding in self.scaled_widget_paddings:
            try:
                widget.configure(
                    padding=tuple(
                        max(0, round(item * dimension_factor)) for item in padding
                    )
                )
            except tk.TclError:
                pass

        style = ttk.Style(self.root)
        style.configure(
            "TButton",
            padding=(round(12 * dimension_factor), round(7 * dimension_factor)),
        )
        style.configure(
            "Primary.TButton",
            padding=(round(16 * dimension_factor), round(8 * dimension_factor)),
        )
        style.configure(
            "Icon.TButton",
            padding=(round(7 * dimension_factor), round(5 * dimension_factor)),
        )
        style.configure(
            "Arrow.TButton",
            padding=(round(7 * dimension_factor), round(5 * dimension_factor)),
        )
        style.configure(
            "TEntry",
            padding=(round(9 * dimension_factor), round(7 * dimension_factor)),
        )
        style.configure(
            "TCombobox",
            padding=(round(8 * dimension_factor), round(6 * dimension_factor)),
        )
        style.configure(
            "TCheckbutton",
            indicatorsize=max(8, round(10 * dimension_factor)),
        )
        style.configure(
            "TRadiobutton",
            indicatordiameter=max(7, round(9 * dimension_factor)),
        )
        style.configure("Treeview", rowheight=max(24, round(30 * dimension_factor)))
        style.configure(
            "Horizontal.TScale",
            sliderlength=max(14, round(22 * dimension_factor)),
            sliderthickness=max(10, round(16 * dimension_factor)),
        )
        sb = dlgs.scrollbar_metrics(dimension_factor)
        style.configure(
            "Vertical.TScrollbar",
            sliderthickness=sb.vertical_thickness,
            arrowsize=sb.arrow_size,
        )
        style.configure(
            "Horizontal.TScrollbar",
            sliderthickness=sb.horizontal_thickness,
            arrowsize=sb.arrow_size,
        )
        dlgs.configure_dialog_styles(style, self.current_palette, self.ui_zoom)
        self._update_logo_scale(dimension_factor)
        self._refresh_sidebar_layout()
        self.root.update_idletasks()
        dlgs.refresh_all_open_dialogs(self.current_palette, self.ui_zoom)
        self._apply_ui_scale_widget_theme()

    def _update_logo_scale(self, factor: float) -> None:
        if not self.logo_source or not self.logo_label:
            return
        if not self.sidebar_collapsed:
            src_w = self.logo_source.width()
            target_w = min(src_w, max(72, round(120 * factor)))
            if target_w >= src_w:
                self.logo_image = self.logo_source
            else:
                ratio = subsample_ratio(src_w, target_w)
                self.logo_image = self.logo_source.subsample(ratio, ratio)
            self.logo_label.configure(image=self.logo_image)

    def _update_custom_path_states(self) -> None:
        python_state = "normal" if self.use_custom_python_var.get() else "disabled"
        obs_state = "normal" if self.use_custom_obs_var.get() else "disabled"
        if hasattr(self, "python_path_entry"):
            self.python_path_entry.configure(state=python_state)
            self.python_browse_button.configure(state=python_state)
            self.obs_path_entry.configure(state=obs_state)
            self.obs_browse_button.configure(state=obs_state)

    def _browse_python(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose Python executable",
            filetypes=(("Python executable", "python*.exe"), ("Executables", "*.exe")),
            parent=self.root,
        )
        if selected:
            self.python_path_var.set(selected)

    def _browse_obs(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose OBS executable",
            filetypes=(("OBS executable", "obs64.exe"), ("Executables", "*.exe")),
            parent=self.root,
        )
        if selected:
            self.obs_path_var.set(selected)

    def _apply_tool_logs(self) -> None:
        show = self.tool_logs_var.get()
        for label, text, scrollbar in (
            (self.results_label, self.results, self.results_scrollbar),
            (self.export_log_label, self.export_results, self.export_results_scrollbar),
            (self.resize_log_label, self.resize_results, self.resize_results_scrollbar),
        ):
            if show:
                label.grid(row=5, column=0, sticky="w")
                text.grid(row=6, column=0, sticky="nsew", pady=(8, 0))
                scrollbar.grid(row=6, column=1, sticky="ns", pady=(8, 0))
            else:
                label.grid_remove()
                text.grid_remove()
                scrollbar.grid_remove()

    def _collect_settings(self) -> AppSettings:
        remembered_folder = ""
        if self.remember_folder_var.get():
            current_folder = self.folder_var.get().strip()
            if current_folder and Path(current_folder).is_dir():
                remembered_folder = current_folder
            else:
                remembered_folder = self.settings.last_overlay_folder
        return AppSettings(
            theme=THEME_LABELS.get(self.theme_var.get(), "system"),
            ui_scale=int(round(self.ui_scale_var.get() / 5.0) * 5),
            sidebar_collapsed=self.sidebar_collapsed,
            use_custom_python=self.use_custom_python_var.get(),
            python_path=self.python_path_var.get().strip(),
            use_custom_obs=self.use_custom_obs_var.get(),
            obs_path=self.obs_path_var.get().strip(),
            remember_last_folder=self.remember_folder_var.get(),
            last_overlay_folder=remembered_folder,
            open_output_after_conversion=self.open_output_var.get(),
            show_tool_logs=self.tool_logs_var.get(),
        )

    def _save_settings(self) -> bool:
        settings = self._collect_settings()
        for enabled, path_value, label in (
            (settings.use_custom_python, settings.python_path, "Python executable"),
            (settings.use_custom_obs, settings.obs_path, "OBS executable"),
        ):
            if enabled and not Path(path_value).is_file():
                messagebox.showerror(APP_TITLE, f"Choose a valid {label.lower()} file.", parent=self.root)
                self.settings_status_var.set(f"{label} was not saved.")
                return False
        try:
            self.settings_store.save(settings)
        except OSError:
            messagebox.showerror(
                APP_TITLE, self.settings_store.last_error or "Settings failed."
            )
            self.settings_status_var.set("Settings could not be saved.")
            return False
        self.settings = settings
        self.settings_status_var.set(f"Saved to {self.settings_store.path}")
        return True

    def _restore_defaults(self) -> None:
        defaults = AppSettings()
        self.theme_var.set(THEME_NAMES[defaults.theme])
        self.ui_scale_var.set(defaults.ui_scale)
        self.use_custom_python_var.set(defaults.use_custom_python)
        self.python_path_var.set(defaults.python_path)
        self.use_custom_obs_var.set(defaults.use_custom_obs)
        self.obs_path_var.set(defaults.obs_path)
        self.remember_folder_var.set(defaults.remember_last_folder)
        self.open_output_var.set(defaults.open_output_after_conversion)
        self.tool_logs_var.set(defaults.show_tool_logs)
        self._update_custom_path_states()
        self._apply_theme()
        self._set_scale(defaults.ui_scale)
        self._set_sidebar_collapsed(False, persist=False)
        self._apply_tool_logs()
        if self._save_settings():
            self.settings_status_var.set("Default settings restored.")

    def _browse(self) -> None:
        # One browse entry for both flows: pick a normal folder, or a ZIP
        # archive that is extracted beside itself before scanning.
        selected = filedialog.askdirectory(
            title="Choose the extracted overlay folder (or cancel to pick a ZIP archive)"
        )
        if not selected:
            selected = filedialog.askopenfilename(
                title="Choose a ZIP overlay package",
                filetypes=(
                    ("ZIP archives", "*.zip"),
                    ("All files", "*.*"),
                ),
            )
        if selected:
            self.folder_var.set(selected)
            if self.remember_folder_var.get():
                self.settings.last_overlay_folder = selected
                self.settings.remember_last_folder = True
                try:
                    self.settings_store.save(self.settings)
                except OSError:
                    pass
            self._scan()

    def _select_import_method(self, method: str) -> None:
        self.import_method_var.set(method)
        palette = self.current_palette
        for name, accent in self.method_accents.items():
            accent.configure(bg=palette.accent if name == method else palette.border)
        for name in self.method_expanded:
            self.method_expanded[name] = name == method
        self._update_import_method_panels()

    def _toggle_import_method(self, method: str) -> None:
        if self.import_method_var.get() != method:
            self._select_import_method(method)
            return
        self.method_expanded[method] = not self.method_expanded[method]
        self._update_import_method_panels()

    def _update_import_method_panels(self) -> None:
        labels = {
            "obs": "Import OBS Scene Collection File",
            "streamlabs": "Import Streamlabs Scene File",
        }
        for method, options in self.method_options.items():
            if self.method_expanded[method]:
                options.grid()
            else:
                options.grid_remove()
            self.method_arrows[method].configure(
                text="▾" if self.method_expanded[method] else "▸"
            )
        selected = self.import_method_var.get()
        self.selected_method_label.configure(text=f"Selected: {labels[selected]}")
        self.run_button.configure(state="disabled" if self.busy else "normal")

    def _run_selected_method(self) -> None:
        method = self.import_method_var.get()
        if method == "obs":
            self._convert()
        else:
            self._import_streamlabs()

    def _configured_obs_scenes_directory(self) -> Path:
        executable: Path | None = None
        if self.use_custom_obs_var.get():
            custom_path = Path(self.obs_path_var.get().strip())
            if custom_path.is_file():
                executable = custom_path
        if executable is None:
            executable = self.detected_obs_path
        return default_obs_scenes_directory(executable)

    def _refresh_export_collections(self) -> None:
        if self.busy:
            return
        scenes_directory = self._configured_obs_scenes_directory()
        self.export_collections = list_obs_scene_collections(scenes_directory)
        labels = list(self.export_collections)
        self.export_collection_combo.configure(values=labels)
        selected = self.export_collection_var.get()
        active = active_obs_scene_collection(scenes_directory)
        active_label = next(
            (
                label
                for label, path in self.export_collections.items()
                if active and path == active
            ),
            None,
        )
        if active_label:
            self.export_collection_var.set(active_label)
        elif selected in self.export_collections:
            self.export_collection_var.set(selected)
        elif labels:
            self.export_collection_var.set(labels[0])
        else:
            self.export_collection_var.set("")
        self.export_status_var.set(
            "Choose a scene collection and destination folder."
            if labels
            else "No OBS scene collections were found. Check OBS in Settings, then Refresh."
        )

    def _browse_export_destination(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose the overlay export destination"
        )
        if selected:
            self.export_destination_var.set(selected)

    def _export_overlay(self) -> None:
        if self.busy:
            return
        collection = self.export_collections.get(self.export_collection_var.get())
        if collection is None or not collection.is_file():
            messagebox.showerror(
                APP_TITLE, "Choose a valid OBS scene collection first."
            )
            return
        destination = Path(self.export_destination_var.get().strip())
        if not destination.is_dir():
            messagebox.showerror(APP_TITLE, "Choose a valid export destination folder.")
            return
        self._set_busy(True, "Inspecting the scene collection before export…")
        self.export_status_var.set("Building the export inventory…")
        self._write_export_results("")
        compressed = self.export_compress_var.get()
        threading.Thread(
            target=self._export_inventory_worker,
            args=(collection, destination, compressed),
            daemon=True,
        ).start()

    def _export_inventory_worker(self, collection: Path, destination: Path, compressed: bool) -> None:
        try:
            from .exporter import build_export_plan, export_inventory_from_plan
            plan = build_export_plan(collection, destination, compressed=compressed)
            inventory = export_inventory_from_plan(plan)
            self.events.put(("export_inventory", inventory))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _export_worker(self, collection: Path, destination: Path, compressed: bool, plan: object) -> None:
        try:
            from .exporter import export_scene_collection
            result = export_scene_collection(collection, destination, compressed=compressed, plan=plan)
            self.events.put(("export", result))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _refresh_resize_collections(self) -> None:
        if self.busy:
            return
        scenes_directory = self._configured_obs_scenes_directory()
        self.resize_collections = list_obs_scene_collections(scenes_directory)
        labels = list(self.resize_collections)
        self.resize_collection_combo.configure(values=labels)
        selected = self.resize_collection_var.get()
        active = active_obs_scene_collection(scenes_directory)
        active_label = next(
            (
                label
                for label, path in self.resize_collections.items()
                if active and path == active
            ),
            None,
        )
        if active_label:
            self.resize_collection_var.set(active_label)
        elif selected in self.resize_collections:
            self.resize_collection_var.set(selected)
        elif labels:
            self.resize_collection_var.set(labels[0])
        else:
            self.resize_collection_var.set("")
        self._refresh_resize_targets()
        self._refresh_resize_screen_size()
        self.resize_status_var.set(
            "Choose what to resize and a target size."
            if labels
            else "No OBS scene collections were found. Check OBS in Settings, then Refresh."
        )

    def _refresh_resize_targets(self) -> None:
        collection = self.resize_collections.get(self.resize_collection_var.get())
        scope = self.resize_scope_var.get()
        if collection is None:
            self.resize_source_choices.clear()
            self.resize_name_combo.configure(values=(), state="disabled")
            self.resize_name_var.set("")
            return
        if scope == SCOPE_COLLECTION:
            self.resize_source_choices.clear()
            self.resize_name_combo.configure(values=(), state="disabled")
            self.resize_name_var.set("")
            return
        self.resize_source_choices.clear()
        try:
            data = load_json(collection)
            if scope == SCOPE_SCENE:
                names = scene_names(data)
            else:
                choices = source_choices(data)
                self.resize_source_choices = {
                    choice.label: choice.uuid for choice in choices
                }
                names = [choice.label for choice in choices]
        except UtilityError:
            names = []
        self.resize_name_combo.configure(
            values=names, state="readonly" if names else "disabled"
        )
        if self.resize_name_var.get() not in names:
            self.resize_name_var.set(names[0] if names else "")

    def _refresh_resize_screen_size(self) -> None:
        canvas = active_profile_canvas(self._configured_obs_scenes_directory())
        if canvas:
            self.resize_screen_size_var.set(
                f"Screen size: {canvas.width} × {canvas.height} (active OBS profile: {canvas.profile_name})"
            )
        else:
            self.resize_screen_size_var.set(
                "Screen size unavailable; choose Custom size or configure OBS in Settings."
            )

    def _update_resize_size_mode(self) -> None:
        state = (
            "normal"
            if self.resize_size_mode_var.get() == "custom" and not self.busy
            else "disabled"
        )
        self.resize_width_entry.configure(state=state)
        self.resize_height_entry.configure(state=state)

    def _prepare_live_connection(self) -> tuple[str | None, str, str | None]:
        """Connect to OBS, prompting once for an in-memory-only password."""
        try:
            with ObsWebSocketClient(password=self.obs_websocket_password) as client:
                current, _collections = client.scene_collections()
                return self.obs_websocket_password, current, None
        except ObsAuthenticationRequired:
            password = simpledialog.askstring(
                "OBS Live Control",
                "Enter the password shown in OBS under Tools → WebSocket Server Settings.\n\n"
                "The password is kept only until this app closes.",
                show="*",
                parent=self.root,
            )
            if password is None:
                return None, "", "OBS live control was cancelled."
            try:
                with ObsWebSocketClient(password=password) as client:
                    current, _collections = client.scene_collections()
                self.obs_websocket_password = password
                return password, current, None
            except ObsLiveError as exc:
                return None, "", str(exc)
        except ObsLiveError as exc:
            return None, "", str(exc)

    def _auto_device_setup(
        self, collection_path: Path | None, collection_name: str
    ) -> None:
        """Auto-match device sources to local devices, then activate live."""
        if collection_path is None:
            self._activate_imported_collection(collection_name)
            return
        try:
            mapped, unconfigured = auto_apply_device_choices(
                collection_path,
                self._configured_obs_scenes_directory(),
                exclude_collection=collection_path,
            )
        except UtilityError as exc:
            self._append_import_results(
                f"\n\nDevice setup could not be completed: {exc}"
            )
        else:
            if mapped or unconfigured:
                self._append_import_results(
                    "\n\nDevice setup: "
                    f"{mapped} auto-matched to local devices; "
                    f"{unconfigured} left unconfigured for manual setup in OBS."
                )
        self._activate_imported_collection(collection_name)

    def _activate_imported_collection(self, name: str) -> None:
        if not is_obs_running():
            self._append_import_results(
                "\n\nOBS is closed. The collection will be available on the next OBS launch."
            )
            return
        password, _current, error = self._prepare_live_connection()
        if error:
            self._append_import_results(
                f"\n\nThe collection was installed, but live activation was unavailable: {error}"
            )
            return
        try:
            with ObsWebSocketClient(password=password) as client:
                client.activate_scene_collection(name)
            self._append_import_results(
                f'\n\nLive OBS: switched to "{name}". No restart required.'
            )
        except ObsLiveError as exc:
            self._append_import_results(
                f"\n\nThe collection was installed, but OBS could not activate it live: {exc}"
            )

    def _resize_target_size(self) -> tuple[int, int]:
        if self.resize_size_mode_var.get() == "screen":
            canvas = active_profile_canvas(self._configured_obs_scenes_directory())
            if not canvas:
                raise UtilityError(
                    "OBS's active profile canvas could not be read. Choose Custom size instead."
                )
            return canvas.width, canvas.height
        try:
            return int(self.resize_width_var.get().strip()), int(
                self.resize_height_var.get().strip()
            )
        except ValueError as exc:
            raise UtilityError(
                "Enter whole-number custom width and height values."
            ) from exc

    def _run_resize(self) -> None:
        if self.busy:
            return
        collection = self.resize_collections.get(self.resize_collection_var.get())
        if collection is None or not collection.is_file():
            messagebox.showerror(
                APP_TITLE, "Choose a valid OBS scene collection first."
            )
            return
        scope = self.resize_scope_var.get()
        selected_name = self.resize_name_var.get().strip() or None
        selected_uuid = (
            self.resize_source_choices.get(selected_name or "")
            if scope == SCOPE_SOURCE
            else None
        )
        if (scope == SCOPE_SCENE and not selected_name) or (
            scope == SCOPE_SOURCE and not selected_uuid
        ):
            messagebox.showerror(
                APP_TITLE, "Choose a valid scene or UUID-backed source first."
            )
            return
        try:
            target_width, target_height = self._resize_target_size()
        except UtilityError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        collection_name = str(load_json(collection).get("name", collection.stem))
        if is_obs_running():
            password, current, live_error = self._prepare_live_connection()
            if not live_error and current == collection_name:
                self._set_busy(True, "Resizing the active collection inside OBS…")
                self.resize_status_var.set("Applying live transforms through OBS…")
                self._write_resize_results("")
                threading.Thread(
                    target=self._live_resize_worker,
                    args=(
                        collection, password, collection_name, scope, selected_name,
                        selected_uuid, self.resize_mode_var.get(), target_width, target_height,
                    ),
                    daemon=True,
                ).start()
                return
            active_path = active_obs_scene_collection(
                self._configured_obs_scenes_directory()
            )
            if live_error and active_path and active_path.resolve() == collection.resolve():
                messagebox.showerror(
                    APP_TITLE,
                    "The active collection cannot be safely overwritten while OBS is open.\n\n"
                    f"{live_error}",
                )
                return
        self._set_busy(True, "Resizing the selected OBS collection…")
        self.resize_status_var.set(
            "Writing the resized collection and its undo backup…"
        )
        self._write_resize_results("")
        threading.Thread(
            target=self._resize_worker,
            args=(
                collection,
                scope,
                selected_name,
                selected_uuid,
                self.resize_mode_var.get(),
                target_width,
                target_height,
            ),
            daemon=True,
        ).start()

    def _resize_worker(
        self,
        collection: Path,
        scope: str,
        selected_name: str | None,
        selected_uuid: str | None,
        mode: str,
        target_width: int,
        target_height: int,
    ) -> None:
        self.events.put(
            (
                "resize",
                resize_collection(
                    collection,
                    scope=scope,
                    selected_name=selected_name,
                    selected_uuid=selected_uuid,
                    mode=mode,
                    target_width=target_width,
                    target_height=target_height,
                ),
            )
        )

    def _live_resize_worker(
        self, collection: Path, password: str | None, collection_name: str,
        scope: str, selected_name: str | None, selected_uuid: str | None,
        mode: str, target_width: int, target_height: int,
    ) -> None:
        outcome = resize_active_collection(
            password=password,
            collection_name=collection_name,
            scope=scope,
            selected_name=selected_name,
            selected_uuid=selected_uuid,
            mode=mode,
            target_width=target_width,
            target_height=target_height,
        )
        outcome.result.collection_path = collection
        self.events.put(("live_resize", outcome))

    def _undo_resize(self) -> None:
        if self.busy:
            return
        if self.last_live_resize_snapshot:
            self._set_busy(True, "Undoing the live resize inside OBS…")
            threading.Thread(
                target=self._undo_live_resize_worker,
                args=(self.last_live_resize_snapshot,),
                daemon=True,
            ).start()
            return
        if not self.last_resize_collection or not self.last_resize_backup:
            return
        self._set_busy(True, "Restoring the collection from its resize backup…")
        self.resize_status_var.set("Restoring the last resize backup…")
        threading.Thread(
            target=self._undo_resize_worker,
            args=(self.last_resize_collection, self.last_resize_backup),
            daemon=True,
        ).start()

    def _undo_resize_worker(self, collection: Path, backup: Path) -> None:
        self.events.put(
            ("resize_undo", (collection, backup, undo_resize(collection, backup)))
        )

    def _undo_live_resize_worker(self, snapshot: LiveResizeSnapshot) -> None:
        self.events.put((
            "live_resize_undo",
            (snapshot, undo_live_resize(self.obs_websocket_password, snapshot)),
        ))

    def _browse_streamlabs(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose a Streamlabs overlay package",
            filetypes=(
                ("Streamlabs overlay", "*.overlay"),
                ("ZIP packages", "*.zip"),
                ("All files", "*.*"),
            ),
        )
        if selected:
            self.streamlabs_file_var.set(selected)

    def _import_streamlabs(self) -> None:
        if self.busy:
            return
        archive = Path(self.streamlabs_file_var.get().strip())
        if not archive.is_file():
            messagebox.showerror(
                APP_TITLE, "Choose a valid Streamlabs .overlay package."
            )
            return
        if self.use_custom_obs_var.get():
            configured_path = Path(self.obs_path_var.get().strip())
            if not configured_path.is_file():
                messagebox.showerror(
                    APP_TITLE, "Choose a valid custom OBS executable in Settings first."
                )
                return
            executable: Path | None = configured_path
        else:
            executable = self.detected_obs_path
        self._set_busy(True, "Extracting and converting the Streamlabs package…")
        self._write_results("")
        target = default_obs_scenes_directory(executable)
        threading.Thread(
            target=self._streamlabs_worker,
            args=(archive, target, self.scale_to_canvas_var.get()),
            daemon=True,
        ).start()

    def _streamlabs_worker(self, archive: Path, target: Path, scale_to_canvas: bool) -> None:
        self.events.put(
            (
                "streamlabs",
                import_streamlabs_overlay(
                    archive, target, scale_to_canvas=scale_to_canvas
                ),
            )
        )

    def _scan(self) -> None:
        if self.busy:
            return
        folder = Path(self.folder_var.get().strip())
        if not folder.is_dir() and not _is_zip_path(folder):
            messagebox.showerror(
                APP_TITLE, "Choose a valid overlay folder or ZIP archive."
            )
            return
        self.last_output = None
        self._scan_busy_message = "Extracting the ZIP archive…" if _is_zip_path(folder) else "Finding an OBS scene collection export…"
        self._set_busy(True, self._scan_busy_message)
        threading.Thread(target=self._scan_worker, args=(folder,), daemon=True).start()

    def _scan_worker(self, folder: Path) -> None:
        try:
            if _is_zip_path(folder):
                folder = extract_zip_archive(folder)
                self._extracted_overlay_root = folder
                self.events.put(("note", f"Extracted ZIP archive to:\n{folder}"))
                self.events.put(("busy_text", "Finding an OBS scene collection export…"))
            self.events.put(("scan", find_scene_collections(folder)))
        except UtilityError as exc:
            self.events.put(("error", str(exc)))

    def _convert(self) -> None:
        if self.busy:
            return
        collection = self.collections.get(self.collection_var.get())
        folder = Path(self.folder_var.get().strip())
        if _is_zip_path(folder):
            folder = getattr(self, "_extracted_overlay_root", None) or folder
        if (
            collection is not None
            and folder.is_dir()
            and not collection.is_relative_to(folder.resolve())
        ):
            collection = None
        if collection is None:
            raw_folder = Path(self.folder_var.get().strip())
            if not raw_folder.is_dir() and not _is_zip_path(raw_folder):
                messagebox.showerror(
                    APP_TITLE, "Choose a valid overlay folder or ZIP archive."
                )
                return
            self.pending_obs_conversion = True
            self._scan()
            return
        self._set_busy(True, "Checking and matching overlay files…")
        self._write_results("")
        target = self._configured_obs_scenes_directory()
        threading.Thread(
            target=self._convert_worker,
            args=(
                collection,
                folder,
                True,
                True,
                target,
                self.scale_to_canvas_var.get(),
            ),
            daemon=True,
        ).start()

    def _convert_worker(
        self,
        collection: Path,
        folder: Path,
        strict: bool,
        case_sensitive: bool,
        target: Path,
        scale_to_canvas: bool,
    ) -> None:
        result = convert_collection(
            collection, folder, strict=strict, case_sensitive=case_sensitive
        )
        if result.success and result.output_path:
            try:
                name, path = install_scene_collection(result.output_path, target)
                result.installed_name = name
                result.installed_path = path
            except UtilityError as exc:
                result.install_error = str(exc)
            if scale_to_canvas and result.installed_path and not result.install_error:
                canvas = active_profile_canvas(target)
                if canvas is None:
                    result.scale_note = (
                        "OBS profile canvas could not be read; layout left unchanged."
                    )
                else:
                    try:
                        resize_collection(
                            result.installed_path,
                            scope=SCOPE_COLLECTION,
                            selected_name=None,
                            selected_uuid=None,
                            mode=MODE_SCALE_RATIO,
                            target_width=canvas.width,
                            target_height=canvas.height,
                        )
                        result.scaled = True
                        result.scale_note = f"{canvas.width} × {canvas.height}"
                    except UtilityError as exc:
                        result.scale_note = (
                            f"Could not scale to the OBS canvas ({exc})."
                        )
        self.events.put(("conversion", result))

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "scan":
                    self._finish_scan(payload)  # type: ignore[arg-type]
                elif event == "conversion":
                    self._finish_conversion(payload)  # type: ignore[arg-type]
                elif event == "streamlabs":
                    self._finish_streamlabs(payload)  # type: ignore[arg-type]
                elif event == "export_inventory":
                    self._finish_export_inventory(payload)  # type: ignore[arg-type]
                elif event == "export":
                    self._finish_export(payload)  # type: ignore[arg-type]
                elif event == "live_resize":
                    self._finish_live_resize(payload)  # type: ignore[arg-type]
                elif event == "live_resize_undo":
                    self._finish_live_resize_undo(payload)  # type: ignore[arg-type]
                elif event == "resize":
                    self._finish_resize(payload)  # type: ignore[arg-type]
                elif event == "resize_undo":
                    self._finish_resize_undo(payload)  # type: ignore[arg-type]
                elif event == "error":
                    self._set_busy(False, "Could not finish the operation.")
                    messagebox.showerror(APP_TITLE, str(payload))
                elif event == "note":
                    self._scan_note = str(payload)
                elif event == "busy_text":
                    self._set_busy(True, str(payload))
        except queue.Empty:
            pass
        self._process_events_after_id = self.root.after(100, self._process_events)

    def _finish_scan(self, paths: list[Path]) -> None:
        self.collections.clear()
        root = Path(self.folder_var.get().strip())
        if _is_zip_path(root):
            root = getattr(self, "_extracted_overlay_root", None) or root
        note = getattr(self, "_scan_note", None)
        self._scan_note = None
        for path in paths:
            try:
                label = str(path.relative_to(root))
            except ValueError:
                label = path.name
            if label in self.collections:
                label = str(path)
            self.collections[label] = path
        labels = list(self.collections)
        self.collection_var.set(labels[0] if labels else "")
        if labels:
            self._write_results(
                (f"{note}\n\n" if note else "")
                + "Automatically detected OBS export:\n"
                + "\n".join(f"• {label}" for label in labels)
            )
            self._set_busy(
                False, f"Found {len(labels)} OBS scene collection export(s)."
            )
            if self.pending_obs_conversion:
                self.pending_obs_conversion = False
                self._convert()
        else:
            self.pending_obs_conversion = False
            self._write_results(
                "No valid OBS scene collection was found. Make sure the downloaded package was fully extracted."
            )
            self._set_busy(False, "No OBS scene collection export found.")

    def _finish_conversion(self, result: ConversionResult) -> None:
        if result.error:
            self._write_results(result.error)
            self._set_busy(
                False, "Conversion failed safely; the original was not changed."
            )
            return

        lines = [
            f"Referenced local files: {result.candidate_paths}",
            f"Overlay files indexed: {result.indexed_files}",
            f"Paths updated: {result.changed}",
            f"Paths already valid: {result.unchanged}",
        ]
        if result.missing:
            lines.extend(
                ("", "Missing files:", *(f"• {item}" for item in result.missing))
            )
        if result.ambiguous:
            lines.extend(("", "Ambiguous matches:"))
            for problem in result.ambiguous:
                lines.append(f"• {problem.source_name}: {problem.original_path}")
                lines.extend(f"    - {candidate}" for candidate in problem.candidates)

        if result.success and result.output_path:
            self.last_output = result.output_path
            healthy = result.changed + result.unchanged
            lines.extend(
                (
                    "",
                    f"Local file references: {healthy} online · {len(result.missing)} missing.",
                )
            )
            if result.missing:
                lines.append(
                    "IMPORTANT: the missing references above will appear offline "
                    "in OBS until the missing files exist."
                )
            if result.plugin_source_ids:
                lines.append(
                    "Plugin sources/filters: "
                    + ", ".join(result.plugin_source_ids)
                    + " — install those plugins on this PC or they stay blank."
                )
            if result.remote_browser_urls:
                lines.append(
                    f"Browser overlays using the internet: {result.remote_browser_urls} "
                    "(e.g. StreamElements) — they only load while online."
                )
            if result.scaled:
                lines.append(
                    f"Scaled the layout to the active OBS canvas ({result.scale_note}), "
                    "aspect preserved."
                )
            elif result.scale_note:
                lines.append(f"Note: {result.scale_note}")
            lines.extend(("", f"Created: {result.output_path}"))
            if result.installed_name:
                lines.append(
                    f"Installed as OBS scene collection: {result.installed_name}"
                )
            if result.install_error:
                lines.append(
                    "Note: the collection could not be installed into OBS "
                    f"({result.install_error}). Import the file manually with "
                    "Scene Collection → Import."
                )
            self._set_busy(
                False,
                "Updated collection installed into OBS."
                if result.installed_name
                else "Updated collection created, but not installed into OBS.",
            )
        else:
            self._set_busy(
                False, "No file was written. Resolve the items below and try again."
            )
        self._write_results("\n".join(lines))
        if result.success and result.output_path:
            if self.open_output_var.get():
                self._open_output()
            if result.installed_name:
                self._activate_imported_collection(result.installed_name)

    def _finish_resize(self, result: ResizeResult) -> None:
        if result.error:
            self._write_resize_results(result.error)
            self.resize_status_var.set(
                "Resize failed safely; the collection was not overwritten."
            )
            self._set_busy(False, "Could not resize the scene collection.")
            return
        self.last_resize_collection = result.collection_path
        self.last_resize_backup = result.backup_path
        self.last_live_resize_snapshot = None
        canvas_text = (
            f"Canvas: {result.source_width} × {result.source_height} → {result.target_width} × {result.target_height}"
            if result.canvas_changed
            else f"Canvas preserved: {result.source_width} × {result.source_height}; selected target: {result.target_width} × {result.target_height}"
        )
        self._write_resize_results(
            "\n".join(
                (
                    (
                        f"Live OBS collection updated: {result.collection_path}"
                        if result.live
                        else f"Collection file overwritten: {result.collection_path}"
                    ),
                    (
                        "Undo snapshot: held in memory for this app session"
                        if result.live else f"Undo backup: {result.backup_path}"
                    ),
                    canvas_text,
                    f"Source items resized: {result.changed_items}",
                    "",
                    "OBS remained open and the change is already active." if result.live else "The inactive collection file was resized safely.",
                )
            )
        )
        self.resize_status_var.set(
            "Resize complete. Undo is available for this operation."
        )
        self._set_busy(False, "Scene collection resized successfully.")
        self.undo_resize_button.configure(state="normal")

    def _finish_resize_undo(self, payload: tuple[Path, Path, str | None]) -> None:
        collection, backup, error = payload
        if error:
            self._write_resize_results(error)
            self.resize_status_var.set("Undo failed; the resize backup was retained.")
            self._set_busy(False, "Could not restore the resize backup.")
            self.undo_resize_button.configure(state="normal")
            return
        self.last_resize_collection = None
        self.last_resize_backup = None
        self._write_resize_results(
            f"Undo complete. Restored inactive collection: {collection}\nRemoved used backup: {backup}"
        )
        self.resize_status_var.set("The last resize was restored.")
        self._set_busy(False, "Resize undo completed successfully.")
        self.undo_resize_button.configure(state="disabled")

    def _finish_live_resize(self, outcome: LiveResizeOutcome) -> None:
        self._finish_resize(outcome.result)
        self.last_live_resize_snapshot = outcome.snapshot
        self.undo_resize_button.configure(
            state="normal" if outcome.snapshot and outcome.result.success else "disabled"
        )

    def _finish_live_resize_undo(
        self, payload: tuple[LiveResizeSnapshot, str | None]
    ) -> None:
        _snapshot, error = payload
        if error:
            self._write_resize_results(error)
            self.resize_status_var.set("Live Undo failed; the snapshot was retained.")
            self._set_busy(False, "Could not undo the live resize.")
            self.undo_resize_button.configure(state="normal")
            return
        self.last_live_resize_snapshot = None
        self.last_resize_collection = None
        self.last_resize_backup = None
        self._write_resize_results(
            "Live Undo complete. OBS remained open and the restored layout is already active."
        )
        self.resize_status_var.set("The last live resize was restored.")
        self._set_busy(False, "Live resize undo completed successfully.")
        self.undo_resize_button.configure(state="disabled")

    def _finish_export_inventory(self, inventory: ExportInventory) -> None:
        if inventory.error or not inventory.success:
            error = inventory.error or "Could not build the export inventory."
            self._write_export_results(error)
            self.export_status_var.set(
                "Export inventory failed; no package was created."
            )
            self._set_busy(False, "Could not inspect the scene collection.")
            return
        if inventory.collection_path is None or inventory.destination is None:
            self._write_export_results("The export inventory is incomplete.")
            self._set_busy(False, "Could not inspect the scene collection.")
            return
        plan = inventory.plan
        compressed = plan.compressed if plan else False
        output_label = "ZIP archive" if compressed else "Package folder"
        output_path = str(plan.output_path) if plan else (str(inventory.package_path) + (".zip" if compressed else ""))

        summary_lines = [
            f"Proposed output: {output_path}",
            f"Output format: {output_label}",
            f"Scenes: {inventory.scene_count}",
            f"Sources: {inventory.source_count}",
            f"Unique files: {len(inventory.items)}",
            f"Total size: {format_file_size(inventory.total_bytes)}",
            f"Browser-overlay files: {inventory.browser_files}",
            f"Local references inspected: {inventory.source_references}",
            f"Missing references: {len(inventory.missing_references)}",
        ]
        if plan and plan.dependency_report:
            dr = plan.dependency_report
            if dr.plugin_source_ids:
                summary_lines.append(f"Plugin/unknown source IDs: {len(dr.plugin_source_ids)}")
            if dr.plugin_filter_ids:
                summary_lines.append(f"Plugin/unknown filter IDs: {len(dr.plugin_filter_ids)}")
            if dr.fonts:
                summary_lines.append(f"Fonts: {len(dr.fonts)}")
            if dr.remote_resources:
                summary_lines.append(f"Remote resources: {len(dr.remote_resources)}")
            if dr.has_sensitive_urls:
                summary_lines.append("WARNING: Remote URLs contain sensitive query parameters")
        summary_lines.extend(["", "Review the inventory window, then confirm or cancel the export."])
        self._write_export_results("\n".join(summary_lines))
        self.export_status_var.set("Review the export inventory before continuing.")
        self._show_export_inventory_confirmation(inventory)

    def _show_export_inventory_confirmation(self, inventory: ExportInventory) -> None:
        palette = self.current_palette
        zoom = self.ui_zoom
        space = dlgs.scaled_space(zoom)
        met = dlgs.dialog_metrics(ui_zoom=zoom, base_width=1000, base_height=720,
                                  base_min_width=680, base_min_height=500)
        dlg = dlgs.ThemedDialog(
            self.root, "Confirm Overlay Export", palette,
            ui_zoom=zoom, width=1000, height=720,
            min_width=680, min_height=500, modal=True,
        )
        plan = inventory.plan
        compressed = plan.compressed if plan else False
        output_label = "ZIP archive" if compressed else "Package folder"
        output_path = str(plan.output_path) if plan else (str(inventory.package_path) + (".zip" if compressed else ""))

        dr = plan.dependency_report if plan and plan.dependency_report else None

        # --- Header ---
        hdr = dlg.header(
            "Review Export Package",
            f"{inventory.scene_count} scenes, {inventory.source_count} sources — "
            f"{len(inventory.items)} local files, {format_file_size(inventory.total_bytes)}"
        )
        hdr.columnconfigure(0, weight=1)

        # Package path
        ttk.Label(
            hdr,
            text=f"Output: {output_path} ({output_label})",
            style="DialogBody.TLabel",
            wraplength=met.body_wraplength,
        ).grid(row=2, column=0, sticky="w", pady=(space.XS, 0))

        # Summary grid in header
        summary_vars = {
            "Unique files": str(len(inventory.items)),
            "Total uncompressed": format_file_size(inventory.total_bytes),
            "Browser files": str(inventory.browser_files),
            "Missing references": str(len(inventory.missing_references)),
            "Format": output_label,
        }
        if dr:
            if dr.plugin_source_ids:
                summary_vars["Plugin source IDs"] = str(len(dr.plugin_source_ids))
            if dr.plugin_filter_ids:
                summary_vars["Plugin filter IDs"] = str(len(dr.plugin_filter_ids))
            if dr.fonts:
                summary_vars["Fonts"] = str(len(dr.fonts))
            if dr.remote_resources:
                summary_vars["Remote resources"] = str(len(dr.remote_resources))
            if dr.devices:
                summary_vars["Devices"] = str(len(dr.devices))

        summary_row = 3
        items_per = 3
        keys = list(summary_vars)
        for i in range(0, len(keys), items_per):
            batch = keys[i:i + items_per]
            for j, k in enumerate(batch):
                col = j * 2
                ttk.Label(hdr, text=f"{k}:", style="DialogMuted.TLabel").grid(
                    row=summary_row, column=col, sticky="w",
                    padx=(0, space.XS), pady=(space.XS, 0))
                ttk.Label(hdr, text=summary_vars[k], style="DialogBody.TLabel").grid(
                    row=summary_row, column=col + 1, sticky="w",
                    padx=(0, space.XL), pady=(space.XS, 0))
            summary_row += 1

        # --- Warning ---
        warn = inventory.missing_references
        sensitive = dr and dr.has_sensitive_urls
        if warn or sensitive:
            wf = ttk.Frame(dlg.body, style="DialogWarning.TFrame")
            wf.grid(row=0, column=0, sticky="ew", pady=(0, space.MD))
            wf.columnconfigure(0, weight=1)
            wpad = space.MD
            msgs = []
            if warn:
                msgs.append(
                    f"{len(warn)} referenced file(s) could not be found and will "
                    "not be included. Review the Missing / Manual Review tab."
                )
            if sensitive:
                msgs.append(
                    "Remote URLs with sensitive query parameters were detected. "
                    "Credentials are not copied into the manifest."
                )
            for mi, msg in enumerate(msgs):
                ttk.Label(wf, text=msg, style="DialogWarning.TLabel",
                          wraplength=met.body_wraplength).grid(
                    row=mi, column=0, sticky="w", padx=wpad, pady=(wpad, wpad if mi == len(msgs) - 1 else 0))

        # --- Notebook ---
        note_row = 1 if warn or sensitive else 0
        nb = ttk.Notebook(dlg.body, style="Dialog.TNotebook")
        nb.grid(row=note_row, column=0, sticky="nsew")
        dlg.body.rowconfigure(note_row, weight=1)

        # Files tab
        files_frame = ttk.Frame(nb, style="DialogBody.TFrame")
        files_frame.columnconfigure(0, weight=1)
        files_frame.rowconfigure(0, weight=1)
        tree_cols = ("category", "size", "used_by", "source_path", "package_path")
        tree = ttk.Treeview(files_frame, columns=tree_cols, show="headings",
                            style="Dialog.Treeview")
        tree.heading("category", text="Category")
        tree.heading("size", text="Size")
        tree.heading("used_by", text="Used by")
        tree.heading("source_path", text="Source path")
        tree.heading("package_path", text="Package path")
        tree.column("category", width=100, stretch=False)
        tree.column("size", width=85, anchor="e", stretch=False)
        tree.column("used_by", width=180, stretch=False)
        tree.column("source_path", width=260, stretch=True)
        tree.column("package_path", width=260, stretch=True)
        tree.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(files_frame, orient="vertical", command=tree.yview,
                           style="Dialog.Vertical.TScrollbar")
        vs.grid(row=0, column=1, sticky="ns")
        hs = ttk.Scrollbar(files_frame, orient="horizontal", command=tree.xview,
                           style="Dialog.Horizontal.TScrollbar")
        hs.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

        if inventory.items:
            for item in inventory.items:
                tree.insert("", "end", values=(
                    item.category, format_file_size(item.size),
                    item.source_name, str(item.path), item.package_path))
        else:
            ttk.Label(files_frame, text="No local files to package.",
                      style="DialogMuted.TLabel").grid(
                row=2, column=0, sticky="w", pady=space.MD)

        tree.insert("", "end", values=("", "", "", "", ""))
        for missing in inventory.missing_references:
            tree.insert("", "end", values=("Missing", "\u2014", "", missing, ""))

        nb.add(files_frame, text="Files")

        # Requirements tab
        req_frame = ttk.Frame(nb, style="DialogBody.TFrame")
        req_frame.columnconfigure(0, weight=1)
        req_frame.rowconfigure(0, weight=1)
        req_tree = ttk.Treeview(req_frame, columns=("type", "detail"), show="headings",
                                style="Dialog.Treeview")
        req_tree.heading("type", text="Type")
        req_tree.heading("detail", text="Detail")
        req_tree.column("type", width=180, stretch=False)
        req_tree.column("detail", width=500, stretch=True)
        req_tree.grid(row=0, column=0, sticky="nsew")
        rvs = ttk.Scrollbar(req_frame, orient="vertical", command=req_tree.yview,
                           style="Dialog.Vertical.TScrollbar")
        rvs.grid(row=0, column=1, sticky="ns")
        req_tree.configure(yscrollcommand=rvs.set)

        has_reqs = False
        if dr:
            for f in dr.fonts:
                req_tree.insert("", "end", values=("Font", f))
                has_reqs = True
            for d in dr.devices:
                req_tree.insert("", "end", values=(
                    "Device", f"{d.get('source_name', '')} ({d.get('source_id', '')}) [{d.get('kind', '')}]"))
                has_reqs = True
            for r in dr.remote_resources:
                req_tree.insert("", "end", values=(
                    "Remote", f"{r.get('host', '')} {'[sensitive]' if r.get('sensitive') == 'yes' else ''}"))
                has_reqs = True
            for p in dr.plugin_source_ids:
                req_tree.insert("", "end", values=("Plugin source", f"{p['name']} ({p['id']})"))
                has_reqs = True
            for p in dr.plugin_filter_ids:
                req_tree.insert("", "end", values=("Plugin filter", f"{p['name']} ({p['id']})"))
                has_reqs = True
        if not has_reqs:
            ttk.Label(req_frame, text="No additional requirements detected.",
                      style="DialogMuted.TLabel").grid(
                row=1, column=0, sticky="w", pady=space.MD)
        nb.add(req_frame, text="Requirements")

        # Missing tab
        miss_frame = ttk.Frame(nb, style="DialogBody.TFrame")
        miss_frame.columnconfigure(0, weight=1)
        miss_frame.rowconfigure(0, weight=1)
        miss_tree = ttk.Treeview(miss_frame,
                                 columns=("source", "setting", "filename", "reason"),
                                 show="headings", style="Dialog.Treeview")
        miss_tree.heading("source", text="Source")
        miss_tree.heading("setting", text="Setting")
        miss_tree.heading("filename", text="Filename")
        miss_tree.heading("reason", text="Reason")
        miss_tree.column("source", width=150, stretch=False)
        miss_tree.column("setting", width=120, stretch=False)
        miss_tree.column("filename", width=200, stretch=True)
        miss_tree.column("reason", width=200, stretch=True)
        miss_tree.grid(row=0, column=0, sticky="nsew")
        mvs = ttk.Scrollbar(miss_frame, orient="vertical", command=miss_tree.yview,
                           style="Dialog.Vertical.TScrollbar")
        mvs.grid(row=0, column=1, sticky="ns")
        miss_tree.configure(yscrollcommand=mvs.set)

        if plan and plan.missing_references:
            for m in plan.missing_references:
                miss_tree.insert("", "end", values=(
                    m.get("source", ""), m.get("setting", ""),
                    m.get("basename", ""), m.get("reason", "")))
        else:
            ttk.Label(miss_frame, text="No missing files. All referenced files were found.",
                      style="DialogMuted.TLabel").grid(
                row=1, column=0, sticky="w", pady=space.MD)
        nb.add(miss_frame, text="Missing / Manual Review")

        # --- Footer ---
        def _cancel() -> None:
            dlg.close()
            self.export_status_var.set("Export cancelled after inventory review.")
            self._set_busy(False, "Overlay export cancelled.")

        def _confirm() -> None:
            coll = inventory.collection_path
            dest = inventory.destination
            p = inventory.plan
            comp = p.compressed if p else self.export_compress_var.get()
            dlg.close()
            self.export_status_var.set("Packaging the confirmed OBS collection…")
            self._write_export_results("Inventory confirmed. Exporting the package…")
            threading.Thread(
                target=self._export_worker,
                args=(coll, dest, comp, p),
                daemon=True,
            ).start()

        dlg.set_on_close(_cancel)
        dlg.footer_buttons([
            ("Cancel", _cancel, False),
            ("Confirm Export", _confirm, True),
        ])
        dlg.show()

    def _finish_export(self, result: ExportResult) -> None:
        if result.error:
            self._write_export_results(result.error)
            self.export_status_var.set(
                "Export failed safely; review the log and try again."
            )
            self._set_busy(False, "Could not export the scene collection.")
            return
        if result.compressed and result.archive_path:
            lines = [
                f"ZIP archive: {result.archive_path}",
                f"Archive size: {format_file_size(result.archive_bytes)}",
                f"Uncompressed size: {format_file_size(result.uncompressed_bytes)}",
                f"Files included: {result.copied_files}",
            ]
        else:
            lines = [
                f"Package folder: {result.package_path}",
                f"OBS export JSON: {result.collection_path}",
                f"Referenced files copied: {result.copied_files}",
            ]
        lines.extend([
            f"Local file references rewritten: {result.source_references}",
            "",
            "The JSON preserves OBS, plugin-source, and filter settings. Install required OBS plugins and fonts separately on the destination computer.",
        ])
        if result.verification:
            if result.verification.ok:
                lines.append("Package verification: PASSED")
            else:
                lines.append("Package verification: ISSUES FOUND")
                lines.extend(f"  - {e}" for e in result.verification.errors[:5])
        if result.skipped_references:
            lines.extend(("", "References requiring manual review:"))
            lines.extend(f"• {item}" for item in result.skipped_references)
        self._write_export_results("\n".join(lines))
        self.export_status_var.set("Overlay package exported successfully.")
        self._set_busy(False, "Overlay package exported successfully.")
        if self.open_output_var.get():
            if result.compressed and result.archive_path:
                self._open_folder(result.archive_path.parent)
            elif result.package_path:
                self._open_folder(result.package_path)

    def _finish_streamlabs(self, result: StreamlabsImportResult) -> None:
        if result.error:
            self._write_results(result.error)
            self._set_busy(
                False, "Streamlabs import failed safely; no OBS collection was created."
            )
            return

        lines = [
            f"OBS collection: {result.collection_name}",
            f"Collection file: {result.collection_path}",
            f"Extracted package: {result.extraction_path}",
            f"Canvas resized to: {result.canvas_width} × {result.canvas_height}"
            + (
                f" (active OBS profile: {result.profile_name})"
                if result.profile_name
                else ""
            ),
            f"Supported sources imported: {result.imported_sources}",
            "",
            "Matching device sources, then activating the collection in live OBS…",
        ]
        if result.skipped_sources:
            lines.extend(("", "Sources that need manual setup:"))
            lines.extend(f"• {item}" for item in result.skipped_sources)
        self._write_results("\n".join(lines))
        self._set_busy(False, "Streamlabs package imported into OBS successfully.")
        self._auto_device_setup(result.collection_path, result.collection_name)

    def _set_busy(self, busy: bool, status: str) -> None:
        self.busy = busy
        self.status_var.set(status)
        state = "disabled" if busy else "normal"
        for control in self.method_controls:
            control.configure(state=state)
        for control in self.export_controls:
            control.configure(state=state)
        for control in self.resizer_controls:
            control.configure(state=state)
        if not busy:
            self._update_resize_size_mode()
            self.undo_resize_button.configure(
                state="normal"
                if self.last_live_resize_snapshot or (self.last_resize_collection and self.last_resize_backup)
                else "disabled"
            )
        for button in self.navigation_buttons:
            button.configure(state=state)
        self.run_button.configure(state="disabled" if busy else "normal")

    def _append_import_results(self, text: str) -> None:
        self.results.configure(state="normal")
        self.results.insert("end", text)
        self.results.configure(state="disabled")

    def _write_resize_results(self, text: str) -> None:
        self.resize_results.configure(state="normal")
        self.resize_results.delete("1.0", "end")
        self.resize_results.insert("1.0", text)
        self.resize_results.configure(state="disabled")

    def _write_export_results(self, text: str) -> None:
        self.export_results.configure(state="normal")
        self.export_results.delete("1.0", "end")
        self.export_results.insert("1.0", text)
        self.export_results.configure(state="disabled")

    def _write_results(self, text: str) -> None:
        self.results.configure(state="normal")
        self.results.delete("1.0", "end")
        self.results.insert("1.0", text)
        self.results.configure(state="disabled")

    def _open_folder(self, folder: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Could not open the folder: {exc}")

    def _open_output(self) -> None:
        if not self.last_output:
            return
        folder = self.last_output.parent
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Could not open the folder: {exc}")


def main() -> None:
    enable_high_dpi_awareness()
    root = tk.Tk()
    ImportUtilityApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
