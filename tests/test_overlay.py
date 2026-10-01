"""Open the editor on a fake screenshot, draw, export, and close."""

import tempfile
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageDraw

from lightshort.overlay import CaptureOverlay
from lightshort.render import Anno
from lightshort.settings import Settings
from lightshort.winutil import enable_dpi_awareness


def test_editor_exports_markup():
    enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    image = Image.new("RGB", (480, 300), (245, 245, 245))
    ImageDraw.Draw(image).rectangle((30, 30, 180, 100), fill=(10, 132, 255))
    folder = Path(tempfile.mkdtemp())
    settings = Settings(folder / "settings.json")
    overlay = None
    try:
        overlay = CaptureOverlay(
            root,
            settings,
            on_close=lambda: None,
            on_notify=lambda _message: None,
            image=image,
            origin=(60, 60),
        )
        root.update()

        class Pointer:
            def __init__(self, x, y, state=0):
                self.x = x
                self.y = y
                self.state = state

        overlay._on_press(Pointer(15, 18))
        overlay._on_move(Pointer(200, 150))
        overlay._on_release(Pointer(200, 150))
        assert overlay.mode == "edit"
        assert overlay.sel == (15, 18, 185, 132)
        overlay.set_tool("rect")
        overlay._on_press(Pointer(40, 50, state=1))
        overlay._on_move(Pointer(120, 70, state=1))
        overlay._on_release(Pointer(120, 70, state=1))
        square = overlay.annos[-1]
        assert square.kind == "rect"
        assert abs(square.points[1][0] - square.points[0][0]) == abs(square.points[1][1] - square.points[0][1])
        overlay._enter_edit((20, 20, 240, 160))
        overlay.set_tool("arrow")
        overlay.set_color("#ff3b30")
        overlay.set_stroke(4)
        overlay._commit(Anno("arrow", [(40, 140), (180, 40)], "#ff3b30", 4))
        overlay._commit(Anno("rect", [(50, 50), (150, 110)], "#ffcc00", 4))
        overlay.bump_font(2)
        overlay._commit(Anno("text", [(60, 120)], "#1c1c1e", 4, overlay.font_size, "Shot"))
        root.update()
        exported = overlay.result_image()
        assert exported is not None
        assert exported.size == (240, 160)
        pixels = list(exported.getdata())
        assert any(pixel[0] > 200 and pixel[1] < 90 for pixel in pixels)
        overlay.undo()
        assert len(overlay.annos) == 3
        overlay.redo_anno()
        assert len(overlay.annos) == 4
        assert overlay.toolbar.winfo_ismapped()
        assert overlay.tool_buttons["arrow"].cget("bg") == "#0a84ff"
    finally:
        if overlay is not None:
            overlay.close()
        root.update()
        root.destroy()
