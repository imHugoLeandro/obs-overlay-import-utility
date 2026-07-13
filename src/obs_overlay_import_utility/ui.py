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
        "settings": (
            "Settings",
            "Application preferences will be available here in a future release.",
        ),
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_TITLE} {__version__}")
        self.root.minsize(720, 600)
        self.root.geometry("820x700")

        self.folder_var = tk.StringVar()
        self.collection_var = tk.StringVar()
        self.strict_var = tk.BooleanVar(value=True)
        self.case_var = tk.BooleanVar(value=False)
        self.section_var = tk.StringVar(value="import")
        self.placeholder_title_var = tk.StringVar()
        self.placeholder_description_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Choose the extracted overlay folder to begin.")
        self.collections: dict[str, Path] = {}
        self.last_output: Path | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self.navigation_buttons: list[ttk.Radiobutton] = []

        self._build_interface()
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
            foreground="#555555",
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
        ttk.Label(content, text="Coming soon", foreground="#666666").grid(row=2, column=0)
        ttk.Button(
            content,
            text="Back to Import Overlay",
            command=lambda: self._select_section("import"),
        ).grid(row=3, column=0, pady=(24, 0))
        self.placeholder_page = placeholder

        self._show_section()

    def _select_section(self, section: str) -> None:
        self.section_var.set(section)
        self._show_section()

    def _show_section(self) -> None:
        section = self.section_var.get()
        self.import_page.grid_remove()
        self.placeholder_page.grid_remove()
        if section == "import":
            self.import_page.grid(row=0, column=0, sticky="nsew")
            return

        title, description = self.PLACEHOLDER_COPY.get(
            section,
            ("Coming Soon", "This tool is planned for a future release."),
        )
        self.placeholder_title_var.set(title)
        self.placeholder_description_var.set(description)
        self.placeholder_page.grid(row=0, column=0, sticky="nsew")

    def _browse(self) -> None:
        selected = filedialog.askdirectory(title="Choose the extracted overlay folder")
        if selected:
            self.folder_var.set(selected)
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
