"""Tkinter interface for customers importing OBS overlay packages."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .constants import APP_TITLE, __version__
from .core import convert_collection, find_scene_collections
from .models import ConversionResult, UtilityError
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
        self.strict_var = tk.BooleanVar(value=self.settings.strict_validation)
        self.case_var = tk.BooleanVar(value=self.settings.case_sensitive_matching)
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
        self.last_output: Path | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.navigation_buttons: list[ttk.Radiobutton] = []
        self.logo_source: tk.PhotoImage | None = None
        self.logo_image: tk.PhotoImage | None = None

        self._apply_ui_scale(self.settings.ui_scale, resize_window=True)
        self._apply_theme()
        self._build_interface()
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
            self.logo_image = self.logo_source.subsample(2, 2)
            ttk.Label(navigation, image=self.logo_image).grid(
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
        frame.rowconfigure(8, weight=1)
        self.import_page = frame

        ttk.Label(frame, text=APP_TITLE, font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            frame,
            text="Create a safe, import-ready OBS scene collection using the files on this computer.",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(4, 18))

        folder_group = ttk.LabelFrame(frame, text="1. Overlay folder", padding=12)
        folder_group.grid(row=2, column=0, sticky="ew")
        folder_group.columnconfigure(0, weight=1)
        self.folder_entry = ttk.Entry(folder_group, textvariable=self.folder_var)
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.browse_button = ttk.Button(folder_group, text="Browse…", command=self._browse)
        self.browse_button.grid(row=0, column=1)
        self.scan_button = ttk.Button(folder_group, text="Scan", command=self._scan)
        self.scan_button.grid(row=0, column=2, padx=(8, 0))

        collection_group = ttk.LabelFrame(frame, text="2. OBS scene collection", padding=12)
        collection_group.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        collection_group.columnconfigure(0, weight=1)
        self.collection_combo = ttk.Combobox(
            collection_group, textvariable=self.collection_var, state="readonly"
        )
        self.collection_combo.grid(row=0, column=0, sticky="ew")

        options_group = ttk.LabelFrame(frame, text="Options", padding=12)
        options_group.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.strict_check = ttk.Checkbutton(
            options_group,
            text="Require every referenced file (recommended)",
            variable=self.strict_var,
        )
        self.strict_check.grid(row=0, column=0, sticky="w")
        self.case_check = ttk.Checkbutton(
            options_group,
            text="Case-sensitive filename matching",
            variable=self.case_var,
        )
        self.case_check.grid(row=1, column=0, sticky="w", pady=(5, 0))

        button_row = ttk.Frame(frame)
        button_row.grid(row=5, column=0, sticky="ew", pady=(16, 0))
        button_row.columnconfigure(0, weight=1)
        self.convert_button = ttk.Button(
            button_row, text="Validate and create import file", command=self._convert
        )
        self.convert_button.grid(row=0, column=0, sticky="ew")
        self.open_button = ttk.Button(
            button_row, text="Open output folder", command=self._open_output, state="disabled"
        )
        self.open_button.grid(row=0, column=1, padx=(10, 0))

        ttk.Separator(frame).grid(row=6, column=0, sticky="ew", pady=16)
        ttk.Label(frame, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).grid(
            row=7, column=0, sticky="w"
        )
        self.results = tk.Text(frame, height=14, wrap="word", state="disabled")
        self.results.grid(row=8, column=0, sticky="nsew", pady=(8, 0))
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.results.yview)
        scrollbar.grid(row=8, column=1, sticky="ns", pady=(8, 0))
        self.results.configure(yscrollcommand=scrollbar.set)
        ttk.Label(
            frame,
            text="Your original collection is never changed. A new _ImportReady.json file is created.",
            style="Muted.TLabel",
        ).grid(row=9, column=0, sticky="w", pady=(12, 0))

        placeholder = ttk.Frame(self.page_container, padding=40)
        placeholder.columnconfigure(0, weight=1)
        placeholder.rowconfigure(0, weight=1)
        content = ttk.Frame(placeholder)
        content.grid(row=0, column=0)
        ttk.Label(
            content,
            textvariable=self.placeholder_title_var,
            font=("Segoe UI", 22, "bold"),
            anchor="center",
        ).grid(row=0, column=0)
        ttk.Label(
            content,
            textvariable=self.placeholder_description_var,
            justify="center",
            anchor="center",
            wraplength=520,
        ).grid(row=1, column=0, pady=(12, 22))
        ttk.Label(content, text="Coming soon", style="Muted.TLabel").grid(row=2, column=0)
        ttk.Button(
            content,
            text="Back to Import Overlay",
            command=lambda: self._select_section("import"),
        ).grid(row=3, column=0, pady=(24, 0))
        self.placeholder_page = placeholder

        self._build_settings_page()

        self._show_section()

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
        self.placeholder_page.grid_remove()
        self.settings_page.grid_remove()
        if section == "import":
            self.import_page.grid(row=0, column=0, sticky="nsew")
            return
        if section == "settings":
            self.settings_page.grid(row=0, column=0, sticky="nsew")
            return

        title, description = self.PLACEHOLDER_COPY.get(
            section,
            ("Coming Soon", "This tool is planned for a future release."),
        )
        self.placeholder_title_var.set(title)
        self.placeholder_description_var.set(description)
        self.placeholder_page.grid(row=0, column=0, sticky="nsew")

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
        else:
            style.theme_use("clam")
            if theme == "dark":
                background = "#1e1e1e"
                surface = "#292929"
                foreground = "#f2f2f2"
                muted = "#b5b5b5"
                field = "#353535"
                selection = "#f42425"
            else:
                background = "#f5f5f5"
                surface = "#ffffff"
                foreground = "#171717"
                muted = "#5f5f5f"
                field = "#ffffff"
                selection = "#d91f20"
            text_background = field
            text_foreground = foreground
            style.configure(".", background=background, foreground=foreground)
            style.configure("TFrame", background=background)
            style.configure("TLabel", background=background, foreground=foreground)
            style.configure("TLabelframe", background=background, foreground=foreground)
            style.configure(
                "TLabelframe.Label", background=background, foreground=foreground
            )
            style.configure("TButton", background=surface, foreground=foreground)
            style.map(
                "TButton",
                background=[("active", selection)],
                foreground=[("active", "#ffffff")],
            )
            style.configure("TCheckbutton", background=background, foreground=foreground)
            style.map("TCheckbutton", background=[("active", background)])
            style.configure(
                "TEntry",
                fieldbackground=field,
                foreground=foreground,
                insertcolor=foreground,
            )
            style.configure(
                "TCombobox",
                fieldbackground=field,
                background=surface,
                foreground=foreground,
                arrowcolor=foreground,
            )
            style.map(
                "TCombobox",
                fieldbackground=[("readonly", field), ("disabled", surface)],
                foreground=[("readonly", foreground), ("disabled", muted)],
            )
            style.configure("Horizontal.TScale", background=background)
            style.configure("Toolbutton", background=surface, foreground=foreground)
            style.map(
                "Toolbutton",
                background=[("selected", selection), ("active", selection)],
                foreground=[("selected", "#ffffff"), ("active", "#ffffff")],
            )

        style.configure("Muted.TLabel", foreground=muted)
        self.root.configure(background=background)
        if hasattr(self, "results"):
            self.results.configure(
                background=text_background,
                foreground=text_foreground,
                insertbackground=text_foreground,
                selectbackground=selection,
                selectforeground="#ffffff",
            )

    def _on_scale_changed(self, value: str) -> None:
        self._apply_ui_scale(float(value), resize_window=True)

    def _set_scale(self, value: int) -> None:
        self.ui_scale_var.set(value)
        self._apply_ui_scale(value, resize_window=True)

    def _apply_ui_scale(self, value: float, *, resize_window: bool) -> None:
        percent = int(round(float(value) / 5.0) * 5)
        percent = max(MIN_UI_SCALE, min(MAX_UI_SCALE, percent))
        self.ui_scale_label_var.set(f"{percent}%")
        if round(self.ui_scale_var.get()) != percent:
            self.ui_scale_var.set(percent)
        factor = percent / 100.0
        self.root.tk.call("tk", "scaling", self.default_tk_scaling * factor)
        self.root.minsize(round(720 * factor), round(600 * factor))
        if resize_window:
            self.root.geometry(f"{round(820 * factor)}x{round(700 * factor)}")

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

    def _scan(self) -> None:
        if self.busy:
            return
        folder = Path(self.folder_var.get().strip())
        if not folder.is_dir():
            messagebox.showerror(APP_TITLE, "Choose a valid overlay folder.")
            return
        self.last_output = None
        self.open_button.configure(state="disabled")
        self._set_busy(True, "Scanning for OBS scene collections…")
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
        if collection is None:
            messagebox.showerror(APP_TITLE, "Select a detected OBS scene collection.")
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
        self.collection_combo.configure(values=labels)
        self.collection_var.set(labels[0] if labels else "")
        if labels:
            self._write_results("Detected:\n" + "\n".join(f"• {label}" for label in labels))
            self._set_busy(False, f"Found {len(labels)} valid OBS scene collection(s).")
        else:
            self._write_results(
                "No valid OBS scene collection was found. Make sure the downloaded package was fully extracted."
            )
            self._set_busy(False, "No OBS scene collections found.")

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
            self.open_button.configure(state="normal")
            lines.extend(("", f"Created: {result.output_path}"))
            self._set_busy(False, "Import-ready collection created successfully.")
            messagebox.showinfo(
                APP_TITLE,
                "The import-ready collection was created.\n\nIn OBS, use Scene Collection → Import.",
            )
            if self.open_output_var.get():
                self._open_output()
        else:
            self._set_busy(False, "No file was written. Resolve the items below and try again.")
        self._write_results("\n".join(lines))

    def _set_busy(self, busy: bool, status: str) -> None:
        self.busy = busy
        self.status_var.set(status)
        state = "disabled" if busy else "normal"
        self.folder_entry.configure(state=state)
        self.browse_button.configure(state=state)
        self.scan_button.configure(state=state)
        self.strict_check.configure(state=state)
        self.case_check.configure(state=state)
        self.convert_button.configure(state=state)
        self.collection_combo.configure(state="disabled" if busy else "readonly")
        for button in self.navigation_buttons:
            button.configure(state="disabled" if busy else "normal")
        if busy:
            self.open_button.configure(state="disabled")
        elif self.last_output:
            self.open_button.configure(state="normal")

    def _write_results(self, text: str) -> None:
        self.results.configure(state="normal")
        self.results.delete("1.0", "end")
        self.results.insert("1.0", text)
        self.results.configure(state="disabled")

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
