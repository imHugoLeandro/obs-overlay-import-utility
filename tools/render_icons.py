"""Design-time icon PNG generator.

Reads the official Material Design Icons SVG files from ``assets/`` and
generates anti-aliased PNG variants at multiple sizes in both white
(normal) and Social Space red (selected) colours.

Uses a scanline-based nonzero-fill renderer built on Pillow with
supersampled anti-aliasing.  Avoids Cairo, polygon-fill shortcuts,
and manual path-flattening subpath detection hacks.

Run with a Python interpreter that has Pillow and svg.path installed
(these are *build* dependencies, never needed at runtime)::

    python tools/render_icons.py
    python tools/render_icons.py --check

Outputs::

    src/obs_overlay_import_utility/assets/icon-<name>-<color>-<size>.png

The runtime application loads the nearest matching size according to
effective DPI and app zoom --- no subsampling, no SVG parsing, no font
registration, no Pillow at runtime.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image
from svg.path import (
    Arc,
    Close,
    CubicBezier,
    Line,
    Move,
    QuadraticBezier,
    parse_path,
)

COLORS: dict[str, tuple[int, int, int, int]] = {
    "white": (0xF7, 0xF8, 0xFA, 255),
    "red": (0xE1, 0x26, 0x2F, 255),
}

SIZES: tuple[int, ...] = (32, 40, 48, 64)
SUPERSAMPLE: int = 8
BEZIER_STEPS: int = 30

ICON_NAMES: tuple[str, ...] = (
    "folder-arrow-left",
    "folder-arrow-right",
    "fit-to-screen",
    "cog",
)


def _parse_subpaths(d_str: str) -> list[list[tuple[float, float]]]:
    path = parse_path(d_str)
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for seg in path:
        if isinstance(seg, Move):
            if current:
                subpaths.append(current)
            current = [(seg.start.real, seg.start.imag)]
        elif isinstance(seg, (Line, Close)):
            current.append((seg.end.real, seg.end.imag))
        elif isinstance(seg, (CubicBezier, QuadraticBezier, Arc)):
            for i in range(1, BEZIER_STEPS + 1):
                p = seg.point(i / BEZIER_STEPS)
                current.append((p.real, p.imag))
    if current:
        subpaths.append(current)
    return subpaths


def _nonzero_fill_mask(
    subpaths: list[list[tuple[float, float]]],
    hi_size: int,
    scale: float,
    margin: float,
) -> np.ndarray:
    """Return a ``(hi_size, hi_size)`` uint8 mask using the nonzero fill rule."""
    scaled: list[list[tuple[float, float]]] = []
    for sp in subpaths:
        pts = [(x * scale + margin, y * scale + margin) for x, y in sp]
        scaled.append(pts)

    edges: list[tuple[float, float, float, float, int]] = []
    for sp in scaled:
        for i in range(len(sp) - 1):
            x1, y1 = sp[i]
            x2, y2 = sp[i + 1]
            if abs(y2 - y1) < 0.001:  # horizontal --- skip
                continue
            edges.append((x1, y1, x2, y2, 1 if y2 > y1 else -1))

    mask = np.zeros((hi_size, hi_size), dtype=np.uint8)
    for y in range(hi_size):
        y_scan = y + 0.5
        crossings: list[tuple[float, int]] = []
        for x1, y1, x2, y2, wsign in edges:
            if (y1 <= y_scan < y2) or (y2 <= y_scan < y1):
                t = (y_scan - y1) / (y2 - y1)
                x = x1 + t * (x2 - x1)
                crossings.append((x, wsign))
        crossings.sort(key=lambda c: c[0])

        winding = 0
        span_start: int | None = None
        for x, w in crossings:
            prev = winding
            winding += w
            if prev == 0 and winding != 0:
                span_start = int(np.clip(x, 0, hi_size))
            elif prev != 0 and winding == 0:
                span_end = int(np.clip(x, 0, hi_size))
                if span_start is not None and span_start < span_end:
                    mask[y, span_start:span_end] = 255
                span_start = None
        if span_start is not None:
            span_end = hi_size
            if span_start < span_end:
                mask[y, span_start:span_end] = 255

    return mask


def _render_to_png(
    svg_path: Path,
    size: int,
    colour: tuple[int, int, int, int],
    output: Path,
) -> None:
    tree = ET.parse(str(svg_path))
    path_elem = tree.find(".//{http://www.w3.org/2000/svg}path")
    if path_elem is None:
        raise ValueError(f"No <path> in {svg_path}")
    d_str = path_elem.get("d", "").strip()
    if not d_str:
        raise ValueError(f"Empty path 'd' in {svg_path}")

    subpaths = _parse_subpaths(d_str)

    hi_size = size * SUPERSAMPLE
    margin = hi_size * 0.08
    draw_area = hi_size - 2 * margin
    scale = draw_area / 24.0

    mask = _nonzero_fill_mask(subpaths, hi_size, scale, margin)

    img_arr = np.zeros((hi_size, hi_size, 4), dtype=np.uint8)
    img_arr[mask == 255] = colour
    img = Image.fromarray(img_arr)
    if SUPERSAMPLE > 1:
        img = img.resize((size, size), Image.LANCZOS)
    img.save(output, format="PNG")


def _pngs_match(path_a: Path, path_b: Path) -> bool:
    a = np.array(Image.open(str(path_a)))
    b = np.array(Image.open(str(path_b)))
    return bool(np.array_equal(a, b))


def _asset_dir() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "src"
        / "obs_overlay_import_utility"
        / "assets"
    )


def cmd_render(assets: Path, quiet: bool = False) -> int:
    generated = 0
    for name in ICON_NAMES:
        svg_path = assets / f"{name}.svg"
        if not svg_path.is_file():
            print(f"WARNING: SVG not found: {svg_path}", file=sys.stderr)
            continue
        for colour_name, colour_val in COLORS.items():
            for size in SIZES:
                target = assets / f"icon-{name}-{colour_name}-{size}.png"
                _render_to_png(svg_path, size, colour_val, target)
                generated += 1
                if not quiet:
                    print(f"  {target.name} ({size}x{size}")

    if not quiet:
        print(f"\nGenerated {generated} PNG variants from {len(ICON_NAMES)} SVGs")
    return 0


def cmd_check(assets: Path) -> int:
    errors = 0
    with tempfile.TemporaryDirectory(prefix="render_icons_check_") as tmp:
        tmp_dir = Path(tmp)
        for name in ICON_NAMES:
            svg_path = assets / f"{name}.svg"
            if not svg_path.is_file():
                print(f"ERROR: missing SVG {svg_path}", file=sys.stderr)
                errors += 1
                continue
            for colour_name, colour_val in COLORS.items():
                for size in SIZES:
                    committed = assets / f"icon-{name}-{colour_name}-{size}.png"
                    rendered = tmp_dir / f"icon-{name}-{colour_name}-{size}.png"
                    _render_to_png(svg_path, size, colour_val, rendered)
                    if not committed.is_file():
                        print(f"  MISSING {committed.name}", file=sys.stderr)
                        errors += 1
                    elif not _pngs_match(committed, rendered):
                        print(f"  STALE  {committed.name}", file=sys.stderr)
                        errors += 1
                    else:
                        print(f"  OK     {committed.name}")

    if errors:
        print(f"\n{errors} asset(s) do not match. Run: python tools/render_icons.py")
    else:
        print("\nAll committed assets are current.")
    return 0 if errors == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate icon PNGs from SVGs")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify committed PNGs match freshly rendered output",
    )
    args = parser.parse_args()

    assets = _asset_dir()
    if not assets.is_dir():
        print(f"assets directory not found: {assets}", file=sys.stderr)
        return 1

    if args.check:
        return cmd_check(assets)
    return cmd_render(assets)


if __name__ == "__main__":
    raise SystemExit(main())
