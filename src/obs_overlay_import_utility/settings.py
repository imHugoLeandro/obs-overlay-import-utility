"""Persistent per-user settings for the desktop utility."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


SETTINGS_FOLDER = "OBS Overlay Import Utility"
SETTINGS_FILENAME = "settings.json"
THEMES = frozenset({"system", "light", "dark"})
MIN_UI_SCALE = 75
MAX_UI_SCALE = 150


@dataclass
class AppSettings:
    schema_version: int = 1
    theme: str = "system"
    ui_scale: int = 100
    use_custom_python: bool = False
    python_path: str = ""
    use_custom_obs: bool = False
    obs_path: str = ""
    remember_last_folder: bool = True
    last_overlay_folder: str = ""
    open_output_after_conversion: bool = False
    strict_validation: bool = True
    case_sensitive_matching: bool = True

    @classmethod
    def from_dict(cls, value: Any) -> "AppSettings":
        if not isinstance(value, dict):
            return cls()
        allowed = {field.name for field in fields(cls)}
        clean = {key: item for key, item in value.items() if key in allowed}
        try:
            settings = cls(**clean)
        except TypeError:
            return cls()

        if settings.theme not in THEMES:
            settings.theme = "system"
        try:
            settings.ui_scale = max(
                MIN_UI_SCALE,
                min(MAX_UI_SCALE, int(settings.ui_scale)),
            )
        except (TypeError, ValueError):
            settings.ui_scale = 100

        for name in (
            "use_custom_python",
            "use_custom_obs",
            "remember_last_folder",
            "open_output_after_conversion",
            "strict_validation",
            "case_sensitive_matching",
        ):
            setattr(settings, name, bool(getattr(settings, name)))
        for name in ("python_path", "obs_path", "last_overlay_folder"):
            value = getattr(settings, name)
            setattr(settings, name, value if isinstance(value, str) else "")
        settings.schema_version = 1
        return settings


def default_settings_directory() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / SETTINGS_FOLDER


class SettingsStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or default_settings_directory()
        self.path = self.directory / SETTINGS_FILENAME
        self.last_error: str | None = None

    def load(self) -> AppSettings:
        self.last_error = None
        if not self.path.exists():
            return AppSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            return AppSettings.from_dict(data)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            self.last_error = f"Could not read saved settings: {exc}"
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.last_error = None
        temporary_name: str | None = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=self.directory,
                prefix=f".{SETTINGS_FILENAME}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_name = handle.name
                json.dump(asdict(settings), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        except OSError as exc:
            if temporary_name:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass
            self.last_error = f"Could not save settings: {exc}"
            raise


def detect_default_obs_path() -> Path | None:
    candidates: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "obs-studio" / "bin" / "64bit" / "obs64.exe")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "obs-studio" / "bin" / "64bit" / "obs64.exe")
    return next((path for path in candidates if path.is_file()), None)
