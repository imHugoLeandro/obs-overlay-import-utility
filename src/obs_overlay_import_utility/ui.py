"""Tkinter interface for customers importing OBS overlay packages."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from fractions import Fraction
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .automatic import AutomaticImportResult, automatically_import_overlay
from .constants import APP_TITLE, __version__
from .core import convert_collection, find_scene_collections, load_json
from .exporter import (
    ExportResult,
    active_obs_scene_collection,
    export_scene_collection,
    list_obs_scene_collections,
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
    source_names,
    undo_resize,
)
from .streamlabs import (
    StreamlabsImportResult,
    default_obs_scenes_directory,
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


def bundled_asset(name: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "obs_overlay_import_utility" / "assets" / name
    return Path(__file__).resolve().parent / "assets" / name


class ImportUtilityApp:
    SECTIONS = (
        ("import", "Import Overlay"),
        ("export", "Export Overlay"),
        ("resizer", "Auto Resizer"),
        ("settings", "Settings"),
    )

    PLACEHOLDER_COPY = {
        "export": (
            "Export Overlay",
            "Package an OBS overlay for customers. This tool is planned for a future release.",
        ),
        "resizer": (
            "Auto Resizer",
            "Resize overlay assets and scene layouts automatically. This tool is planned for a future release.",
        ),
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_TITLE} {__version__}")
        self.root.minsize(720, 600)
        self.root.geometry("820x700")
        self.default_tk_scaling = float(self.root.tk.call("tk", "scaling"))
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
        self.obs_advanced_visible = False
        self.pending_obs_conversion = False
        self.strict_var = tk.BooleanVar(value=self.settings.strict_validation)
        self.case_var = tk.BooleanVar(value=self.settings.case_sensitive_matching)
        self.streamlabs_file_var = tk.StringVar()
        self.automatic_folder_var = tk.StringVar(value=initial_folder)
        self.export_collection_var = tk.StringVar()
        self.export_destination_var = tk.StringVar()
        self.export_status_var = tk.StringVar(value="Choose a scene collection and destination folder.")
        self.resize_collection_var = tk.StringVar()
        self.resize_scope_var = tk.StringVar(value=SCOPE_COLLECTION)
        self.resize_name_var = tk.StringVar()
        self.resize_mode_var = tk.StringVar(value=MODE_STRETCH)
        self.resize_size_mode_var = tk.StringVar(value="screen")
        self.resize_width_var = tk.StringVar(value="1920")
        self.resize_height_var = tk.StringVar(value="1080")
        self.resize_screen_size_var = tk.StringVar(value="Screen size: checking OBS profile…")
        self.resize_status_var = tk.StringVar(value="Choose what to resize and a target size.")
        self.section_var = tk.StringVar(value="import")
        self.placeholder_title_var = tk.StringVar()
        self.placeholder_description_var = tk.StringVar()
        self.theme_var = tk.StringVar(
            value=THEME_NAMES.get(self.settings.theme, "Windows default")
        )
        self.ui_scale_var = tk.DoubleVar(value=self.settings.ui_scale)
        self.ui_scale_label_var = tk.StringVar(value=f"{self.settings.ui_scale}%")
        self.use_custom_python_var = tk.BooleanVar(value=self.settings.use_custom_python)
        self.python_path_var = tk.StringVar(value=self.settings.python_path)
        self.use_custom_obs_var = tk.BooleanVar(value=self.settings.use_custom_obs)
        self.obs_path_var = tk.StringVar(value=self.settings.obs_path)
        self.remember_folder_var = tk.BooleanVar(value=self.settings.remember_last_folder)
        self.open_output_var = tk.BooleanVar(
            value=self.settings.open_output_after_conversion
        )
        self.settings_status_var = tk.StringVar(
            value=self.settings_store.last_error or "Settings are saved for this Windows user."
        )
        self.status_var = tk.StringVar(value="Choose the extracted overlay folder to begin.")
        self.collections: dict[str, Path] = {}
        self.export_collections: dict[str, Path] = {}
        self.export_controls: list[tk.Widget] = []
        self.resize_collections: dict[str, Path] = {}
        self.resizer_controls: list[tk.Widget] = []
        self.last_resize_collection: Path | None = None
        self.last_resize_backup: Path | None = None
        self.last_output: Path | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.navigation_buttons: list[ttk.Radiobutton] = []
        self.logo_source: tk.PhotoImage | None = None
        self.logo_image: tk.PhotoImage | None = None
        self.logo_label: ttk.Label | None = None
        self.base_named_font_sizes: dict[str, int] = {}
        self.scaled_widget_fonts: list[tuple[tkfont.Font, int]] = []
        self.scaled_widget_paddings: list[tuple[tk.Widget, tuple[int, ...]]] = []

        self._apply_theme()
        self._build_interface()
        self._capture_scalable_ui()
        self._apply_ui_scale(self.settings.ui_scale)
        self._apply_theme()
        self._update_custom_path_states()
        self.root.after(100, self._process_events)

    def _build_interface(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        navigation = ttk.Frame(self.root, padding=(18, 12))
        navigation.grid(row=0, column=0, sticky="ew")
        ttk.Label(navigation, text="Tools", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, padx=(0, 12)
        )
        for column, (section, label) in enumerate(self.SECTIONS, start=1):
            button = ttk.Radiobutton(
                navigation,
                text=label,
                value=section,
                variable=self.section_var,
                command=self._show_section,
                style="Toolbutton",
                padding=(12, 7),
            )
            button.grid(row=0, column=column, padx=(0, 6))
            self.navigation_buttons.append(button)
        navigation.columnconfigure(len(self.SECTIONS) + 1, weight=1)
        logo_path = bundled_asset("social-space-logo.png")
        try:
            self.logo_source = tk.PhotoImage(file=logo_path)
            self.logo_label = ttk.Label(navigation)
            self.logo_label.grid(
                row=0,
                column=len(self.SECTIONS) + 2,
                sticky="e",
                padx=(12, 0),
            )
        except tk.TclError:
            ttk.Label(
                navigation,
                text="SOCIAL SPACE",
                font=("Segoe UI", 10, "bold"),
            ).grid(row=0, column=len(self.SECTIONS) + 2, sticky="e", padx=(12, 0))
        ttk.Separator(self.root).grid(row=0, column=0, sticky="sew")

        self.page_container = ttk.Frame(self.root)
        self.page_container.grid(row=1, column=0, sticky="nsew")
        self.page_container.columnconfigure(0, weight=1)
        self.page_container.rowconfigure(0, weight=1)

        frame = ttk.Frame(self.page_container, padding=22)
        frame.grid(sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(6, weight=1)
        self.import_page = frame

        ttk.Label(frame, text=APP_TITLE, font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            frame,
            text="Select one import method, expand its options with the arrow, then run it from this page.",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        methods = ttk.Frame(frame)
        methods.grid(row=2, column=0, sticky="ew")
        methods.columnconfigure(0, weight=1)
        self.method_controls: list[tk.Widget] = []
        self.method_options: dict[str, ttk.Frame] = {}
        self.method_arrows: dict[str, ttk.Button] = {}
        self.method_expanded = {"obs": True, "streamlabs": False, "automatic": False}

        obs_card = ttk.LabelFrame(methods, text="Method 1 — Fix Scene Collection Paths", padding=10)
        obs_card.grid(row=0, column=0, sticky="ew")
        obs_card.columnconfigure(0, weight=1)
        obs_header = ttk.Frame(obs_card)
        obs_header.grid(row=0, column=0, sticky="ew")
        obs_header.columnconfigure(0, weight=1)
        self.obs_method_radio = ttk.Radiobutton(
            obs_header,
            text="Repair an exported OBS scene collection and its local asset paths",
            value="obs",
            variable=self.import_method_var,
            command=lambda: self._select_import_method("obs"),
        )
        self.obs_method_radio.grid(row=0, column=0, sticky="w")
        self.obs_arrow = ttk.Button(obs_header, text="▾", width=3, command=lambda: self._toggle_import_method("obs"))
        self.obs_arrow.grid(row=0, column=1, sticky="e")
        self.method_arrows["obs"] = self.obs_arrow
        self.method_controls.extend((self.obs_method_radio, self.obs_arrow))
        obs_options = ttk.Frame(obs_card)
        obs_options.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        obs_options.columnconfigure(0, weight=1)
        self.method_options["obs"] = obs_options
        ttk.Label(obs_options, text="Overlay Folder path").grid(row=0, column=0, sticky="w")
        obs_folder_row = ttk.Frame(obs_options)
        obs_folder_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        obs_folder_row.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(obs_folder_row, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.browse_button = ttk.Button(obs_folder_row, text="Browse…", command=self._browse)
        self.browse_button.grid(row=0, column=1)
        self.method_controls.extend((self.folder_entry, self.browse_button))
        ttk.Label(
            obs_options,
            text="The scene collection export is found automatically inside this folder.",
            style="Muted.TLabel",
            wraplength=700,
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.advanced_obs_button = ttk.Button(
            obs_options, text="Advanced options ▸", command=self._toggle_obs_advanced
        )
        self.advanced_obs_button.grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.method_controls.append(self.advanced_obs_button)
        self.advanced_obs_options = ttk.Frame(obs_options)
        self.advanced_obs_options.columnconfigure(0, weight=1)
        self.strict_check = ttk.Checkbutton(
            self.advanced_obs_options,
            text="Require every referenced file",
            variable=self.strict_var,
        )
        self.strict_check.grid(row=0, column=0, sticky="w")
        self.case_check = ttk.Checkbutton(
            self.advanced_obs_options,
            text="Case-sensitive filename matching",
            variable=self.case_var,
        )
        self.case_check.grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.method_controls.extend((self.strict_check, self.case_check))

        streamlabs_card = ttk.LabelFrame(methods, text="Method 2 — Import Streamlabs Scene File", padding=10)
        streamlabs_card.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        streamlabs_card.columnconfigure(0, weight=1)
        streamlabs_header = ttk.Frame(streamlabs_card)
        streamlabs_header.grid(row=0, column=0, sticky="ew")
        streamlabs_header.columnconfigure(0, weight=1)
        self.streamlabs_method_radio = ttk.Radiobutton(
            streamlabs_header,
            text="Extract, convert, and import a Streamlabs package into OBS",
            value="streamlabs",
            variable=self.import_method_var,
            command=lambda: self._select_import_method("streamlabs"),
        )
        self.streamlabs_method_radio.grid(row=0, column=0, sticky="w")
        self.streamlabs_arrow = ttk.Button(
            streamlabs_header, text="▸", width=3, command=lambda: self._toggle_import_method("streamlabs")
        )
        self.streamlabs_arrow.grid(row=0, column=1, sticky="e")
        self.method_arrows["streamlabs"] = self.streamlabs_arrow
        self.method_controls.extend((self.streamlabs_method_radio, self.streamlabs_arrow))
        streamlabs_options = ttk.Frame(streamlabs_card)
        streamlabs_options.columnconfigure(0, weight=1)
        self.method_options["streamlabs"] = streamlabs_options
        streamlabs_options.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(streamlabs_options, text="Streamlabs .overlay file").grid(row=0, column=0, sticky="w")
        streamlabs_file_row = ttk.Frame(streamlabs_options)
        streamlabs_file_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        streamlabs_file_row.columnconfigure(0, weight=1)
        self.streamlabs_file_entry = ttk.Entry(streamlabs_file_row, textvariable=self.streamlabs_file_var)
        self.streamlabs_file_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.streamlabs_browse_button = ttk.Button(
            streamlabs_file_row, text="Browse…", command=self._browse_streamlabs
        )
        self.streamlabs_browse_button.grid(row=0, column=1)
        self.method_controls.extend((self.streamlabs_file_entry, self.streamlabs_browse_button))
        ttk.Label(
            streamlabs_options,
            text="Files are extracted beside the selected package and a new OBS collection is created automatically.",
            style="Muted.TLabel",
            wraplength=700,
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))

        automatic_card = ttk.LabelFrame(methods, text="Method 3 — Automatic Scene Collection", padding=10)
        automatic_card.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        automatic_card.columnconfigure(0, weight=1)
        automatic_header = ttk.Frame(automatic_card)
        automatic_header.grid(row=0, column=0, sticky="ew")
        automatic_header.columnconfigure(0, weight=1)
        self.automatic_method_radio = ttk.Radiobutton(
            automatic_header,
            text="Detect a Streamlabs package or OBS export and import it into OBS automatically",
            value="automatic",
            variable=self.import_method_var,
            command=lambda: self._select_import_method("automatic"),
        )
        self.automatic_method_radio.grid(row=0, column=0, sticky="w")
        self.automatic_arrow = ttk.Button(
            automatic_header, text="▸", width=3, command=lambda: self._toggle_import_method("automatic")
        )
        self.automatic_arrow.grid(row=0, column=1, sticky="e")
        self.method_arrows["automatic"] = self.automatic_arrow
        self.method_controls.extend((self.automatic_method_radio, self.automatic_arrow))
        automatic_options = ttk.Frame(automatic_card)
        automatic_options.columnconfigure(0, weight=1)
        self.method_options["automatic"] = automatic_options
        automatic_options.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(automatic_options, text="Scene collection pack folder").grid(row=0, column=0, sticky="w")
        automatic_folder_row = ttk.Frame(automatic_options)
        automatic_folder_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        automatic_folder_row.columnconfigure(0, weight=1)
        self.automatic_folder_entry = ttk.Entry(automatic_folder_row, textvariable=self.automatic_folder_var)
        self.automatic_folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.automatic_browse_button = ttk.Button(
            automatic_folder_row, text="Browse…", command=self._browse_automatic
        )
        self.automatic_browse_button.grid(row=0, column=1)
        self.method_controls.extend((self.automatic_folder_entry, self.automatic_browse_button))
        ttk.Label(
            automatic_options,
            text=(
                "The utility looks for exactly one .overlay package first, then one OBS scene collection export. "
                "It converts the detected pack and installs it in OBS with a new collection name."
            ),
            style="Muted.TLabel",
            wraplength=700,
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))
        run_row = ttk.Frame(frame)
        run_row.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        run_row.columnconfigure(0, weight=1)
        self.selected_method_label = ttk.Label(run_row, text="Selected: Method 1 — Fix Scene Collection Paths", style="Muted.TLabel")
        self.selected_method_label.grid(row=0, column=0, sticky="w")
        self.run_button = ttk.Button(run_row, text="Run", command=self._run_selected_method, width=18)
        self.run_button.grid(row=0, column=1, sticky="e")

        ttk.Separator(frame).grid(row=4, column=0, sticky="ew", pady=14)
        ttk.Label(frame, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).grid(
            row=5, column=0, sticky="w"
        )
        self.results = tk.Text(frame, height=12, wrap="word", state="disabled")
        self.results.grid(row=6, column=0, sticky="nsew", pady=(8, 0))
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.results.yview)
        scrollbar.grid(row=6, column=1, sticky="ns", pady=(8, 0))
        self.results.configure(yscrollcommand=scrollbar.set)
        ttk.Label(
            frame,
            text="Method 1 never changes the original export. Methods 2 and 3 never overwrite an existing OBS collection.",
            style="Muted.TLabel",
        ).grid(row=7, column=0, sticky="w", pady=(10, 0))
        self._update_import_method_panels()
        self._build_export_page()

        self._build_resizer_page()
        self._build_settings_page()

        self._show_section()

    def _build_export_page(self) -> None:
        page = ttk.Frame(self.page_container, padding=22)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(6, weight=1)
        self.export_page = page

        ttk.Label(page, text="Export Overlay", font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            page,
            text="Package an OBS scene collection with its local media, plugin resources, and filter files.",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        options = ttk.LabelFrame(page, text="Export options", padding=12)
        options.grid(row=2, column=0, sticky="ew")
        options.columnconfigure(0, weight=1)
        ttk.Label(options, text="OBS Scene Collection").grid(row=0, column=0, sticky="w")
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
        self.export_controls.extend((self.export_collection_combo, self.refresh_export_button))
        ttk.Label(
            options,
            text="The collection currently selected in OBS is chosen automatically when available.",
            style="Muted.TLabel",
            wraplength=700,
        ).grid(row=2, column=0, sticky="w", pady=(4, 12))

        ttk.Label(options, text="Export destination folder").grid(row=3, column=0, sticky="w")
        destination_row = ttk.Frame(options)
        destination_row.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        destination_row.columnconfigure(0, weight=1)
        self.export_destination_entry = ttk.Entry(destination_row, textvariable=self.export_destination_var)
        self.export_destination_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.export_destination_browse_button = ttk.Button(
            destination_row, text="Browse…", command=self._browse_export_destination
        )
        self.export_destination_browse_button.grid(row=0, column=1)
        self.export_controls.extend((self.export_destination_entry, self.export_destination_browse_button))
        ttk.Label(
            options,
            text="A new organized package folder is created here, with images, videos, audio, other resources, and an OBS JSON export.",
            style="Muted.TLabel",
            wraplength=700,
        ).grid(row=5, column=0, sticky="w", pady=(4, 0))

        run_row = ttk.Frame(page)
        run_row.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        run_row.columnconfigure(0, weight=1)
        ttk.Label(run_row, textvariable=self.export_status_var, style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.export_run_button = ttk.Button(run_row, text="Run", command=self._export_overlay, width=18)
        self.export_run_button.grid(row=0, column=1, sticky="e")
        self.export_controls.append(self.export_run_button)

        ttk.Separator(page).grid(row=4, column=0, sticky="ew", pady=14)
        ttk.Label(page, text="Export log", font=("Segoe UI", 10, "bold")).grid(row=5, column=0, sticky="w")
        self.export_results = tk.Text(page, height=14, wrap="word", state="disabled")
        self.export_results.grid(row=6, column=0, sticky="nsew", pady=(8, 0))
        scrollbar = ttk.Scrollbar(page, orient="vertical", command=self.export_results.yview)
        scrollbar.grid(row=6, column=1, sticky="ns", pady=(8, 0))
        self.export_results.configure(yscrollcommand=scrollbar.set)
        self._refresh_export_collections()
    def _build_resizer_page(self) -> None:
        page = ttk.Frame(self.page_container, padding=22)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(6, weight=1)
        self.resizer_page = page

        ttk.Label(page, text="Auto Resizer", font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            page,
            text="Resize an entire collection, one scene, or one source. The selected OBS collection is overwritten with an undo backup.",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        options = ttk.LabelFrame(page, text="Resize options", padding=12)
        options.grid(row=2, column=0, sticky="ew")
        options.columnconfigure(0, weight=1)
        options.columnconfigure(1, weight=1)

        ttk.Label(options, text="OBS Scene Collection").grid(row=0, column=0, sticky="w")
        collection_row = ttk.Frame(options)
        collection_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 10))
        collection_row.columnconfigure(0, weight=1)
        self.resize_collection_combo = ttk.Combobox(
            collection_row, textvariable=self.resize_collection_var, state="readonly"
        )
        self.resize_collection_combo.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.resize_collection_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_resize_targets())
        self.refresh_resize_button = ttk.Button(
            collection_row, text="Refresh", command=self._refresh_resize_collections
        )
        self.refresh_resize_button.grid(row=0, column=1)
        self.resizer_controls.extend((self.resize_collection_combo, self.refresh_resize_button))

        ttk.Label(options, text="Resize").grid(row=2, column=0, sticky="w")
        self.resize_scope_combo = ttk.Combobox(
            options,
            textvariable=self.resize_scope_var,
            values=(SCOPE_COLLECTION, SCOPE_SCENE, SCOPE_SOURCE),
            state="readonly",
        )
        self.resize_scope_combo.grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=(4, 10))
        self.resize_scope_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_resize_targets())
        self.resizer_controls.append(self.resize_scope_combo)

        ttk.Label(options, text="Selected scene or source").grid(row=2, column=1, sticky="w")
        self.resize_name_combo = ttk.Combobox(options, textvariable=self.resize_name_var, state="disabled")
        self.resize_name_combo.grid(row=3, column=1, sticky="ew", pady=(4, 10))
        self.resizer_controls.append(self.resize_name_combo)

        ttk.Label(options, text="Resize behavior").grid(row=4, column=0, sticky="w")
        behavior_row = ttk.Frame(options)
        behavior_row.grid(row=5, column=0, sticky="w", pady=(4, 10))
        self.stretch_radio = ttk.Radiobutton(
            behavior_row, text="Stretch", value=MODE_STRETCH, variable=self.resize_mode_var
        )
        self.stretch_radio.grid(row=0, column=0, sticky="w")
        self.scale_ratio_radio = ttk.Radiobutton(
            behavior_row, text="Scale Ratio", value=MODE_SCALE_RATIO, variable=self.resize_mode_var
        )
        self.scale_ratio_radio.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.resizer_controls.extend((self.stretch_radio, self.scale_ratio_radio))

        ttk.Label(options, text="Target canvas").grid(row=4, column=1, sticky="w")
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

        ttk.Label(options, textvariable=self.resize_screen_size_var, style="Muted.TLabel", wraplength=330).grid(
            row=6, column=0, sticky="w"
        )
        custom_row = ttk.Frame(options)
        custom_row.grid(row=6, column=1, sticky="ew")
        ttk.Label(custom_row, text="W").grid(row=0, column=0, padx=(0, 4))
        self.resize_width_entry = ttk.Entry(custom_row, textvariable=self.resize_width_var, width=8)
        self.resize_width_entry.grid(row=0, column=1, padx=(0, 8))
        ttk.Label(custom_row, text="H").grid(row=0, column=2, padx=(0, 4))
        self.resize_height_entry = ttk.Entry(custom_row, textvariable=self.resize_height_var, width=8)
        self.resize_height_entry.grid(row=0, column=3)
        self.resizer_controls.extend((self.resize_width_entry, self.resize_height_entry))
        ttk.Label(
            options,
            text="Scale Ratio preserves aspect ratio and centers the resized layout. OBS may need to reload the collection if it is already open.",
            style="Muted.TLabel",
            wraplength=700,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        run_row = ttk.Frame(page)
        run_row.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        run_row.columnconfigure(0, weight=1)
        ttk.Label(run_row, textvariable=self.resize_status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.undo_resize_button = ttk.Button(run_row, text="Undo", command=self._undo_resize, width=12, state="disabled")
        self.undo_resize_button.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.resize_run_button = ttk.Button(run_row, text="Run", command=self._run_resize, width=18)
        self.resize_run_button.grid(row=0, column=2, sticky="e")
        self.resizer_controls.extend((self.undo_resize_button, self.resize_run_button))

        ttk.Separator(page).grid(row=4, column=0, sticky="ew", pady=14)
        ttk.Label(page, text="Resize log", font=("Segoe UI", 10, "bold")).grid(row=5, column=0, sticky="w")
        self.resize_results = tk.Text(page, height=10, wrap="word", state="disabled")
        self.resize_results.grid(row=6, column=0, sticky="nsew", pady=(8, 0))
        scrollbar = ttk.Scrollbar(page, orient="vertical", command=self.resize_results.yview)
        scrollbar.grid(row=6, column=1, sticky="ns", pady=(8, 0))
        self.resize_results.configure(yscrollcommand=scrollbar.set)
        self._refresh_resize_collections()
        self._update_resize_size_mode()
    def _build_settings_page(self) -> None:
        page = ttk.Frame(self.page_container, padding=22)
        page.columnconfigure(0, weight=1)
        self.settings_page = page

        ttk.Label(page, text="Settings", font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            page,
            text="Customize how the portable utility looks and finds local applications.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))

        appearance = ttk.LabelFrame(page, text="Appearance", padding=12)
        appearance.grid(row=2, column=0, sticky="ew")
        appearance.columnconfigure(1, weight=1)
        ttk.Label(appearance, text="Theme").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.theme_combo = ttk.Combobox(
            appearance,
            textvariable=self.theme_var,
            values=list(THEME_LABELS),
            state="readonly",
            width=22,
        )
        self.theme_combo.grid(row=0, column=1, sticky="w")
        self.theme_combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_theme())

        ttk.Label(appearance, text="UI size").grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=(12, 0)
        )
        scale_row = ttk.Frame(appearance)
        scale_row.grid(row=1, column=1, sticky="ew", pady=(12, 0))
        scale_row.columnconfigure(0, weight=1)
        self.ui_scale = ttk.Scale(
            scale_row,
            from_=MIN_UI_SCALE,
            to=MAX_UI_SCALE,
            variable=self.ui_scale_var,
            command=self._on_scale_changed,
        )
        self.ui_scale.grid(row=0, column=0, sticky="ew")
        ttk.Label(scale_row, textvariable=self.ui_scale_label_var, width=6).grid(
            row=0, column=1, padx=(10, 0)
        )
        ttk.Button(
            scale_row,
            text="Windows size (100%)",
            command=lambda: self._set_scale(100),
        ).grid(row=0, column=2, padx=(6, 0))

        paths = ttk.LabelFrame(page, text="Application paths", padding=12)
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
        self.python_path_entry = ttk.Entry(python_row, textvariable=self.python_path_var)
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
        self.obs_browse_button = ttk.Button(obs_row, text="Browse…", command=self._browse_obs)
        self.obs_browse_button.grid(row=0, column=1)

        behavior = ttk.LabelFrame(page, text="Import behavior", padding=12)
        behavior.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Checkbutton(
            behavior,
            text="Remember the last overlay folder",
            variable=self.remember_folder_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            behavior,
            text="Require every referenced file by default",
            variable=self.strict_var,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Checkbutton(
            behavior,
            text="Use case-sensitive filename matching by default",
            variable=self.case_var,
        ).grid(row=2, column=0, sticky="w", pady=(5, 0))
        ttk.Checkbutton(
            behavior,
            text="Open the output folder after a successful conversion",
            variable=self.open_output_var,
        ).grid(row=3, column=0, sticky="w", pady=(5, 0))

        actions = ttk.Frame(page)
        actions.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        ttk.Button(actions, text="Save settings", command=self._save_settings).grid(
            row=0, column=0
        )
        ttk.Button(actions, text="Restore defaults", command=self._restore_defaults).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Label(actions, textvariable=self.settings_status_var, style="Muted.TLabel").grid(
            row=0, column=2, sticky="w", padx=(14, 0)
        )

    def _select_section(self, section: str) -> None:
        self.section_var.set(section)
        self._show_section()

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

    def _apply_theme(self) -> None:
        theme = THEME_LABELS.get(self.theme_var.get(), "system")
        style = ttk.Style(self.root)

        if theme == "system":
            preferred = "vista" if sys.platform.startswith("win") else style.theme_names()[0]
            try:
                style.theme_use(preferred)
            except tk.TclError:
                pass
            background = style.lookup("TFrame", "background") or "SystemButtonFace"
            foreground = style.lookup("TLabel", "foreground") or "SystemWindowText"
            muted = "#666666"
            text_background = "SystemWindow" if sys.platform.startswith("win") else "#ffffff"
            text_foreground = "SystemWindowText" if sys.platform.startswith("win") else "#111111"
            selection = "SystemHighlight" if sys.platform.startswith("win") else "#3478c7"
            self.root.option_add("*TCombobox*Listbox.background", text_background)
            self.root.option_add("*TCombobox*Listbox.foreground", text_foreground)
            self.root.option_add("*TCombobox*Listbox.selectBackground", selection)
        else:
            style.theme_use("clam")
            if theme == "dark":
                background = "#151515"
                surface = "#252525"
                foreground = "#f7f7f7"
                muted = "#c2c2c2"
                field = "#202020"
                selection = "#f42425"
                accent_hover = "#ff4b4c"
                border = "#713335"
                trough = "#3b181a"
                disabled = "#343434"
            else:
                background = "#f5f5f5"
                surface = "#ffffff"
                foreground = "#171717"
                muted = "#5f5f5f"
                field = "#ffffff"
                selection = "#d91f20"
                accent_hover = "#f42425"
                border = "#c7c7c7"
                trough = "#f5caca"
                disabled = "#e5e5e5"
            text_background = field
            text_foreground = foreground
            style.configure(".", background=background, foreground=foreground)
            style.configure("TFrame", background=background)
            style.configure("TLabel", background=background, foreground=foreground)
            style.configure(
                "TLabelframe",
                background=background,
                foreground=foreground,
                bordercolor=border,
                lightcolor=border,
                darkcolor=border,
                borderwidth=1,
            )
            style.configure(
                "TLabelframe.Label", background=background, foreground=foreground
            )
            style.configure(
                "TButton",
                background=surface,
                foreground=foreground,
                bordercolor=border,
                focuscolor=selection,
                lightcolor=border,
                darkcolor=border,
            )
            style.map(
                "TButton",
                background=[("pressed", selection), ("active", accent_hover)],
                foreground=[("active", "#ffffff")],
            )
            style.configure(
                "TCheckbutton",
                background=background,
                foreground=foreground,
                indicatorcolor=field,
                bordercolor=border,
                focuscolor=selection,
            )
            style.map(
                "TCheckbutton",
                background=[("active", background)],
                indicatorcolor=[
                    ("selected", selection),
                    ("active", accent_hover),
                    ("disabled", disabled),
                ],
            )
            style.configure(
                "TEntry",
                fieldbackground=field,
                foreground=foreground,
                insertcolor=foreground,
                bordercolor=border,
                focuscolor=selection,
                lightcolor=border,
                darkcolor=border,
            )
            style.configure(
                "TCombobox",
                fieldbackground=field,
                background=surface,
                foreground=foreground,
                arrowcolor=foreground,
                bordercolor=border,
                focuscolor=selection,
                lightcolor=border,
                darkcolor=border,
            )
            style.map(
                "TCombobox",
                fieldbackground=[("readonly", field), ("disabled", disabled)],
                foreground=[("readonly", foreground), ("disabled", muted)],
                bordercolor=[("focus", selection)],
            )
            style.configure(
                "Horizontal.TScale",
                background=selection,
                troughcolor=trough,
                bordercolor=border,
                lightcolor=selection,
                darkcolor=selection,
                troughrelief="flat",
            )
            style.map(
                "Horizontal.TScale",
                background=[("active", accent_hover), ("disabled", disabled)],
                lightcolor=[("active", accent_hover)],
                darkcolor=[("active", accent_hover)],
            )
            style.configure(
                "Toolbutton",
                background=surface,
                foreground=foreground,
                bordercolor=border,
                focuscolor=selection,
            )
            style.map(
                "Toolbutton",
                background=[
                    ("selected", selection),
                    ("pressed", selection),
                    ("active", accent_hover),
                ],
                foreground=[("selected", "#ffffff"), ("active", "#ffffff")],
            )
            self.root.option_add("*TCombobox*Listbox.background", field)
            self.root.option_add("*TCombobox*Listbox.foreground", foreground)
            self.root.option_add("*TCombobox*Listbox.selectBackground", selection)

        style.configure("Muted.TLabel", foreground=muted)
        self.root.configure(background=background)
        for text_widget_name in ("results", "export_results", "resize_results"):
            text_widget = getattr(self, text_widget_name, None)
            if text_widget is not None:
                text_widget.configure(
                    background=text_background,
                    foreground=text_foreground,
                    insertbackground=text_foreground,
                    selectbackground=selection,
                    selectforeground="#ffffff",
                )

    def _capture_scalable_ui(self) -> None:
        named_fonts = set(tkfont.names(self.root))
        for name in named_fonts:
            try:
                size = int(tkfont.nametofont(name, root=self.root).cget("size"))
            except tk.TclError:
                continue
            if size:
                self.base_named_font_sizes[name] = size

        def descendants(widget: tk.Misc) -> list[tk.Misc]:
            items: list[tk.Misc] = []
            for child in widget.winfo_children():
                items.append(child)
                items.extend(descendants(child))
            return items

        for widget in descendants(self.root):
            try:
                font_value = str(widget.cget("font"))
            except tk.TclError:
                font_value = ""
            if font_value and font_value not in named_fonts:
                try:
                    font = tkfont.Font(root=self.root, font=font_value)
                    base_size = int(font.cget("size"))
                    widget.configure(font=font)
                    self.scaled_widget_fonts.append((font, base_size))
                except tk.TclError:
                    pass

            try:
                raw_padding = widget.cget("padding")
                parts = self.root.tk.splitlist(raw_padding)
                padding = tuple(int(float(part)) for part in parts)
            except (tk.TclError, TypeError, ValueError):
                padding = ()
            if padding:
                self.scaled_widget_paddings.append((widget, padding))

    def _on_scale_changed(self, value: str) -> None:
        self._apply_ui_scale(float(value))

    def _set_scale(self, value: int) -> None:
        self.ui_scale_var.set(value)
        self._apply_ui_scale(value)

    def _apply_ui_scale(self, value: float) -> None:
        percent = int(round(float(value) / 5.0) * 5)
        percent = max(MIN_UI_SCALE, min(MAX_UI_SCALE, percent))
        self.ui_scale_label_var.set(f"{percent}%")
        if round(self.ui_scale_var.get()) != percent:
            self.ui_scale_var.set(percent)
        factor = percent / 100.0
        for name, base_size in self.base_named_font_sizes.items():
            scaled_size = max(1, round(abs(base_size) * factor))
            if base_size < 0:
                scaled_size = -scaled_size
            try:
                tkfont.nametofont(name, root=self.root).configure(size=scaled_size)
            except tk.TclError:
                pass
        for font, base_size in self.scaled_widget_fonts:
            scaled_size = max(1, round(abs(base_size) * factor))
            font.configure(size=-scaled_size if base_size < 0 else scaled_size)
        for widget, padding in self.scaled_widget_paddings:
            try:
                widget.configure(
                    padding=tuple(max(0, round(item * factor)) for item in padding)
                )
            except tk.TclError:
                pass

        style = ttk.Style(self.root)
        style.configure(
            "TButton",
            padding=(max(3, round(8 * factor)), max(2, round(4 * factor))),
        )
        style.configure(
            "Horizontal.TScale",
            sliderlength=max(12, round(22 * factor)),
            sliderthickness=max(10, round(16 * factor)),
        )
        self._update_logo_scale(percent)
        self.root.update_idletasks()

    def _update_logo_scale(self, percent: int) -> None:
        if not self.logo_source or not self.logo_label:
            return
        ratio = Fraction(percent, 400).limit_denominator(16)
        self.logo_image = self.logo_source.zoom(
            ratio.numerator, ratio.numerator
        ).subsample(ratio.denominator, ratio.denominator)
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
        )
        if selected:
            self.python_path_var.set(selected)

    def _browse_obs(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose OBS executable",
            filetypes=(("OBS executable", "obs64.exe"), ("Executables", "*.exe")),
        )
        if selected:
            self.obs_path_var.set(selected)

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
            use_custom_python=self.use_custom_python_var.get(),
            python_path=self.python_path_var.get().strip(),
            use_custom_obs=self.use_custom_obs_var.get(),
            obs_path=self.obs_path_var.get().strip(),
            remember_last_folder=self.remember_folder_var.get(),
            last_overlay_folder=remembered_folder,
            open_output_after_conversion=self.open_output_var.get(),
            strict_validation=self.strict_var.get(),
            case_sensitive_matching=self.case_var.get(),
        )

    def _save_settings(self) -> bool:
        settings = self._collect_settings()
        for enabled, path_value, label in (
            (settings.use_custom_python, settings.python_path, "Python executable"),
            (settings.use_custom_obs, settings.obs_path, "OBS executable"),
        ):
            if enabled and not Path(path_value).is_file():
                messagebox.showerror(APP_TITLE, f"Choose a valid {label.lower()} file.")
                self.settings_status_var.set(f"{label} was not saved.")
                return False
        try:
            self.settings_store.save(settings)
        except OSError:
            messagebox.showerror(APP_TITLE, self.settings_store.last_error or "Settings failed.")
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
        self.strict_var.set(defaults.strict_validation)
        self.case_var.set(defaults.case_sensitive_matching)
        self._update_custom_path_states()
        self._apply_theme()
        self._set_scale(defaults.ui_scale)
        if self._save_settings():
            self.settings_status_var.set("Default settings restored.")

    def _browse(self) -> None:
        selected = filedialog.askdirectory(title="Choose the extracted overlay folder")
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
            "obs": "Method 1 — Fix Scene Collection Paths",
            "streamlabs": "Method 2 — Import Streamlabs Scene File",
            "automatic": "Method 3 — Automatic Scene Collection",
        }
        for method, options in self.method_options.items():
            if self.method_expanded[method]:
                options.grid()
            else:
                options.grid_remove()
            self.method_arrows[method].configure(text="▾" if self.method_expanded[method] else "▸")
        selected = self.import_method_var.get()
        self.selected_method_label.configure(text=f"Selected: {labels[selected]}")
        self.run_button.configure(state="disabled" if self.busy else "normal")

    def _toggle_obs_advanced(self) -> None:
        self.obs_advanced_visible = not self.obs_advanced_visible
        if self.obs_advanced_visible:
            self.advanced_obs_options.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        else:
            self.advanced_obs_options.grid_remove()
        self.advanced_obs_button.configure(
            text="Advanced options ▾" if self.obs_advanced_visible else "Advanced options ▸"
        )

    def _run_selected_method(self) -> None:
        method = self.import_method_var.get()
        if method == "obs":
            self._convert()
        elif method == "streamlabs":
            self._import_streamlabs()
        else:
            self._import_automatic()
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
            (label for label, path in self.export_collections.items() if active and path == active),
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
        selected = filedialog.askdirectory(title="Choose the overlay export destination")
        if selected:
            self.export_destination_var.set(selected)

    def _export_overlay(self) -> None:
        if self.busy:
            return
        collection = self.export_collections.get(self.export_collection_var.get())
        if collection is None or not collection.is_file():
            messagebox.showerror(APP_TITLE, "Choose a valid OBS scene collection first.")
            return
        destination = Path(self.export_destination_var.get().strip())
        if not destination.is_dir():
            messagebox.showerror(APP_TITLE, "Choose a valid export destination folder.")
            return
        self._set_busy(True, "Exporting the scene collection and its local resources…")
        self.export_status_var.set("Packaging the selected OBS collection…")
        self._write_export_results("")
        threading.Thread(
            target=self._export_worker, args=(collection, destination), daemon=True
        ).start()

    def _export_worker(self, collection: Path, destination: Path) -> None:
        self.events.put(("export", export_scene_collection(collection, destination)))
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
            (label for label, path in self.resize_collections.items() if active and path == active),
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
            self.resize_name_combo.configure(values=(), state="disabled")
            self.resize_name_var.set("")
            return
        if scope == SCOPE_COLLECTION:
            self.resize_name_combo.configure(values=(), state="disabled")
            self.resize_name_var.set("")
            return
        try:
            data = load_json(collection)
            names = scene_names(data) if scope == SCOPE_SCENE else source_names(data)
        except UtilityError:
            names = []
        self.resize_name_combo.configure(values=names, state="readonly" if names else "disabled")
        if self.resize_name_var.get() not in names:
            self.resize_name_var.set(names[0] if names else "")

    def _refresh_resize_screen_size(self) -> None:
        canvas = active_profile_canvas(self._configured_obs_scenes_directory())
        if canvas:
            self.resize_screen_size_var.set(
                f"Screen size: {canvas.width} × {canvas.height} (active OBS profile: {canvas.profile_name})"
            )
        else:
            self.resize_screen_size_var.set("Screen size unavailable; choose Custom size or configure OBS in Settings.")

    def _update_resize_size_mode(self) -> None:
        state = "normal" if self.resize_size_mode_var.get() == "custom" and not self.busy else "disabled"
        self.resize_width_entry.configure(state=state)
        self.resize_height_entry.configure(state=state)

    def _resize_target_size(self) -> tuple[int, int]:
        if self.resize_size_mode_var.get() == "screen":
            canvas = active_profile_canvas(self._configured_obs_scenes_directory())
            if not canvas:
                raise UtilityError("OBS's active profile canvas could not be read. Choose Custom size instead.")
            return canvas.width, canvas.height
        try:
            return int(self.resize_width_var.get().strip()), int(self.resize_height_var.get().strip())
        except ValueError as exc:
            raise UtilityError("Enter whole-number custom width and height values.") from exc

    def _run_resize(self) -> None:
        if self.busy:
            return
        collection = self.resize_collections.get(self.resize_collection_var.get())
        if collection is None or not collection.is_file():
            messagebox.showerror(APP_TITLE, "Choose a valid OBS scene collection first.")
            return
        scope = self.resize_scope_var.get()
        selected_name = self.resize_name_var.get().strip() or None
        if scope != SCOPE_COLLECTION and not selected_name:
            messagebox.showerror(APP_TITLE, "Choose the scene or source to resize first.")
            return
        try:
            target_width, target_height = self._resize_target_size()
        except UtilityError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self._set_busy(True, "Resizing the selected OBS collection…")
        self.resize_status_var.set("Writing the resized collection and its undo backup…")
        self._write_resize_results("")
        threading.Thread(
            target=self._resize_worker,
            args=(collection, scope, selected_name, self.resize_mode_var.get(), target_width, target_height),
            daemon=True,
        ).start()

    def _resize_worker(
        self,
        collection: Path,
        scope: str,
        selected_name: str | None,
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
                    mode=mode,
                    target_width=target_width,
                    target_height=target_height,
                ),
            )
        )

    def _undo_resize(self) -> None:
        if self.busy:
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
        self.events.put(("resize_undo", (collection, backup, undo_resize(collection, backup))))
    def _browse_streamlabs(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose a Streamlabs overlay package",
            filetypes=(("Streamlabs overlay", "*.overlay"), ("ZIP packages", "*.zip"), ("All files", "*.*")),
        )
        if selected:
            self.streamlabs_file_var.set(selected)

    def _import_streamlabs(self) -> None:
        if self.busy:
            return
        archive = Path(self.streamlabs_file_var.get().strip())
        if not archive.is_file():
            messagebox.showerror(APP_TITLE, "Choose a valid Streamlabs .overlay package.")
            return
        if self.use_custom_obs_var.get():
            configured_path = Path(self.obs_path_var.get().strip())
            if not configured_path.is_file():
                messagebox.showerror(APP_TITLE, "Choose a valid custom OBS executable in Settings first.")
                return
            executable: Path | None = configured_path
        else:
            executable = self.detected_obs_path
        self._set_busy(True, "Extracting and converting the Streamlabs package…")
        self._write_results("")
        target = default_obs_scenes_directory(executable)
        threading.Thread(target=self._streamlabs_worker, args=(archive, target), daemon=True).start()

    def _streamlabs_worker(self, archive: Path, target: Path) -> None:
        self.events.put(("streamlabs", import_streamlabs_overlay(archive, target)))

    def _browse_automatic(self) -> None:
        selected = filedialog.askdirectory(title="Choose the scene collection pack folder")
        if selected:
            self.automatic_folder_var.set(selected)

    def _import_automatic(self) -> None:
        if self.busy:
            return
        folder = Path(self.automatic_folder_var.get().strip())
        if not folder.is_dir():
            messagebox.showerror(APP_TITLE, "Choose a valid scene collection pack folder.")
            return
        if self.use_custom_obs_var.get():
            configured_path = Path(self.obs_path_var.get().strip())
            if not configured_path.is_file():
                messagebox.showerror(APP_TITLE, "Choose a valid custom OBS executable in Settings first.")
                return
            executable: Path | None = configured_path
        else:
            executable = self.detected_obs_path
        self._set_busy(True, "Detecting and importing the scene collection pack…")
        self._write_results("")
        target = default_obs_scenes_directory(executable)
        threading.Thread(
            target=self._automatic_worker,
            args=(folder, target, self.strict_var.get(), self.case_var.get()),
            daemon=True,
        ).start()

    def _automatic_worker(
        self, folder: Path, target: Path, strict: bool, case_sensitive: bool
    ) -> None:
        result = automatically_import_overlay(
            folder, target, strict=strict, case_sensitive=case_sensitive
        )
        self.events.put(("automatic", result))
    def _scan(self) -> None:
        if self.busy:
            return
        folder = Path(self.folder_var.get().strip())
        if not folder.is_dir():
            messagebox.showerror(APP_TITLE, "Choose a valid overlay folder.")
            return
        self.last_output = None
        self._set_busy(True, "Finding an OBS scene collection export…")
        threading.Thread(target=self._scan_worker, args=(folder,), daemon=True).start()

    def _scan_worker(self, folder: Path) -> None:
        try:
            self.events.put(("scan", find_scene_collections(folder)))
        except UtilityError as exc:
            self.events.put(("error", str(exc)))

    def _convert(self) -> None:
        if self.busy:
            return
        collection = self.collections.get(self.collection_var.get())
        folder = Path(self.folder_var.get().strip())
        if collection is not None and folder.is_dir() and not collection.is_relative_to(folder.resolve()):
            collection = None
        if collection is None:
            if not folder.is_dir():
                messagebox.showerror(APP_TITLE, "Choose a valid overlay folder.")
                return
            self.pending_obs_conversion = True
            self._scan()
            return
        self._set_busy(True, "Checking and matching overlay files…")
        self._write_results("")
        threading.Thread(
            target=self._convert_worker,
            args=(collection, folder, self.strict_var.get(), self.case_var.get()),
            daemon=True,
        ).start()

    def _convert_worker(
        self, collection: Path, folder: Path, strict: bool, case_sensitive: bool
    ) -> None:
        result = convert_collection(
            collection, folder, strict=strict, case_sensitive=case_sensitive
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
                elif event == "automatic":
                    self._finish_automatic(payload)  # type: ignore[arg-type]
                elif event == "export":
                    self._finish_export(payload)  # type: ignore[arg-type]
                elif event == "resize":
                    self._finish_resize(payload)  # type: ignore[arg-type]
                elif event == "resize_undo":
                    self._finish_resize_undo(payload)  # type: ignore[arg-type]
                elif event == "error":
                    self._set_busy(False, "Could not finish the operation.")
                    messagebox.showerror(APP_TITLE, str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._process_events)

    def _finish_scan(self, paths: list[Path]) -> None:
        self.collections.clear()
        root = Path(self.folder_var.get().strip())
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
            self._write_results("Automatically detected OBS export:\n" + "\n".join(f"• {label}" for label in labels))
            self._set_busy(False, f"Found {len(labels)} OBS scene collection export(s).")
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
            self._set_busy(False, "Conversion failed safely; the original was not changed.")
            return

        lines = [
            f"Referenced local files: {result.candidate_paths}",
            f"Overlay files indexed: {result.indexed_files}",
            f"Paths updated: {result.changed}",
            f"Paths already valid: {result.unchanged}",
        ]
        if result.missing:
            lines.extend(("", "Missing files:", *(f"• {item}" for item in result.missing)))
        if result.ambiguous:
            lines.extend(("", "Ambiguous matches:"))
            for problem in result.ambiguous:
                lines.append(f"• {problem.source_name}: {problem.original_path}")
                lines.extend(f"    - {candidate}" for candidate in problem.candidates)

        if result.success and result.output_path:
            self.last_output = result.output_path
            lines.extend(("", f"Created: {result.output_path}", "Import it in OBS with Scene Collection → Import."))
            self._set_busy(False, "Import-ready collection created successfully.")
            if self.open_output_var.get():
                self._open_output()
        else:
            self._set_busy(False, "No file was written. Resolve the items below and try again.")
        self._write_results("\n".join(lines))

    def _finish_resize(self, result: ResizeResult) -> None:
        if result.error:
            self._write_resize_results(result.error)
            self.resize_status_var.set("Resize failed safely; the collection was not overwritten.")
            self._set_busy(False, "Could not resize the scene collection.")
            return
        self.last_resize_collection = result.collection_path
        self.last_resize_backup = result.backup_path
        self._write_resize_results(
            "\n".join(
                (
                    f"Collection overwritten: {result.collection_path}",
                    f"Undo backup: {result.backup_path}",
                    f"Canvas: {result.source_width} × {result.source_height} → {result.target_width} × {result.target_height}",
                    f"Source items resized: {result.changed_items}",
                    "",
                    "OBS can remain open. If this collection is already active, switch collections or restart OBS to reload the updated file.",
                )
            )
        )
        self.resize_status_var.set("Resize complete. Undo is available for this operation.")
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
            f"Undo complete. Restored: {collection}\nRemoved used backup: {backup}\n\n"
            "If OBS has this collection open, switch collections or restart OBS to reload the restored file."
        )
        self.resize_status_var.set("The last resize was restored.")
        self._set_busy(False, "Resize undo completed successfully.")
        self.undo_resize_button.configure(state="disabled")
    def _finish_export(self, result: ExportResult) -> None:
        if result.error:
            self._write_export_results(result.error)
            self.export_status_var.set("Export failed safely; review the log and try again.")
            self._set_busy(False, "Could not export the scene collection.")
            return
        lines = [
            f"Package folder: {result.package_path}",
            f"OBS export JSON: {result.collection_path}",
            f"Referenced files copied: {result.copied_files}",
            f"Local file references rewritten: {result.source_references}",
            "",
            "The JSON preserves OBS, plugin-source, and filter settings. Install required OBS plugins and fonts separately on the destination computer.",
        ]
        if result.skipped_references:
            lines.extend(("", "References requiring manual review:"))
            lines.extend(f"• {item}" for item in result.skipped_references)
        self._write_export_results("\n".join(lines))
        self.export_status_var.set("Overlay package exported successfully.")
        self._set_busy(False, "Overlay package exported successfully.")
        if self.open_output_var.get() and result.package_path:
            self._open_folder(result.package_path)
    def _finish_streamlabs(self, result: StreamlabsImportResult) -> None:
        if result.error:
            self._write_results(result.error)
            self._set_busy(False, "Streamlabs import failed safely; no OBS collection was created.")
            return

        lines = [
            f"OBS collection: {result.collection_name}",
            f"Collection file: {result.collection_path}",
            f"Extracted package: {result.extraction_path}",
            f"Canvas resized to: {result.canvas_width} × {result.canvas_height}"
            + (f" (active OBS profile: {result.profile_name})" if result.profile_name else ""),
            f"Supported sources imported: {result.imported_sources}",
            "",
            "Restart OBS if it was already open, then select the new collection from Scene Collection.",
        ]
        if result.skipped_sources:
            lines.extend(("", "Sources that need manual setup:"))
            lines.extend(f"• {item}" for item in result.skipped_sources)
        self._write_results("\n".join(lines))
        self._set_busy(False, "Streamlabs package imported into OBS successfully.")

    def _finish_automatic(self, result: AutomaticImportResult) -> None:
        if result.error:
            self._write_results(result.error)
            self._set_busy(False, "Automatic scene collection import failed safely.")
            return

        lines = [
            f"Detected format: {'Streamlabs .overlay' if result.kind == 'streamlabs' else 'OBS scene collection export'}",
            f"OBS collection: {result.collection_name}",
            f"Collection file: {result.collection_path}",
        ]
        if result.extraction_path:
            lines.append(f"Extracted package: {result.extraction_path}")
        if result.canvas_width and result.canvas_height:
            profile_detail = f" (active OBS profile: {result.profile_name})" if result.profile_name else ""
            lines.append(f"Canvas resized to: {result.canvas_width} × {result.canvas_height}{profile_detail}")
        if result.conversion:
            lines.extend(
                (
                    f"Paths updated: {result.conversion.changed}",
                    f"Paths already valid: {result.conversion.unchanged}",
                )
            )
        if result.streamlabs and result.streamlabs.skipped_sources:
            lines.extend(("", "Sources that need manual setup:"))
            lines.extend(f"• {item}" for item in result.streamlabs.skipped_sources)
        lines.extend(("", "Restart OBS if it was already open, then select the new collection from Scene Collection."))
        self._write_results("\n".join(lines))
        self._set_busy(False, "Scene collection detected and imported into OBS successfully.")
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
                state="normal" if self.last_resize_collection and self.last_resize_backup else "disabled"
            )
        for button in self.navigation_buttons:
            button.configure(state=state)
        self.run_button.configure(
            state="disabled" if busy else "normal"
        )
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
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista" if sys.platform.startswith("win") else "clam")
    except tk.TclError:
        pass
    ImportUtilityApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
