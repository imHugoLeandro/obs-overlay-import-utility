"""Data models returned by the conversion engine."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class UtilityError(Exception):
    """A validation or conversion problem safe to display to the customer."""


@dataclass(frozen=True)
class PathReference:
    parent: Any
    key: Any
    detection_key: Any
    value: str
    source_name: str


@dataclass(frozen=True)
class AmbiguousMatch:
    source_name: str
    original_path: str
    candidates: tuple[str, ...]


@dataclass
class ConversionResult:
    success: bool = False
    output_path: Path | None = None
    changed: int = 0
    unchanged: int = 0
    missing: list[str] = field(default_factory=list)
    ambiguous: list[AmbiguousMatch] = field(default_factory=list)
    indexed_files: int = 0
    candidate_paths: int = 0
    error: str | None = None


@dataclass
class FileIndex:
    by_name: dict[str, list[str]] = field(default_factory=dict)
    by_folder: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    file_count: int = 0
