"""PyInstaller entry point for the bundled desktop backend.

This script is used ONLY for packaging the Python backend as a standalone
executable. It is never used as the Electron application entry point —
the Electron app launches this compiled backend as a subprocess via
stdio JSON-lines.

When running from source, use:
    python -m obs_overlay_import_utility.desktop_backend

This entry point exists solely for PyInstaller to bundle the backend
without the Tk UI (ui.py) and its tkinter dependency.
"""

from obs_overlay_import_utility.desktop_backend import run

if __name__ == "__main__":
    raise SystemExit(run())
