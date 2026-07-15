"""Runtime SVG icon renderer for sidebar navigation buttons.

Renders Material Design Icons (24x24 viewBox) from the bundled .svg files
at an exact pixel size with supersampling anti-aliasing, returning
``tk.PhotoImage`` objects suitable for ``tk.Label(image=…)``.

Uses only stdlib modules, ``svg.path`` (pure-Python, bundled by PyInstaller),
and Tk. No Pillow or Cairo required at runtime.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import NamedTuple

from svg.path import parse_path


class _Edge(NamedTuple):
    ymin: float
    ymax: float
    x_at_ymin: float
    slope_inv: float  # dx / dy  (inverse slope; 0 for vertical)


# --- helpers ---------------------------------------------------------------

def _flatten_path_elements(
    path_str: str, num_bezier_segments: int = 8
) -> list[tuple[float, float]]:
    """Parse SVG path *d* string and return a flat list of vertex coords."""
    elements = parse_path(path_str)
    points: list[tuple[float, float]] = []

    for elem in elements:
        cls = elem.__class__.__name__.lower()
        if cls == "moveto":
            p = (elem.start.real, elem.start.imag)
            if points and points[-1] != p:
                points.append(p)  # new sub-path signal
            points.append(p)
        elif cls == "lineto":
            points.append((elem.end.real, elem.end.imag))
        elif cls == "curveto":
            for i in range(1, num_bezier_segments + 1):
                t = i / num_bezier_segments
                c = elem.point(t)
                points.append((c.real, c.imag))
        elif cls == "arc":
            for i in range(1, num_bezier_segments + 1):
                t = i / num_bezier_segments
                c = elem.point(t)
                points.append((c.real, c.imag))
        elif cls in ("closepath", "z"):
            pass
        elif cls == "line":
            points.append((elem.end.real, elem.end.imag))
        # else: ignore unknown commands

    return points


def _subpaths_from_points(
    points: list[tuple[float, float]],
) -> list[list[tuple[float, float]]]:
    """Split flat point list at moveto boundaries."""
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    prev: tuple[float, float] | None = None

    for p in points:
        if prev is not None and p == prev and current != [p]:
            if len(current) >= 1:
                subpaths.append(current)
            current = []
        current.append(p)
        prev = p

    if len(current) >= 1:
        subpaths.append(current)
    return subpaths


def _build_edges(
    vertices: list[tuple[float, float]],
) -> list[_Edge]:
    """Convert a closed polygon (list of vertices) to edge list."""
    edges: list[_Edge] = []
    n = len(vertices)
    if n < 2:
        return edges

    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]

        # Skip horizontal edges (they don't contribute to scanline fill)
        if abs(y2 - y1) < 1e-9:
            continue

        if y1 <= y2:
            ymin, ymax = y1, y2
            x_at_ymin = x1
        else:
            ymin, ymax = y2, y1
            x_at_ymin = x2

        slope_inv = (x2 - x1) / (y2 - y1)
        edges.append(_Edge(ymin, ymax, x_at_ymin, slope_inv))
    return edges


def _scanline_fill(
    edges: list[_Edge],
    width: int,
    height: int,
) -> list[list[bool]]:
    """Render filled polygon into a boolean grid using scanline method."""
    grid = [[False] * width for _ in range(height)]

    active: list[_Edge] = []
    # Process scanlines from top to bottom
    for y in range(height):
        # Remove edges that end before this scanline
        active = [e for e in active if e.ymax > y]
        # Add edges that start at this scanline
        for e in edges:
            if e.ymin <= y < e.ymax:
                if e not in active:
                    active.append(e)

        # Compute x intersections
        xs: list[float] = []
        for e in active:
            x = e.x_at_ymin + e.slope_inv * (y - e.ymin)
            xs.append(x)

        xs.sort()

        # Fill between pairs (even-odd rule)
        row = grid[y]
        for i in range(0, len(xs) - 1, 2):
            x_start = max(0, int(xs[i]) + 1)
            x_end = min(width, int(xs[i + 1]) + 1)
            for x in range(x_start, x_end):
                row[x] = True

    return grid


# --- PNG encoder -----------------------------------------------------------

def _encode_png_rgba(width: int, height: int, rows: list[bytes]) -> bytes:
    """Encode list of RGBA byte strings as a valid PNG."""

    def _chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
        c = chunk_type + chunk_data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(chunk_data)) + c + crc

    raw = b"".join(b"\x00" + row for row in rows)
    compressed = zlib.compress(raw)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", compressed)
        + _chunk(b"IEND", b"")
    )


# --- public API ------------------------------------------------------------

def render_svg_icon(
    svg_path: Path,
    pixel_size: int,
    color_hex: str = "#F7F8FA",
    supersample: int = 3,
) -> bytes:
    """Render an MDI SVG (viewBox 0 0 24 24) to RGBA PNG bytes.

    Arguments:
        svg_path: Path to the .svg file on disk.
        pixel_size: Size of the output square in device pixels.
        color_hex: Fill colour (``#RRGGBB``).
        supersample: Supersampling factor per axis (1 = no AA, 3 = 9×).

    Returns:
        PNG byte string (RGBA) that can be passed to
        ``tk.PhotoImage(data=base64.b64encode(bytes).decode())``.
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

    # Parse flat points
    flat_points = _flatten_path_elements(d_str)
    subpaths = _subpaths_from_points(flat_points)

    # R, G, B
    c = color_hex.lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

    # Scale from 24×24 viewBox to pixel grid with a 8% margin
    margin = pixel_size * supersample * 0.08
    usable = pixel_size * supersample - 2 * margin
    scale = usable / 24.0

    hi_res = pixel_size * supersample

    # Build boolean mask from all subpaths
    mask = [[False] * hi_res for _ in range(hi_res)]
    for sub in subpaths:
        if len(sub) < 3:
            continue
        # Scale and translate
        scaled = [
            (x * scale + margin, y * scale + margin) for x, y in sub
        ]
        edges = _build_edges(scaled)
        fill = _scanline_fill(edges, hi_res, hi_res)
        for y in range(hi_res):
            row_mask = mask[y]
            row_fill = fill[y]
            for x in range(hi_res):
                if row_fill[x]:
                    row_mask[x] = True

    # Downsample with averaging
    rows: list[bytes] = []
    for y in range(pixel_size):
        row_data = bytearray(pixel_size * 4)
        for x in range(pixel_size):
            total = 0
            for dy in range(supersample):
                my = y * supersample + dy
                mask_row = mask[my]
                for dx in range(supersample):
                    mx = x * supersample + dx
                    if mask_row[mx]:
                        total += 1
            alpha = round(total * 255 / (supersample * supersample))
            offset = x * 4
            row_data[offset] = r
            row_data[offset + 1] = g
            row_data[offset + 2] = b
            row_data[offset + 3] = alpha
        rows.append(bytes(row_data))

    return _encode_png_rgba(pixel_size, pixel_size, rows)
