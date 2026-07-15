"""Runtime SVG icon renderer for sidebar navigation buttons.

Renders Material Design Icons (24x24 viewBox) from the bundled .svg files
at an exact pixel size, producing ``tk.PhotoImage`` objects suitable for
``tk.Label(image=…)``.

Depends on ``svg.path`` (pure-Python path parser) and ``Pillow`` (anti-aliased
rasteriser + LANCZOS downscale). Both are bundled by PyInstaller — the
portable EXE has no install-time requirements.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageDraw
from PIL.ImageTk import PhotoImage as PilPhotoImage
from svg.path import parse_path


class _Edge(NamedTuple):
    ymin: float
    ymax: float
    x_at_ymin: float
    slope_inv: float


# The Pillow ImageTk module, when imported, *installs* a ``PhotoImage``
# constructor that is drop-in compatible with ``tk.PhotoImage``.  We import
# it as a side-effect so that the caller can still use plain
# ``tk.PhotoImage(data=…)`` if desired, but the primary return type is
# ``PIL.ImageTk.PhotoImage`` which auto-references the underlying PIL image
# and prevents early garbage-collection.
_ = PilPhotoImage  # noqa: F811 – register ImageTk.PhotoImage with Tk



# --- helpers ---------------------------------------------------------------

def _flatten_path_to_points(
    path_str: str,
    bezier_steps: int = 16,
) -> list[tuple[float, float]]:
    """Parse SVG *d* and return a flat list of vertex coords.

    Consecutive ``(x, y)`` pairs with the same value signal a sub-path
    boundary (new ``M`` / ``moveto``).
    """
    elements = parse_path(path_str)
    points: list[tuple[float, float]] = []

    for elem in elements:
        cls = elem.__class__.__name__.lower()
        if cls == "moveto":
            p = (elem.start.real, elem.start.imag)
            if points and points[-1] != p:
                points.append(p)  # boundary signal
            points.append(p)
        elif cls in ("lineto", "line"):
            points.append((elem.end.real, elem.end.imag))
        elif cls == "curveto":
            for i in range(1, bezier_steps + 1):
                c = elem.point(i / bezier_steps)
                points.append((c.real, c.imag))
        elif cls == "arc":
            for i in range(1, bezier_steps + 1):
                c = elem.point(i / bezier_steps)
                points.append((c.real, c.imag))
        elif cls == "close":
            points.append((elem.end.real, elem.end.imag))

    return points


def _subpath_polygons(
    flat: list[tuple[float, float]],
) -> list[list[tuple[float, float]]]:
    """Split the flat point list into closed polygon subpaths."""
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


# --- public API ------------------------------------------------------------

def render_svg_icon(
    svg_path: Path,
    pixel_size: int,
    color_hex: str = "#F7F8FA",
    supersample: int = 4,
) -> PilPhotoImage:
    """Render an MDI SVG (viewBox 0 0 24 24) to a Tk-compatible PhotoImage.

    Rasterises at ``pixel_size * supersample`` with Pillow, then LANCZOS-
    downsamples for smooth edges.  The returned ``PhotoImage`` is an
    ``ImageTk.PhotoImage`` which keeps a reference to the underlying PIL
    image so Tk labels display it reliably.

    Arguments:
        svg_path: Path to the .svg file on disk.
        pixel_size: Side length of the output square in device pixels.
        color_hex: Fill colour (``#RRGGBB``).
        supersample: Supersample factor (4 = 16× samples per pixel).

    Returns:
        ``tk.PhotoImage`` (actually ``PIL.ImageTk.PhotoImage``).
    """
    tree = ET.parse(svg_path)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    path_elem = tree.find(".//svg:path", ns)
    if path_elem is None:
        path_elem = tree.find(".//path")
    if path_elem is None:
        raise ValueError(f"No <path> element found in {svg_path}")

    d_str = path_elem.get("d", "").strip()
    if not d_str:
        raise ValueError(f"Empty path 'd' in {svg_path}")

    flat = _flatten_path_to_points(d_str)
    polys = _subpath_polygons(flat)

    c = color_hex.lstrip("#")
    colour = (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)

    hi_size = pixel_size * supersample
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

    if supersample > 1:
        img = img.resize((pixel_size, pixel_size), Image.LANCZOS)

    return PilPhotoImage(img)
