"""Fullscreen region select and markup editor."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog

import mss
from PIL import Image, ImageTk

from lightshort.clipboard import copy_image
from lightshort.icons import TOOL_ICONS
from lightshort.render import (
    COLORS,
    FONT_SIZES,
    STROKES,
    Anno,
    constrain_square,
    contrast_bg,
    hex_rgb,
    normalize_box,
    render,
)
from lightshort.settings import Settings, log
from lightshort.winutil import focus_window, pictures_dir

TOOLS = (
    ("arrow", "Arrow", "1"),
    ("rect", "Square", "2"),
    ("ellipse", "Circle", "3"),
    ("line", "Line", "4"),
    ("pen", "Pen", "5"),
    ("highlight", "Marker", "6"),
    ("text", "Text", "7"),
)

TOOL_HINTS = {
    "arrow": "Arrow",
    "rect": "Square · hold Shift to lock",
    "ellipse": "Circle · hold Shift to lock",
    "line": "Line",
    "pen": "Pen",
    "highlight": "Marker",
    "text": "Text · click, type, Enter",
}

HANDLE_CURSORS = {
    "nw": "size_nw_se",
    "se": "size_nw_se",
    "ne": "size_ne_sw",
    "sw": "size_ne_sw",
    "n": "size_ns",
    "s": "size_ns",
    "e": "size_we",
    "w": "size_we",
}


class CaptureOverlay:
    def __init__(
        self,
        root: tk.Tk,
        settings: Settings,
        on_close,
        on_notify,
        image: Image.Image | None = None,
        origin: tuple[int, int] = (0, 0),
    ) -> None:
        self.root = root
        self.settings = settings
        self.on_close = on_close
        self.on_notify = on_notify
        self.closed = False
        self.mode = "select"
        self.sel: tuple[int, int, int, int] | None = None
        self.annos: list[Anno] = []
        self.item_ids: list[list[int]] = []
        self.redo: list[Anno] = []
        self._selecting = False
        self._drawing = False
        self._resizing: str | None = None
        self._select_origin = (0, 0)
        self._origin = (0.0, 0.0)
        self._points: list[tuple[float, float]] = []
        self._shift = False
        self._ignore_release = False
        self._bright_job = None
        self._compose_job = None
        self._pending_box = None
        self.bright_id = None
        self.bright_photo = None
        self.view_photo = None
        self.text_entry: tk.Entry | None = None
        self.text_window = None
        self.text_at = (0, 0)
        self.tool = self._setting_tool()
        self.color = self._setting_color()
        self.stroke = self._setting_stroke()
        self.font_size = self._setting_font()

        if image is None:
            self._grab_screen()
        else:
            self.base = image.convert("RGB")
            self.origin = origin
            width, height = self.base.size
            monitor = {"left": origin[0], "top": origin[1], "width": width, "height": height}
            self.monitors = [monitor, dict(monitor)]
        self.sw, self.sh = self.base.size
        black = Image.new("RGB", self.base.size, (0, 0, 0))
        self.dark = Image.blend(self.base, black, 0.58)
        try:
            self._build()
        except Exception:
            self.closed = True
            win = getattr(self, "win", None)
            if win is not None:
                try:
                    win.destroy()
                except tk.TclError:
                    pass
            raise

    def _setting_tool(self) -> str:
        tool = str(self.settings.get("tool"))
        return tool if tool in TOOL_ICONS else "arrow"

    def _setting_color(self) -> str:
        color = str(self.settings.get("color"))
        if color in COLORS or (color.startswith("#") and len(color) == 7):
            try:
                hex_rgb(color)
                return color
            except ValueError:
                pass
        return COLORS[0]

    def _setting_stroke(self) -> int:
        try:
            stroke = int(self.settings.get("stroke"))
        except (TypeError, ValueError):
            stroke = 4
        return stroke if stroke in STROKES else 4

    def _setting_font(self) -> int:
        try:
            size = int(self.settings.get("font_size"))
        except (TypeError, ValueError):
            size = 20
        return size if size in FONT_SIZES else 20

    def _grab_screen(self) -> None:
        with mss.mss() as sct:
            self.monitors = [dict(mon) for mon in sct.monitors]
            virtual = self.monitors[0]
            raw = sct.grab(virtual)
            self.base = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            self.origin = (virtual["left"], virtual["top"])
        log(f"captured {self.base.width}x{self.base.height} at {self.origin[0]},{self.origin[1]}")

    def _build(self) -> None:
        self.win = tk.Toplevel(self.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="black")
        left, top = self.origin
        self.win.geometry(f"{self.sw}x{self.sh}{left:+d}{top:+d}")
        self.canvas = tk.Canvas(
            self.win,
            width=self.sw,
            height=self.sh,
            highlightthickness=0,
            bd=0,
            bg="black",
            cursor="crosshair",
        )
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.dark_photo = ImageTk.PhotoImage(self.dark)
        self.bg_id = self.canvas.create_image(0, 0, image=self.dark_photo, anchor="nw")
        self._build_toolbar()
        self._show_select_hint()
        self._bind_keys()
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<ButtonPress-3>", self._on_right)
        self.canvas.bind("<Motion>", self._on_hover)
        self.win.deiconify()
        self.win.update_idletasks()
        self.win.lift()
        try:
            focus_window(self.win.winfo_id())
        except Exception as exc:
            log(f"focus failed: {exc}")
        self.win.focus_force()
        try:
            self.win.grab_set()
        except tk.TclError:
            pass

    def _bind_keys(self) -> None:
        self.win.bind("<Escape>", self._on_escape)
        self.win.bind("<Return>", self._on_enter)
        self.win.bind("<Control-z>", lambda e: self._history_key(self.undo))
        self.win.bind("<Control-Z>", lambda e: self._history_key(self.undo))
        self.win.bind("<Control-y>", lambda e: self._history_key(self.redo_anno))
        self.win.bind("<Control-Y>", lambda e: self._history_key(self.redo_anno))
        self.win.bind("<Control-Shift-Z>", lambda e: self._history_key(self.redo_anno))
        self.win.bind("<Control-s>", lambda e: self._save_key(False))
        self.win.bind("<Control-S>", lambda e: self._save_key(False))
        self.win.bind("<Control-Shift-s>", lambda e: self._save_key(True))
        self.win.bind("<Control-Shift-S>", lambda e: self._save_key(True))
        self.win.bind("<Control-c>", self._on_copy_key)
        self.win.bind("<Control-C>", self._on_copy_key)
        self.win.bind("<Control-x>", self._on_close_key)
        self.win.bind("<Control-X>", self._on_close_key)
        self.win.bind("<Delete>", lambda e: self._history_key(self.undo))
        for index, (tool, _label, _key) in enumerate(TOOLS):
            self.win.bind(str(index + 1), lambda e, name=tool: self._tool_key(name))

    def _typing(self) -> bool:
        return self.text_entry is not None and self.win.focus_get() == self.text_entry

    def _history_key(self, action):
        if self._typing() or self.mode != "edit":
            return
        action()
        return "break"

    def _tool_key(self, name: str):
        if self._typing() or self.mode != "edit":
            return
        self.set_tool(name)
        return "break"

    def _save_key(self, choose: bool):
        if self._typing() or self.mode != "edit":
            return
        self.save(choose=choose, close=not choose)
        return "break"

    def _on_copy_key(self, _event):
        if self._typing() or self.mode != "edit":
            return
        self.copy(close=True)
        return "break"

    def _on_close_key(self, _event):
        if self._typing():
            return
        self.close()
        return "break"

    def _on_enter(self, _event):
        if self._typing():
            return
        if self.mode == "edit":
            self.copy(close=True)
        return "break"

    def _on_escape(self, _event):
        if self.text_entry is not None:
            self._cancel_text()
            return "break"
        self.close()
        return "break"

    def _on_right(self, _event):
        if self.mode == "select":
            self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.settings.data.update(
            {
                "tool": self.tool,
                "color": self.color,
                "stroke": self.stroke,
                "font_size": self.font_size,
            }
        )
        self.settings.save()
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_close()

    def _show_select_hint(self) -> None:
        self.canvas.delete("hint")
        title = self.canvas.create_text(
            self.sw / 2,
            self.sh / 2 - 16,
            text="Drag to select an area",
            fill="#ffffff",
            font=("Segoe UI", 22, "bold"),
            tags=("hint", "hinttext"),
        )
        self.canvas.create_text(
            self.sw / 2,
            self.sh / 2 + 22,
            text="Double-click selects one screen    ·    Esc cancels    ·    right-click cancels",
            fill="#f2f2f7",
            font=("Segoe UI", 12),
            tags=("hint", "hinttext"),
        )
        self._back_text(title)

    def _show_edit_hint(self) -> None:
        self.canvas.delete("hint")
        item = self.canvas.create_text(
            self.sw / 2,
            self.sh - 28,
            text="Ctrl+S saves and closes    ·    Ctrl+C copies and closes    ·    Ctrl+X closes",
            fill="#f2f2f7",
            font=("Segoe UI", 11),
            tags=("hint", "hinttext"),
        )
        self._back_text(item)
        self._raise_ui()

    def _back_text(self, item: int) -> None:
        bbox = self.canvas.bbox(item)
        if not bbox:
            return
        pad_x, pad_y = 10, 4
        rect = self.canvas.create_rectangle(
            bbox[0] - pad_x,
            bbox[1] - pad_y,
            bbox[2] + pad_x,
            bbox[3] + pad_y,
            fill="#1c1c1e",
            outline="",
            tags="hint",
        )
        self.canvas.tag_lower(rect, item)

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self.win, bg="#1c1c1e", highlightthickness=1, highlightbackground="#3a3a3c")
        self.toolbar = bar
        self.icon_photos = {name: ImageTk.PhotoImage(factory()) for name, factory in TOOL_ICONS.items()}
        row1 = tk.Frame(bar, bg="#1c1c1e")
        row1.pack(fill="x", padx=6, pady=(6, 2))
        row2 = tk.Frame(bar, bg="#1c1c1e")
        row2.pack(fill="x", padx=6, pady=(2, 6))
        self.tool_buttons = {}
        for name, label, _key in TOOLS:
            button = tk.Button(
                row1,
                image=self.icon_photos[name],
                command=lambda n=name: self.set_tool(n),
                bg="#1c1c1e",
                activebackground="#2c2c2e",
                relief="flat",
                bd=0,
                padx=5,
                pady=4,
                cursor="hand2",
            )
            button.pack(side="left", padx=1)
            button.bind("<Enter>", lambda e, text=label: self.status.set(text))
            button.bind("<Leave>", lambda e: self._set_status())
            self.tool_buttons[name] = button

        self.undo_btn = self._text_button(row1, "Undo", self.undo)
        self.redo_btn = self._text_button(row1, "Redo", self.redo_anno)
        self._text_button(row1, "Copy", lambda: self.copy(close=False))
        self._text_button(row1, "Save", lambda: self.save(choose=False, close=True))
        close = self._text_button(row1, "Close", self.close)
        close.configure(fg="#ff6b6b")

        self.color_dots = {}
        for color in COLORS:
            dot = tk.Canvas(row2, width=18, height=18, bg="#1c1c1e", highlightthickness=0, cursor="hand2")
            oval = dot.create_oval(2, 2, 16, 16, fill=color, outline="#3a3a3c", width=1)
            dot.pack(side="left", padx=2, pady=4)
            dot.bind("<Button-1>", lambda e, value=color: self.set_color(value))
            self.color_dots[color] = (dot, oval)

        tk.Frame(row2, width=8, bg="#1c1c1e").pack(side="left")
        self.stroke_buttons = {}
        for stroke in STROKES:
            sample = tk.Canvas(row2, width=28, height=18, bg="#2a2a2c", highlightthickness=0, cursor="hand2")
            sample.create_line(4, 9, 24, 9, fill="#f2f2f7", width=stroke, capstyle=tk.ROUND)
            sample.pack(side="left", padx=2)
            sample.bind("<Button-1>", lambda e, value=stroke: self.set_stroke(value))
            self.stroke_buttons[stroke] = sample

        tk.Frame(row2, width=8, bg="#1c1c1e").pack(side="left")
        tk.Label(row2, text="Font", bg="#1c1c1e", fg="#aeaeb2", font=("Segoe UI", 9)).pack(side="left", padx=(2, 2))
        minus = self._text_button(row2, "A−", lambda: self.bump_font(-1))
        minus.configure(padx=4)
        self.font_label = tk.Label(row2, text=str(self.font_size), bg="#1c1c1e", fg="#f2f2f7", font=("Segoe UI", 10), width=3)
        self.font_label.pack(side="left")
        plus = self._text_button(row2, "A+", lambda: self.bump_font(1))
        plus.configure(padx=4)
        self.status = tk.StringVar(value=TOOL_HINTS[self.tool])
        tk.Label(row2, textvariable=self.status, bg="#1c1c1e", fg="#8e8e93", font=("Segoe UI", 9), anchor="w", width=28).pack(
            side="left", padx=(8, 2)
        )
        self._style_tool()
        self._style_color()
        self._style_stroke()
        self._refresh_history_buttons()

    def _text_button(self, parent, text, command) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg="#2a2a2c",
            fg="#f5f5f7",
            activebackground="#3a3a3c",
            activeforeground="#ffffff",
            disabledforeground="#636366",
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            font=("Segoe UI", 9),
        )
        button.pack(side="left", padx=2)
        return button

    def set_tool(self, name: str) -> None:
        if name not in TOOL_ICONS:
            return
        self.tool = name
        self._style_tool()
        self._set_status()
        if self.mode == "edit" and not self._resizing and not self._drawing:
            self.canvas.configure(cursor=self._tool_cursor())

    def set_color(self, color: str) -> None:
        self.color = color
        self._style_color()
        if self.text_entry is not None:
            self.text_entry.configure(
                fg=color,
                insertbackground=color,
                highlightbackground=color,
                bg=contrast_bg(color),
            )

    def set_stroke(self, stroke: int) -> None:
        self.stroke = stroke
        self._style_stroke()

    def bump_font(self, delta: int) -> None:
        index = FONT_SIZES.index(self.font_size) if self.font_size in FONT_SIZES else 0
        index = max(0, min(len(FONT_SIZES) - 1, index + delta))
        self.font_size = FONT_SIZES[index]
        self.font_label.configure(text=str(self.font_size))
        if self.text_entry is not None:
            self.text_entry.configure(font=("Segoe UI", -self.font_size))

    def _style_tool(self) -> None:
        for name, button in self.tool_buttons.items():
            active = name == self.tool
            button.configure(bg="#0a84ff" if active else "#1c1c1e")

    def _style_color(self) -> None:
        for color, (dot, oval) in self.color_dots.items():
            selected = color == self.color
            dot.itemconfig(oval, width=2 if selected else 1, outline="#ffffff" if selected else "#3a3a3c")

    def _style_stroke(self) -> None:
        for stroke, sample in self.stroke_buttons.items():
            sample.configure(bg="#0a84ff" if stroke == self.stroke else "#2a2a2c")

    def _set_status(self) -> None:
        self.status.set(TOOL_HINTS.get(self.tool, ""))

    def _refresh_history_buttons(self) -> None:
        self.undo_btn.configure(state="normal" if self.annos else "disabled")
        self.redo_btn.configure(state="normal" if self.redo else "disabled")

    def _tool_cursor(self) -> str:
        return "xterm" if self.tool == "text" else "crosshair"

    def _clamp(self, x: int, y: int) -> tuple[int, int]:
        return min(max(int(x), 0), self.sw), min(max(int(y), 0), self.sh)

    def _inside(self, x: int, y: int) -> bool:
        if not self.sel:
            return False
        left, top, width, height = self.sel
        return left <= x <= left + width and top <= y <= top + height

    def _on_press(self, event) -> None:
        x, y = self._clamp(event.x, event.y)
        self._shift = bool(event.state & 0x0001)
        if self.mode == "select":
            self._select_origin = (x, y)
            self._selecting = True
            self.canvas.delete("hint")
            return
        if self.text_entry is not None:
            self._commit_text()
        handle = self._hit_handle(x, y)
        if handle:
            self._resizing = handle
            return
        if not self._inside(x, y):
            return
        if self.tool == "text":
            self._begin_text(x, y)
            return
        self._drawing = True
        self._origin = (x, y)
        self._points = [(x, y)]

    def _on_move(self, event) -> None:
        x, y = self._clamp(event.x, event.y)
        self._shift = bool(event.state & 0x0001)
        if self.mode == "select" and self._selecting:
            self._preview_selection(self._select_origin, (x, y))
            return
        if self._resizing:
            self._apply_resize(self._resizing, x, y)
            return
        if self._drawing:
            if self.tool in ("pen", "highlight"):
                last = self._points[-1]
                if math.hypot(x - last[0], y - last[1]) >= 1.5:
                    self._points.append((x, y))
            self._preview_shape((x, y))

    def _on_hover(self, event) -> None:
        if self.mode != "edit" or self._drawing or self._resizing:
            return
        x, y = self._clamp(event.x, event.y)
        handle = self._hit_handle(x, y)
        self.canvas.configure(cursor=HANDLE_CURSORS.get(handle, self._tool_cursor()))

    def _on_release(self, event) -> None:
        if self._ignore_release:
            self._ignore_release = False
            return
        x, y = self._clamp(event.x, event.y)
        self._shift = bool(event.state & 0x0001)
        if self.mode == "select" and self._selecting:
            self._selecting = False
            box = normalize_box(self._select_origin[0], self._select_origin[1], x, y, self.sw, self.sh)
            if box and box[2] >= 8 and box[3] >= 8:
                self._enter_edit(box)
            else:
                self._clear_select_preview()
                self._show_select_hint()
            return
        if self._resizing:
            self._resizing = None
            self._compose_now()
            return
        if self._drawing:
            self._drawing = False
            self._finish_shape((x, y))

    def _on_double(self, event) -> None:
        if self.mode != "select":
            return
        self._selecting = False
        self._ignore_release = True
        self._enter_edit(self._monitor_at(event.x, event.y))

    def _monitor_at(self, x: int, y: int) -> tuple[int, int, int, int]:
        origin_x, origin_y = self.origin
        for monitor in self.monitors[1:]:
            left = monitor["left"] - origin_x
            top = monitor["top"] - origin_y
            if left <= x < left + monitor["width"] and top <= y < top + monitor["height"]:
                return (int(left), int(top), int(monitor["width"]), int(monitor["height"]))
        return (0, 0, self.sw, self.sh)

    def _preview_selection(self, start, end) -> None:
        box = normalize_box(start[0], start[1], end[0], end[1], self.sw, self.sh)
        self.canvas.delete("selui")
        self.canvas.delete("badge")
        if not box:
            return
        self._pending_box = box
        x, y, width, height = box
        self.canvas.create_rectangle(x, y, x + width, y + height, outline="#0a84ff", width=2, tags="selui")
        self._draw_badge(box)
        if not self._bright_job:
            self._bright_job = self.win.after(16, self._flush_bright)

    def _flush_bright(self) -> None:
        self._bright_job = None
        box = self._pending_box
        if not box or self.mode != "select":
            return
        x, y, width, height = box
        crop = self.base.crop((x, y, x + width, y + height))
        self.bright_photo = ImageTk.PhotoImage(crop)
        if self.bright_id is None:
            self.bright_id = self.canvas.create_image(x, y, image=self.bright_photo, anchor="nw", tags="bright")
        else:
            self.canvas.coords(self.bright_id, x, y)
            self.canvas.itemconfig(self.bright_id, image=self.bright_photo)
        self._raise_ui()

    def _clear_select_preview(self) -> None:
        self.canvas.delete("selui")
        self.canvas.delete("badge")
        self.canvas.delete("bright")
        self.bright_id = None
        self.bright_photo = None

    def _enter_edit(self, box: tuple[int, int, int, int]) -> None:
        self.mode = "edit"
        self.sel = box
        self._selecting = False
        self.canvas.delete("hint")
        self._clear_select_preview()
        self._compose_now()
        self._draw_selection_chrome()
        self._place_toolbar()
        self._show_edit_hint()
        self.canvas.configure(cursor=self._tool_cursor())

    def _compose_now(self) -> None:
        if not self.sel:
            return
        x, y, width, height = self.sel
        image = self.dark.copy()
        image.paste(self.base.crop((x, y, x + width, y + height)), (x, y))
        self.view_photo = ImageTk.PhotoImage(image)
        self.canvas.itemconfig(self.bg_id, image=self.view_photo)
        self._raise_ui()

    def _queue_compose(self) -> None:
        if self._compose_job:
            return
        self._compose_job = self.win.after(16, self._flush_compose)

    def _flush_compose(self) -> None:
        self._compose_job = None
        self._compose_now()

    def _draw_selection_chrome(self) -> None:
        self.canvas.delete("selui")
        self.canvas.delete("badge")
        if not self.sel:
            return
        x, y, width, height = self.sel
        self.canvas.create_rectangle(x, y, x + width, y + height, outline="#0a84ff", width=2, tags="selui")
        for cx, cy in self._handle_points().values():
            self.canvas.create_rectangle(
                cx - 4,
                cy - 4,
                cx + 4,
                cy + 4,
                fill="#ffffff",
                outline="#0a84ff",
                width=1,
                tags="selui",
            )
        self._draw_badge(self.sel)
        self._raise_ui()

    def _handle_points(self) -> dict[str, tuple[float, float]]:
        x, y, width, height = self.sel
        return {
            "nw": (x, y),
            "n": (x + width / 2, y),
            "ne": (x + width, y),
            "e": (x + width, y + height / 2),
            "se": (x + width, y + height),
            "s": (x + width / 2, y + height),
            "sw": (x, y + height),
            "w": (x, y + height / 2),
        }

    def _hit_handle(self, x: int, y: int) -> str | None:
        if not self.sel:
            return None
        for name, (cx, cy) in self._handle_points().items():
            if abs(x - cx) <= 8 and abs(y - cy) <= 8:
                return name
        return None

    def _apply_resize(self, handle: str, mx: int, my: int) -> None:
        x, y, width, height = self.sel
        left, top, right, bottom = float(x), float(y), float(x + width), float(y + height)
        if "w" in handle:
            left = mx
        if "e" in handle:
            right = mx
        if "n" in handle:
            top = my
        if "s" in handle:
            bottom = my
        if right < left:
            left, right = right, left
        if bottom < top:
            top, bottom = bottom, top
        left = max(0, min(left, self.sw - 8))
        top = max(0, min(top, self.sh - 8))
        right = max(left + 8, min(float(self.sw), right))
        bottom = max(top + 8, min(float(self.sh), bottom))
        self.sel = (int(left), int(top), int(right - left), int(bottom - top))
        self._draw_selection_chrome()
        self._place_toolbar()
        self._queue_compose()

    def _draw_badge(self, box: tuple[int, int, int, int]) -> None:
        x, y, width, height = box
        label_y = y - 22 if y >= 28 else y + 8
        text = self.canvas.create_text(
            x + 8,
            label_y,
            text=f"{width} × {height}",
            anchor="w",
            fill="#ffffff",
            font=("Segoe UI", 10, "bold"),
            tags=("badge", "badgetext"),
        )
        bbox = self.canvas.bbox(text)
        if not bbox:
            return
        rect = self.canvas.create_rectangle(
            bbox[0] - 6,
            bbox[1] - 3,
            bbox[2] + 6,
            bbox[3] + 3,
            fill="#0a84ff",
            outline="",
            tags="badge",
        )
        self.canvas.tag_lower(rect, text)

    def _place_toolbar(self) -> None:
        if not self.sel:
            return
        self.toolbar.update_idletasks()
        tw = max(self.toolbar.winfo_reqwidth(), 1)
        th = max(self.toolbar.winfo_reqheight(), 1)
        x, y, width, height = self.sel
        gap = 10
        if y + height + gap + th <= self.sh:
            top = y + height + gap
        elif y - gap - th >= 0:
            top = y - gap - th
        else:
            top = max(0, self.sh - th - 8)
        left = min(max(0, x), max(0, self.sw - tw - 4))
        self.toolbar.place(x=int(left), y=int(top))
        self.toolbar.lift()

    def _raise_ui(self) -> None:
        for tag in ("bright", "anno", "preview", "selui", "badge", "hint", "badgetext", "hinttext"):
            self.canvas.tag_raise(tag)
        if self.toolbar.winfo_ismapped():
            self.toolbar.lift()

    def _preview_shape(self, end: tuple[float, float]) -> None:
        self.canvas.delete("preview")
        if self.tool in ("pen", "highlight"):
            anno = Anno(self.tool, list(self._points), self.color, self.stroke)
        else:
            x1, y1 = constrain_square(self._origin[0], self._origin[1], end[0], end[1], self._shift)
            anno = Anno(self.tool, [self._origin, (x1, y1)], self.color, self.stroke)
        self._paint(anno, preview=True)
        self.canvas.tag_raise("preview")

    def _finish_shape(self, end: tuple[float, float]) -> None:
        self.canvas.delete("preview")
        if self.tool in ("pen", "highlight"):
            if len(self._points) < 2:
                return
            anno = Anno(self.tool, list(self._points), self.color, self.stroke)
        else:
            x1, y1 = constrain_square(self._origin[0], self._origin[1], end[0], end[1], self._shift)
            if math.hypot(x1 - self._origin[0], y1 - self._origin[1]) < 3:
                return
            anno = Anno(self.tool, [self._origin, (x1, y1)], self.color, self.stroke)
        self._commit(anno)

    def _commit(self, anno: Anno, clear_redo: bool = True) -> None:
        if clear_redo:
            self.redo.clear()
        self.annos.append(anno)
        self.item_ids.append(self._paint(anno))
        self._refresh_history_buttons()
        self._raise_ui()

    def _paint(self, anno: Anno, preview: bool = False) -> list[int]:
        tag = "preview" if preview else "anno"
        color = anno.color
        width = max(1, anno.width)
        ids: list[int] = []
        pts = anno.points
        if anno.kind in ("pen", "highlight") and len(pts) >= 2:
            flat = [value for point in pts for value in point]
            line_width = max(18, width * 6) if anno.kind == "highlight" else width
            options = {"stipple": "gray50"} if anno.kind == "highlight" else {}
            ids.append(
                self.canvas.create_line(
                    *flat,
                    fill=color,
                    width=line_width,
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND,
                    smooth=anno.kind == "pen",
                    tags=tag,
                    **options,
                )
            )
        elif anno.kind == "line" and len(pts) >= 2:
            ids.append(
                self.canvas.create_line(
                    pts[0][0], pts[0][1], pts[-1][0], pts[-1][1], fill=color, width=width, capstyle=tk.ROUND, tags=tag
                )
            )
        elif anno.kind == "arrow" and len(pts) >= 2:
            from lightshort.render import arrow_parts

            shaft, head = arrow_parts(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1], width)
            ids.append(
                self.canvas.create_line(
                    shaft[0], shaft[1], shaft[2], shaft[3], fill=color, width=width, capstyle=tk.ROUND, tags=tag
                )
            )
            ids.append(self.canvas.create_polygon(*[n for p in head for n in p], fill=color, outline=color, tags=tag))
        elif anno.kind == "rect" and len(pts) >= 2:
            ids.append(
                self.canvas.create_rectangle(
                    pts[0][0], pts[0][1], pts[-1][0], pts[-1][1], outline=color, width=width, tags=tag
                )
            )
        elif anno.kind == "ellipse" and len(pts) >= 2:
            ids.append(
                self.canvas.create_oval(
                    pts[0][0], pts[0][1], pts[-1][0], pts[-1][1], outline=color, width=width, tags=tag
                )
            )
        elif anno.kind == "text" and anno.text and pts:
            ids.append(
                self.canvas.create_text(
                    pts[0][0],
                    pts[0][1],
                    text=anno.text,
                    anchor="nw",
                    fill=color,
                    font=("Segoe UI", -anno.font_size),
                    tags=tag,
                )
            )
        return ids

    def undo(self) -> None:
        if not self.annos:
            return
        self.redo.append(self.annos.pop())
        for item in self.item_ids.pop():
            self.canvas.delete(item)
        self._refresh_history_buttons()

    def redo_anno(self) -> None:
        if not self.redo:
            return
        self._commit(self.redo.pop(), clear_redo=False)

    def _begin_text(self, x: int, y: int) -> None:
        self.text_entry = tk.Entry(
            self.canvas,
            font=("Segoe UI", -self.font_size),
            fg=self.color,
            bg=contrast_bg(self.color),
            insertbackground=self.color,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.color,
            width=8,
        )
        self.text_at = (x, y)
        self.text_window = self.canvas.create_window(x, y, window=self.text_entry, anchor="nw")
        self.text_entry.focus_set()
        self.text_entry.bind("<Return>", self._entry_return)
        self.text_entry.bind("<Escape>", self._entry_escape)
        self.text_entry.bind("<KeyRelease>", self._grow_entry)

    def _grow_entry(self, _event=None) -> None:
        if self.text_entry is not None:
            self.text_entry.configure(width=max(8, len(self.text_entry.get()) + 1))

    def _entry_return(self, _event):
        self._commit_text()
        return "break"

    def _entry_escape(self, _event):
        self._cancel_text()
        return "break"

    def _commit_text(self) -> None:
        if self.text_entry is None:
            return
        text = self.text_entry.get().strip()
        x, y = self.text_at
        font_size = self.font_size
        color = self.color
        self._destroy_text_entry()
        if text:
            self._commit(Anno("text", [(x, y)], color, self.stroke, font_size, text))

    def _cancel_text(self) -> None:
        self._destroy_text_entry()

    def _destroy_text_entry(self) -> None:
        if self.text_window is not None:
            self.canvas.delete(self.text_window)
            self.text_window = None
        if self.text_entry is not None:
            self.text_entry.destroy()
            self.text_entry = None

    def result_image(self) -> Image.Image | None:
        if not self.sel:
            return None
        return render(self.base, self.sel, self.annos)

    def copy(self, close: bool) -> None:
        image = self.result_image()
        if image is None:
            return
        try:
            copy_image(image)
        except OSError as exc:
            self.status.set("Copy failed")
            log(f"clipboard error: {exc}")
            return
        self.status.set("Copied")
        self.on_notify("Copied to the clipboard. Paste with Ctrl+V.")
        if close:
            self.close()

    def save(self, choose: bool, close: bool) -> None:
        image = self.result_image()
        if image is None:
            return
        folder = pictures_dir() / "LightShort"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.status.set("Could not create the save folder")
            log(f"folder error: {exc}")
            return
        path = self._next_path(folder)
        if choose:
            try:
                self.win.grab_release()
            except tk.TclError:
                pass
            self.win.attributes("-topmost", False)
            chosen = filedialog.asksaveasfilename(
                parent=self.win,
                title="Save screenshot",
                initialdir=str(folder),
                initialfile=path.name,
                defaultextension=".png",
                filetypes=[("PNG image", "*.png")],
            )
            self.win.attributes("-topmost", True)
            try:
                self.win.grab_set()
            except tk.TclError:
                pass
            self.win.focus_force()
            if not chosen:
                return
            path = Path(chosen)
        try:
            image.save(path, "PNG")
        except OSError as exc:
            self.status.set("Save failed")
            log(f"save error: {exc}")
            return
        self.status.set(f"Saved {path.name}")
        self.on_notify(f"Saved to {path}")
        if close:
            self.close()

    def _next_path(self, folder: Path) -> Path:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = folder / f"Screenshot_{stamp}.png"
        if path.exists():
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
            path = folder / f"Screenshot_{stamp}.png"
        return path
