"""Safe OBS scene collection discovery and conversion engine."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator

from .constants import GENERATED_JSON_RE, SUPPORTED_EXTENSIONS, TRACKING_FILENAME
from .models import AmbiguousMatch, ConversionResult, FileIndex, PathReference, UtilityError
from .paths import (
    find_file_match,
    is_local_media_path,
    normalized_key,
    normalized_output_path,
    portable_filename,
    portable_parent_name,
)


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UtilityError(f"Could not read {path.name}: {exc}") from exc


def is_obs_scene_collection_data(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    sources = data.get("sources")
    scene_order = data.get("scene_order")
    return isinstance(sources, list) and (
        isinstance(scene_order, list)
        or isinstance(data.get("current_scene"), str)
        or any(isinstance(source, dict) and "settings" in source for source in sources)
    )


def is_likely_obs_json(path: Path) -> bool:
    try:
        return is_obs_scene_collection_data(load_json(path))
    except UtilityError:
        return False


def should_skip_json(path: Path) -> bool:
    name = path.name
    return (
        name.casefold() == TRACKING_FILENAME.casefold()
        or bool(GENERATED_JSON_RE.search(name))
        or any(part.casefold() in {".git", ".venv", ".venv-build", "build", "dist"} for part in path.parts)
    )


def _prune_directories(current: str, directories: list[str]) -> None:
    directories[:] = [
        name
        for name in directories
        if name.casefold() not in {".git", ".venv", ".venv-build", "__pycache__", "build", "dist"}
        and not Path(current, name).is_symlink()
    ]


def find_scene_collections(root: Path) -> list[Path]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise UtilityError("Choose a valid overlay folder first.")

    collections: list[Path] = []
    try:
        for current, directories, files in os.walk(root, followlinks=False):
            _prune_directories(current, directories)
            for filename in files:
                path = Path(current, filename)
                if path.suffix.casefold() != ".json" or should_skip_json(path):
                    continue
                if is_likely_obs_json(path):
                    collections.append(path)
    except OSError as exc:
        raise UtilityError(f"Could not scan this folder: {exc}") from exc
    return sorted(collections, key=lambda path: str(path).casefold())


def build_file_index(root: Path, *, case_sensitive: bool = False) -> FileIndex:
    root = root.expanduser().resolve()
    index = FileIndex()
    try:
        for current, directories, files in os.walk(root, followlinks=False):
            _prune_directories(current, directories)
            for filename in files:
                path = Path(current, filename)
                if path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
                    continue
                resolved = str(path.resolve())
                name_key = normalized_key(filename, case_sensitive)
                folder_key = normalized_key(path.parent.name, case_sensitive)
                index.by_name.setdefault(name_key, []).append(resolved)
                index.by_folder.setdefault(folder_key, {}).setdefault(name_key, []).append(resolved)
                index.file_count += 1
    except OSError as exc:
        raise UtilityError(f"Could not index overlay files: {exc}") from exc
    return index


def iter_path_references(value: Any, *, source_name: str = "Scene collection") -> Iterator[PathReference]:
    if isinstance(value, dict):
        current_source = value.get("name") if isinstance(value.get("name"), str) else source_name
        for key, child in value.items():
            if isinstance(child, str) and is_local_media_path(child):
                yield PathReference(value, key, key, child, current_source)
            elif isinstance(child, (dict, list)):
                yield from iter_path_references(child, source_name=current_source)
    elif isinstance(value, list):
        for position, child in enumerate(value):
            if isinstance(child, str) and is_local_media_path(child):
                yield PathReference(value, position, position, child, source_name)
            elif isinstance(child, (dict, list)):
                yield from iter_path_references(child, source_name=source_name)


def path_exists_on_this_platform(value: str) -> bool:
    return Path(normalized_output_path(value)).is_file()


def next_output_path(collection_path: Path) -> Path:
    base = collection_path.with_name(f"{collection_path.stem}_ImportReady.json")
    if not base.exists():
        return base
    number = 2
    while True:
        candidate = collection_path.with_name(f"{collection_path.stem}_ImportReady_{number}.json")
        if not candidate.exists():
            return candidate
        number += 1


def atomic_write_json(path: Path, data: Any) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary_name = handle.name
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except OSError as exc:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise UtilityError(f"Could not save the converted collection: {exc}") from exc


def convert_collection(
    collection_path: Path,
    overlay_root: Path,
    *,
    strict: bool = True,
    case_sensitive: bool = False,
) -> ConversionResult:
    collection_path = collection_path.expanduser().resolve()
    overlay_root = overlay_root.expanduser().resolve()
    result = ConversionResult()

    try:
        if not collection_path.is_file():
            raise UtilityError("The selected scene collection no longer exists.")
        data = load_json(collection_path)
        if not is_obs_scene_collection_data(data):
            raise UtilityError("The selected JSON is not a recognized OBS scene collection.")

        converted = copy.deepcopy(data)
        references = list(iter_path_references(converted))
        result.candidate_paths = len(references)
        index = build_file_index(overlay_root, case_sensitive=case_sensitive)
        result.indexed_files = index.file_count

        for reference in references:
            if path_exists_on_this_platform(reference.value):
                result.unchanged += 1
                continue
            replacement, ambiguous = find_file_match(
                reference.value, index, case_sensitive=case_sensitive
            )
            if replacement:
                reference.parent[reference.key] = normalized_output_path(replacement)
                result.changed += 1
            elif ambiguous:
                result.ambiguous.append(
                    AmbiguousMatch(reference.source_name, reference.value, ambiguous)
                )
            else:
                result.missing.append(
                    f"{reference.source_name}: {portable_filename(reference.value)}"
                    + (f" (expected folder: {portable_parent_name(reference.value)})" if portable_parent_name(reference.value) else "")
                )

        if result.ambiguous or (strict and result.missing):
            return result

        output_path = next_output_path(collection_path)
        atomic_write_json(output_path, converted)
        result.output_path = output_path
        result.success = True
        return result
    except UtilityError as exc:
        result.error = str(exc)
        return result
