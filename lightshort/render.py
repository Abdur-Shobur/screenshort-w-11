"""Draw markup onto a cropped screenshot."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

COLORS = [
    "#ff3b30",
    "#ff9500",
    "#ffcc00",
    "#34c759",
    "#007aff",
    "#af52de",
    "#ffffff",
    "#1c1c1e",
]

FONT_SIZES = [12, 14, 16, 18, 20, 24, 28, 32, 40, 48, 64, 72]
STROKES = [2, 4, 8]


@dataclass
class Anno:
    kind: str
    points: list[tuple[float, float]]
    color: str
    width: int
    font_size: int = 20
    text: str = ""


def contrast_bg(color: str) -> str:
    red, green, blue = hex_rgb(color)
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    return "#1c1c1e" if luminance > 170 else "#ffffff"


def hex_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def load_font(size: int) -> ImageFont.ImageFont:
    for path in (
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, size=max(8, int(size)))
    return ImageFont.load_default()


def arrow_parts(
    x1: float, y1: float, x2: float, y2: float, width: int
) -> tuple[tuple[float, float, float, float], list[tuple[float, float]]]:
    angle = math.atan2(y2 - y1, x2 - x1)
    length = math.hypot(x2 - x1, y2 - y1)
    head = max(12.0, 8.0 + width * 3.5)
    if length > 1:
        head = min(head, max(length * 0.55, 8.0))
    else:
        head = 0.0
    base_x = x2 - head * math.cos(angle)
    base_y = y2 - head * math.sin(angle)
    spread = math.radians(26)
    tip = (x2, y2)
    left = (
        x2 - head * math.cos(angle - spread),
        y2 - head * math.sin(angle - spread),
    )
    right = (
        x2 - head * math.cos(angle + spread),
        y2 - head * math.sin(angle + spread),
    )
    return (x1, y1, base_x, base_y), [tip, left, right]


def constrain_square(x0: float, y0: float, x1: float, y1: float, square: bool) -> tuple[float, float]:
    if not square:
        return x1, y1
    dx = x1 - x0
    dy = y1 - y0
    side = max(abs(dx), abs(dy))
    return x0 + (side if dx >= 0 else -side), y0 + (side if dy >= 0 else -side)


def normalize_box(
    x0: float, y0: float, x1: float, y1: float, limit_w: int, limit_h: int
) -> tuple[int, int, int, int] | None:
    left = max(0, min(limit_w, int(min(x0, x1))))
    top = max(0, min(limit_h, int(min(y0, y1))))
    right = max(0, min(limit_w, int(max(x0, x1))))
    bottom = max(0, min(limit_h, int(max(y0, y1))))
    width = right - left
    height = bottom - top
    if width < 1 or height < 1:
        return None
    return left, top, width, height


def render(base: Image.Image, selection: tuple[int, int, int, int], annos: list[Anno]) -> Image.Image:
    x, y, width, height = selection
    crop = base.crop((x, y, x + width, y + height)).convert("RGBA")
    layer = Image.new("RGBA", crop.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for anno in annos:
        _draw_anno(draw, anno, x, y)
    return Image.alpha_composite(crop, layer).convert("RGB")


def _local(points: list[tuple[float, float]], ox: int, oy: int) -> list[tuple[float, float]]:
    return [(px - ox, py - oy) for px, py in points]


def _box(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float, float, float]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def _draw_anno(draw: ImageDraw.ImageDraw, anno: Anno, ox: int, oy: int) -> None:
    pts = _local(anno.points, ox, oy)
    red, green, blue = hex_rgb(anno.color)
    if anno.kind == "highlight":
        if len(pts) >= 2:
            _line(draw, pts, red, green, blue, 90, max(18, anno.width * 6))
        return
    if anno.kind == "pen":
        if len(pts) >= 2:
            _line(draw, pts, red, green, blue, 255, max(1, anno.width))
        elif len(pts) == 1:
            radius = max(1, anno.width // 2)
            px, py = pts[0]
            draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=(red, green, blue, 255))
        return
    if anno.kind == "line" and len(pts) >= 2:
        _line(draw, [pts[0], pts[-1]], red, green, blue, 255, max(1, anno.width))
        return
    if anno.kind == "arrow" and len(pts) >= 2:
        shaft, head = arrow_parts(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1], anno.width)
        _line(draw, [(shaft[0], shaft[1]), (shaft[2], shaft[3])], red, green, blue, 255, max(1, anno.width))
        draw.polygon(head, fill=(red, green, blue, 255))
        return
    if anno.kind == "rect" and len(pts) >= 2:
        draw.rectangle(_box(pts[0], pts[-1]), outline=(red, green, blue, 255), width=max(1, anno.width))
        return
    if anno.kind == "ellipse" and len(pts) >= 2:
        draw.ellipse(_box(pts[0], pts[-1]), outline=(red, green, blue, 255), width=max(1, anno.width))
        return
    if anno.kind == "text" and anno.text and pts:
        draw.text(pts[0], anno.text, font=load_font(anno.font_size), fill=(red, green, blue, 255))


def _line(
    draw: ImageDraw.ImageDraw,
    pts: list[tuple[float, float]],
    red: int,
    green: int,
    blue: int,
    alpha: int,
    width: int,
) -> None:
    fill = (red, green, blue, alpha)
    try:
        draw.line(pts, fill=fill, width=width, joint="curve")
    except TypeError:
        draw.line(pts, fill=fill, width=width)
