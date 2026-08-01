# ==============================================================================
# File: tool/generate_brand_assets.py
# Description: Rasterize Phronesis compass brand mark to PNG fallbacks and Windows ICO
# Component: Tooling / Brand assets
# Version: 1.1 (Gold Master)
# Created: 2026-07-31
# Last Update: 2026-07-31
# ==============================================================================
"""Generate PNG favicon fallbacks and Windows ICO from the Phronesis compass mark.

Uses Pillow to draw the same geometry as ``phronesis_app/static/phronesis/favicon.svg``
so raster assets stay in sync without an SVG renderer dependency.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "phronesis_app" / "static" / "phronesis"
WINDOWS_DIR = REPO_ROOT / "packaging" / "windows"

# Hybrid dark brand tokens (match themes.css / favicon.svg)
COLOR_BG = (11, 15, 25, 255)  # #0B0F19
COLOR_BORDER = (42, 50, 71, 217)  # #2A3247 @ ~85%
COLOR_EMERALD = (16, 185, 129, 255)  # #10B981
COLOR_EMERALD_MID = (16, 185, 129, 128)  # ~50% opacity ring
COLOR_EMERALD_FILL = (16, 185, 129, 15)  # ~6% fill
COLOR_MINT = (153, 246, 228, 255)  # #99F6E4

# Compass lives in a 100×100 design space, scaled to ~22px inside the 32px viewBox.
COMPASS_VIEWBOX_SCALE = 0.22


def _rounded_rect_mask(size: int, radius: float) -> Image.Image:
    """Alpha mask for a filled rounded rectangle."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def _scale_point(x: float, y: float, cx: float, cy: float, unit: float) -> tuple[float, float]:
    """Map a point from the 100×100 compass space to pixel coordinates."""
    return (cx + (x - 50.0) * unit, cy + (y - 50.0) * unit)


def _draw_compass(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Draw the livebytes.net Phronesis compass centered in the icon."""
    cx = cy = size / 2.0
    unit = COMPASS_VIEWBOX_SCALE * (size / 32.0)

    r_outer = 32.0 * unit
    r_mid = 22.0 * unit
    r_dot = max(1.0, 4.0 * unit)

    outer_box = (cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer)
    draw.ellipse(outer_box, fill=COLOR_EMERALD_FILL, outline=COLOR_EMERALD, width=max(1, int(round(2.5 * unit))))

    mid_box = (cx - r_mid, cy - r_mid, cx + r_mid, cy + r_mid)
    draw.ellipse(mid_box, outline=COLOR_EMERALD_MID, width=max(1, int(round(1.5 * unit))))

    dot_box = (cx - r_dot, cy - r_dot, cx + r_dot, cy + r_dot)
    draw.ellipse(dot_box, fill=COLOR_MINT)

    def line(x1: float, y1: float, x2: float, y2: float, color: tuple[int, ...], width: float) -> None:
        p1 = _scale_point(x1, y1, cx, cy, unit)
        p2 = _scale_point(x2, y2, cx, cy, unit)
        draw.line([p1, p2], fill=color, width=max(1, int(round(width * unit))))

    line(50, 50, 50, 22, COLOR_EMERALD, 2.5)
    line(50, 50, 68, 58, COLOR_EMERALD, 2.0)
    mint_tick = (*COLOR_MINT[:3], 179)
    line(50, 18, 58, 18, mint_tick, 1.5)
    line(78, 50, 70, 50, mint_tick, 1.5)


def render_brand_mark(size: int) -> Image.Image:
    """Draw the compass brand mark at *size*×*size* pixels."""
    scale = size / 32.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = 7.0 * scale
    bg = Image.new("RGBA", (size, size), COLOR_BG)
    bg.putalpha(_rounded_rect_mask(size, radius))
    img.alpha_composite(bg)

    inset = max(1, int(round(0.5 * scale)))
    border_w = max(1, int(round(1.0 * scale)))
    draw.rounded_rectangle(
        (inset, inset, size - inset - 1, size - inset - 1),
        radius=max(1.0, radius - inset),
        outline=COLOR_BORDER,
        width=border_w,
    )

    _draw_compass(draw, size)
    return img


def _write_png(path: Path, size: int) -> None:
    """Write a PNG brand mark to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    render_brand_mark(size).save(path, format="PNG", optimize=True)


def _write_ico(path: Path, sizes: tuple[int, ...]) -> None:
    """Write a multi-size Windows ICO using Pillow's ICO encoder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = [render_brand_mark(s) for s in sizes]
    frames[0].save(
        path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )


def main() -> None:
    """Generate PNG fallbacks under static/ and phronesis.ico for Windows packaging."""
    png_targets = {
        STATIC_DIR / "favicon-32.png": 32,
        STATIC_DIR / "apple-touch-icon.png": 180,
    }
    for path, px in png_targets.items():
        _write_png(path, px)
        print(f"wrote {path.relative_to(REPO_ROOT)} ({px}px)")

    ico_path = WINDOWS_DIR / "phronesis.ico"
    _write_ico(ico_path, (16, 32, 48, 256))
    print(f"wrote {ico_path.relative_to(REPO_ROOT)} (16/32/48/256)")


if __name__ == "__main__":
    main()
