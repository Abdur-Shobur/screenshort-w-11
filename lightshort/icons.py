"""Small toolbar and tray icons drawn with Pillow."""

from __future__ import annotations

from PIL import Image, ImageDraw

from lightshort.render import arrow_parts


def _canvas(size: int = 22) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def icon_arrow(color: str = "#f2f2f7") -> Image.Image:
    image, draw = _canvas()
    shaft, head = arrow_parts(4, 17, 17, 4, 2)
    draw.line([(shaft[0], shaft[1]), (shaft[2], shaft[3])], fill=color, width=2)
    draw.polygon(head, fill=color)
    return image


def icon_rect(color: str = "#f2f2f7") -> Image.Image:
    image, draw = _canvas()
    draw.rectangle((4, 5, 17, 17), outline=color, width=2)
    return image


def icon_ellipse(color: str = "#f2f2f7") -> Image.Image:
    image, draw = _canvas()
    draw.ellipse((4, 5, 17, 17), outline=color, width=2)
    return image


def icon_line(color: str = "#f2f2f7") -> Image.Image:
    image, draw = _canvas()
    draw.line((4, 17, 17, 5), fill=color, width=2)
    return image


def icon_pen(color: str = "#f2f2f7") -> Image.Image:
    image, draw = _canvas()
    draw.line((6, 17, 16, 6), fill=color, width=2)
    draw.polygon([(15, 3), (19, 7), (16, 8), (12, 4)], fill=color)
    return image


def icon_marker(color: str = "#f2f2f7") -> Image.Image:
    image, draw = _canvas()
    draw.line((3, 15, 18, 8), fill=color, width=6)
    return image


def icon_text(color: str = "#f2f2f7") -> Image.Image:
    image, draw = _canvas()
    draw.line((6, 4, 16, 4), fill=color, width=2)
    draw.line((11, 4, 11, 18), fill=color, width=2)
    draw.line((7, 18, 15, 18), fill=color, width=2)
    return image


def app_icon(size: int = 64) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(2, size // 16)
    draw.rounded_rectangle(
        (margin, margin, size - margin - 1, size - margin - 1),
        radius=max(4, size // 5),
        fill=(10, 132, 255, 255),
    )
    arm = max(2, size // 16)
    inset = size // 4
    color = (255, 255, 255, 255)
    # Viewfinder corners.
    corners = (
        (inset, inset, 1, 1),
        (size - inset, inset, -1, 1),
        (inset, size - inset, 1, -1),
        (size - inset, size - inset, -1, -1),
    )
    length = size // 5
    for x, y, sx, sy in corners:
        draw.line((x, y, x + sx * length, y), fill=color, width=arm)
        draw.line((x, y, x, y + sy * length), fill=color, width=arm)
    return image


TOOL_ICONS = {
    "arrow": icon_arrow,
    "rect": icon_rect,
    "ellipse": icon_ellipse,
    "line": icon_line,
    "pen": icon_pen,
    "highlight": icon_marker,
    "text": icon_text,
}
