"""Design-time generator for navigation icon PNGs from official MDI paths.

Run this with a Python interpreter that has Pillow and svg.path installed
(this is NOT used by the portable build, which has zero runtime dependencies)::

    python tools/render_icons.py

The SVG path data below is copied verbatim from the Pictogrammers
Material Design Icons web pages (pictogrammers.com/library/mdi/). Each icon
has a 24x24 viewBox. We render at 4x supersample then LANCZOS downscale to
256px for clean anti-aliased edges.

Output: ``src/obs_overlay_import_utility/assets/nav-<name>.png`` at
256x256 RGBA. Both app palettes use a dark sidebar with light foreground
``#F7F8FA``, so a single color covers every theme.

Re-run this script to update the bundled PNGs.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw
from svg.path import parse_path

ICON_COLOR = "#F7F8FA"
SIZE = 256
SUPERSAMPLE = 4
NAMES = ("folder-arrow-left", "folder-arrow-right", "fit-to-screen", "cog")

# Verbatim from https://pictogrammers.com/library/mdi/  (viewBox "0 0 24 24")
MDI_PATHS: dict[str, str] = {
    "folder-arrow-left": (
        "M22 8V13.81C21.12 13.3 20.1 13 19 13C15.69 13 13 15.69 13 19"
        "C13 19.34 13.04 19.67 13.09 20H4C2.9 20 2 19.11 2 18V6"
        "C2 4.89 2.89 4 4 4H10L12 6H20C21.1 6 22 6.89 22 8"
        "M18 16L15 19L18 22V20H22V18H18V16Z"
    ),
    "folder-arrow-right": (
        "M13 19C13 19.34 13.04 19.67 13.09 20H4C2.9 20 2 19.11 2 18V6"
        "C2 4.89 2.89 4 4 4H10L12 6H20C21.1 6 22 6.89 22 8V13.81"
        "C21.12 13.3 20.1 13 19 13C15.69 13 13 15.69 13 19"
        "M23 19L20 16V18H16V20H20V22L23 19Z"
    ),
    "fit-to-screen": (
        "M17 4H20C21.1 4 22 4.9 22 6V8H20V6H17V4"
        "M4 8V6H7V4H4C2.9 4 2 4.9 2 6V8H4"
        "M20 16V18H17V20H20C21.1 20 22 19.1 22 18V16H20"
        "M7 18H4V16H2V18C2 19.1 2.9 20 4 20H7V18"
        "M18 8H6V16H18V8Z"
    ),
    "cog": (
        "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5"
        "A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5"
        "M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12"
        "C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37"
        "C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27"
        "C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05"
        "C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42"
        "C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42"
        "L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05"
        "C4.73,4.96 4.46,5.05 4.34,5.27L2.34,8.73"
        "C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11"
        "C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97"
        "L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73"
        "C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.94"
        "C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58"
        "C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58"
        "L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95"
        "C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27"
        "C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z"
    ),
}

SUBDIV = 16  # Bezier subdivisions for smooth curves


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _flatten(path_str: str, scale: float, offset: float) -> list[list[tuple[float, float]]]:
    """Parse an SVG path and return a list of sub-polygons."""
    elements = parse_path(path_str)
    polygons: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    start = (0.0, 0.0)

    for elem in elements:
        cmd = elem.__class__.__name__.lower()
        if cmd == "moveto":
            if current:
                polygons.append(current)
            x = elem.start.real * scale + offset
            y = elem.start.imag * scale + offset
            current = [(x, y)]
            start = (x, y)
        elif cmd == "lineto":
            x = elem.end.real * scale + offset
            y = elem.end.imag * scale + offset
            current.append((x, y))
        elif cmd == "curveto":
            for i in range(SUBDIV + 1):
                t = i / SUBDIV
                bx = elem.start.real * scale * (1 - t) ** 3
                by = elem.start.imag * scale * (1 - t) ** 3
                cx1 = elem.control1.real * scale * 3 * (1 - t) ** 2 * t
                cy1 = elem.control1.imag * scale * 3 * (1 - t) ** 2 * t
                cx2 = elem.control2.real * scale * 3 * (1 - t) * t ** 2
                cy2 = elem.control2.imag * scale * 3 * (1 - t) * t ** 2
                ex = elem.end.real * scale * t ** 3
                ey = elem.end.imag * scale * t ** 3
                px = bx + cx1 + cx2 + ex + offset
                py = by + cy1 + cy2 + ey + offset
                current.append((px, py))
        elif cmd == "arc":
            for i in range(SUBDIV + 1):
                t = i / SUBDIV
                p = elem.point(t)
                current.append((p.real * scale + offset, p.imag * scale + offset))
        elif cmd in ("closepath", "z"):
            current.append(start)
            polygons.append(current)
            current = []
        elif cmd == "line":
            x = elem.end.real * scale + offset
            y = elem.end.imag * scale + offset
            current.append((x, y))

    if current:
        polygons.append(current)
    return polygons


def render(name: str, target: Path) -> None:
    hi = SIZE * SUPERSAMPLE
    img = Image.new("RGBA", (hi, hi), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fill = _hex_to_rgb(ICON_COLOR) + (255,)
    margin = hi * 0.08
    draw_size = hi - 2 * margin
    scale = draw_size / 24.0
    polygons = _flatten(MDI_PATHS[name], scale, margin)
    for poly in polygons:
        if len(poly) >= 2:
            draw.polygon(poly, fill=fill)
    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    img.save(target, format="PNG")
    print(f"wrote {target} ({SIZE}x{SIZE})")


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
    for name in NAMES:
        render(name, assets / f"nav-{name}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())