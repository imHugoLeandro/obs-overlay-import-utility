"""Cross-platform path detection and matching helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .constants import (
    PLUGIN_FILE_EXTENSIONS,
    REMOTE_PREFIXES,
    SUPPORTED_EXTENSIONS,
)
from .models import FileIndex


def portable_parts(value: str) -> tuple[str, ...]:
    """Split either Windows or POSIX paths, regardless of the current OS."""
    return tuple(part for part in re.split(r"[\\/]+", value.strip()) if part)


def portable_filename(value: str) -> str:
    parts = portable_parts(value)
    return parts[-1] if parts else ""


def portable_parent_name(value: str) -> str:
    parts = portable_parts(value)
    return parts[-2] if len(parts) > 1 else ""


def normalized_output_path(value: str) -> str:
    """Use the platform-native separator for paths written into the new JSON."""
    return os.path.normpath(value)


def normalized_key(value: str, case_sensitive: bool = False) -> str:
    value = value.strip()
    return value if case_sensitive else value.casefold()


def has_supported_extension(
    value: str, *, include_plugin_files: bool = False
) -> bool:
    suffixes = (
        SUPPORTED_EXTENSIONS | PLUGIN_FILE_EXTENSIONS
        if include_plugin_files
        else SUPPORTED_EXTENSIONS
    )
    return Path(portable_filename(value)).suffix.casefold() in suffixes


def is_remote_value(value: str) -> bool:
    lowered = value.strip().casefold()
    if lowered.startswith(REMOTE_PREFIXES):
        return True
    # Treat URI schemes as remote/opaque, while preserving Windows drive letters.
    return bool(re.match(r"^[a-z][a-z0-9+.-]*://", lowered))


def looks_absolute_local_path(value: str) -> bool:
    value = value.strip()
    return bool(
        re.match(r"^[a-zA-Z]:[\\/]", value)
        or value.startswith("\\\\")
        or value.startswith("/")
    )


def is_local_media_path(
    value: str, *, include_plugin_files: bool = False
) -> bool:
    return bool(
        value
        and not is_remote_value(value)
        and has_supported_extension(value, include_plugin_files=include_plugin_files)
        and looks_absolute_local_path(value)
    )


def trailing_folder_score(
    original: str, candidate: str, *, case_sensitive: bool = False
) -> int:
    """Count matching folders from the filename backwards."""
    normalize = (lambda part: part) if case_sensitive else (lambda part: part.casefold())
    original_parts = [normalize(part) for part in portable_parts(original)[:-1]]
    candidate_parts = [normalize(part) for part in portable_parts(candidate)[:-1]]
    score = 0
    for left, right in zip(reversed(original_parts), reversed(candidate_parts)):
        if left != right:
            break
        score += 1
    return score


def find_file_match(
    original_path: str,
    index: FileIndex,
    *,
    case_sensitive: bool = False,
) -> tuple[str | None, tuple[str, ...]]:
    """Return a unique replacement or all tied candidates."""
    filename = portable_filename(original_path)
    if not filename:
        return None, ()

    key = normalized_key(filename, case_sensitive)
    candidates = list(index.by_name.get(key, ()))
    if not candidates:
        return None, ()
    if len(candidates) == 1:
        return candidates[0], ()

    parent = portable_parent_name(original_path)
    if parent:
        folder_candidates = index.by_folder.get(
            normalized_key(parent, case_sensitive), {}
        ).get(key, ())
        if len(folder_candidates) == 1:
            return folder_candidates[0], ()
        if folder_candidates:
            candidates = list(folder_candidates)

    scores = {
        candidate: trailing_folder_score(
            original_path, candidate, case_sensitive=case_sensitive
        )
        for candidate in candidates
    }
    best_score = max(scores.values(), default=0)
    if best_score:
        best = sorted(candidate for candidate, score in scores.items() if score == best_score)
        if len(best) == 1:
            return best[0], ()
        candidates = best

    return None, tuple(sorted(candidates))
