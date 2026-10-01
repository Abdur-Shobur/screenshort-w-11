"""Annotation export checks that do not open a window."""

from PIL import Image

from lightshort.render import Anno, render


def test_arrow_rect_and_text_are_drawn():
    base = Image.new("RGB", (200, 120), (255, 255, 255))
    annos = [
        Anno("arrow", [(10, 60), (120, 20)], "#ff3b30", 4),
        Anno("rect", [(20, 20), (90, 80)], "#007aff", 4),
        Anno("text", [(30, 90)], "#1c1c1e", 2, 18, "Note"),
    ]
    image = render(base, (0, 0, 200, 120), annos)
    assert image.size == (200, 120)
    pixels = list(image.getdata())
    assert any(pixel[0] > 200 and pixel[1] < 90 and pixel[2] < 90 for pixel in pixels)
    assert any(pixel[2] > 180 and pixel[0] < 80 for pixel in pixels)
    assert any(pixel[0] < 40 and pixel[1] < 40 and pixel[2] < 40 for pixel in pixels)
