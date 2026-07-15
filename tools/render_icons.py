"""Design-time icon PNG generator.

Reads the official Material Design Icons SVG files from ``assets/`` and
generates anti-aliased PNG variants at multiple sizes in both white
(normal) and Social Space red (selected) colours.

Run with a Python interpreter that has Pillow and svg.path installed
(these are *build* dependencies, never needed at runtime)::

    python tools/render_icons.py

Outputs::

    src/obs_overlay_import_utility/assets/icon-<name>-<color>-<size>.png

The runtime application loads the nearest matching size according to
effective DPI and app zoom — no subsampling, no SVG parsing, no font
registration, no Pillow at runtime.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw
from svg.path import parse_path

COLORS = {
    "white": (0xF7, 0xF8, 0xFA, 255),
    "red": (0xE1, 0x26, 0x2F, 255),
}

SIZES = (32, 40, 48, 64)
SUPERSAMPLE = 8
BEZIER_STEPS = 20

ICON_NAMES = ("folder-arrow-left", "folder-arrow-right", "fit-to-screen", "cog")


def _flatten_path_to_points(
    path_str: str,
) -> list[tuple[float, float]]:
    elements = parse_path(path_str)
    points: list[tuple[float, float]] = []

    for elem in elements:
        cls = elem.__class__.__name__.lower()
        if cls == "moveto":
            p = (elem.start.real, elem.start.imag)
            if points and points[-1] != p:
                points.append(p)
            points.append(p)
        elif cls in ("lineto", "line"):
            points.append((elem.end.real, elem.end.imag))
        elif cls == "curveto":
            for i in range(1, BEZIER_STEPS + 1):
                c = elem.point(i / BEZIER_STEPS)
                points.append((c.real, c.imag))
        elif cls == "arc":
            for i in range(1, BEZIER_STEPS + 1):
                c = elem.point(i / BEZIER_STEPS)
                points.append((c.real, c.imag))
        elif cls == "close":
            points.append((elem.end.real, elem.end.imag))

    return points


def _subpath_polygons(
    flat: list[tuple[float, float]],
) -> list[list[tuple[float, float]]]:
    polys: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    prev: tuple[float, float] | None = None

    for p in flat:
        if prev is not None and p == prev and cur != [p]:
            if len(cur) >= 2:
                polys.append(cur)
            cur = []
        cur.append(p)
        prev = p

    if len(cur) >= 2:
        polys.append(cur)
    return polys


def render(name: str, svg_path: Path, target: Path, size: int, colour: tuple[int, int, int, int]) -> None:
    tree = ET.parse(svg_path)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    path_elem = tree.find(".//svg:path", ns)
    if path_elem is None:
        path_elem = tree.find(".//path")
    if path_elem is None:
        raise ValueError(f"No <path> element in {svg_path}")

    d_str = path_elem.get("d", "").strip()
    if not d_str:
        raise ValueError(f"Empty path 'd' in {svg_path}")

    flat = _flatten_path_to_points(d_str)
    polys = _subpath_polygons(flat)

    hi_size = size * SUPERSAMPLE
    margin = hi_size * 0.08
    draw_area = hi_size - 2 * margin
    scale = draw_area / 24.0

    img = Image.new("RGBA", (hi_size, hi_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for poly in polys:
        if len(poly) < 3:
            continue
        scaled = [(x * scale + margin, y * scale + margin) for x, y in poly]
        draw.polygon(scaled, fill=colour)

    if SUPERSAMPLE > 1:
        img = img.resize((size, size), Image.LANCZOS)

    img.save(target, format="PNG")


def main() -> int:
    assets = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "obs_overlay_import_utility"
        / "assets"
    )
    if not assets.is_dir():
        print(f"assets directory not found: {assets}", file=sys.stderr)
        return 1

    generated = 0
    for name in ICON_NAMES:
        svg_path = assets / f"{name}.svg"
        if not svg_path.is_file():
            print(f"WARNING: SVG not found: {svg_path}", file=sys.stderr)
            continue
        for colour_name, colour_val in COLORS.items():
            for size in SIZES:
                target = assets / f"icon-{name}-{colour_name}-{size}.png"
                render(name, svg_path, target, size, colour_val)
                generated += 1
                print(f"  {target.name} ({size}x{size})")

    print(f"\nGenerated {generated} PNG variants from {len(ICON_NAMES)} SVGs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
