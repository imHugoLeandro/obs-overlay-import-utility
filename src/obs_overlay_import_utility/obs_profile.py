"""Read the active OBS profile canvas without changing OBS configuration."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ObsProfileCanvas:
    """The base canvas configured for OBS's currently selected profile."""

    width: int
    height: int
    profile_name: str


def active_profile_canvas(obs_scenes_directory: Path) -> ObsProfileCanvas | None:
    """Return the active OBS base canvas, or ``None`` when it cannot be determined."""
    scenes_directory = obs_scenes_directory.expanduser().resolve()
    config_directory = scenes_directory.parent.parent
    profiles_directory = config_directory / "basic" / "profiles"
    user_ini = config_directory / "user.ini"
    if not user_ini.is_file() or not profiles_directory.is_dir():
        return None

    user_config = configparser.RawConfigParser(interpolation=None)
    try:
        user_config.read(user_ini, encoding="utf-8")
        profile_directory_name = user_config.get("Basic", "ProfileDir", fallback="").strip()
        profile_name = user_config.get("Basic", "Profile", fallback=profile_directory_name).strip()
    except (configparser.Error, OSError, UnicodeError):
        return None
    if not profile_directory_name:
        profile_directory_name = profile_name
    if not profile_directory_name:
        return None

    profile_directory = (profiles_directory / profile_directory_name).resolve()
    try:
        profile_directory.relative_to(profiles_directory.resolve())
    except ValueError:
        return None
    basic_ini = profile_directory / "basic.ini"
    if not basic_ini.is_file():
        return None

    profile_config = configparser.RawConfigParser(interpolation=None)
    try:
        profile_config.read(basic_ini, encoding="utf-8")
        width = profile_config.getint("Video", "BaseCX")
        height = profile_config.getint("Video", "BaseCY")
    except (configparser.Error, OSError, UnicodeError, ValueError):
        return None
    if not (16 <= width <= 32_768 and 16 <= height <= 32_768):
        return None
    return ObsProfileCanvas(width=width, height=height, profile_name=profile_name or profile_directory_name)
