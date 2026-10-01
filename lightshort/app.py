"""Tray application that owns hotkeys and the capture editor."""

from __future__ import annotations

import os
import queue
import traceback
import tkinter as tk
from pathlib import Path

import pystray
from PIL import ImageTk

from lightshort.hotkeys import HotkeyService
from lightshort.icons import app_icon
from lightshort.overlay import CaptureOverlay
from lightshort.settings import APP_DIR, Settings, log
from lightshort.winutil import create_desktop_shortcut, pictures_dir, second_instance_requested, set_run_at_startup


class App:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.report_callback_exception = self._log_callback_error
        self.icon_image = app_icon(64)
        self.icon_photo = ImageTk.PhotoImage(app_icon(32))
        self.root.iconphoto(True, self.icon_photo)
        self.overlay: CaptureOverlay | None = None
        self.welcome: tk.Toplevel | None = None
        self.quit_requested = False
        self.help_requested = False
        self.hotkeys = HotkeyService()
        self.hotkeys.configure(
            bool(self.settings.get("hotkey_f1")),
            bool(self.settings.get("hotkey_printscreen")),
        )
        self.icon = pystray.Icon(
            "LightShort",
            self.icon_image,
            "LightShort",
            menu=pystray.Menu(self._menu_items),
        )
        self._ensure_ico()
        if not self.settings.get("seen_welcome"):
            self._create_shortcut_quietly()
        self.icon.run_detached(self._tray_ready)
        if not self.hotkeys.installed:
            log(self.hotkeys.error or "hotkey hook was not installed")
        self.root.after(40, self._poll)
        if not self.settings.get("seen_welcome") or not self.hotkeys.installed:
            self.root.after(200, self.show_welcome)

    def _ensure_ico(self) -> Path:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        path = APP_DIR / "LightShort.ico"
        if not path.exists():
            app_icon(256).save(
                path,
                format="ICO",
                sizes=[(16, 16), (32, 32), (48, 48), (256, 256)],
            )
        return path

    def _create_shortcut_quietly(self) -> None:
        try:
            create_desktop_shortcut(self._ensure_ico())
        except Exception as exc:
            log(f"shortcut skipped: {exc}")

    def _tray_ready(self, icon: pystray.Icon) -> None:
        icon.visible = True
        if self.quit_requested:
            icon.stop()
            return
        if self.settings.get("seen_welcome") and self.hotkeys.installed:
            return
        if self.hotkeys.installed:
            message = "Press F1 or Print Screen, then drag to select."
        else:
            message = "Hotkeys are unavailable. Use Take screenshot in the tray menu."
        try:
            icon.notify(message, "LightShort")
        except Exception as exc:
            log(f"notify failed: {exc}")

    def _menu_items(self):
        return (
            pystray.MenuItem("Take screenshot", self._request_capture, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Hotkey: F1", self._toggle_f1, checked=lambda _item: bool(self.settings.get("hotkey_f1"))),
            pystray.MenuItem(
                "Hotkey: Print Screen",
                self._toggle_printscreen,
                checked=lambda _item: bool(self.settings.get("hotkey_printscreen")),
            ),
            pystray.MenuItem(
                "Start with Windows",
                self._toggle_startup,
                checked=lambda _item: bool(self.settings.get("start_with_windows")),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open screenshots folder", self._open_folder),
            pystray.MenuItem("Create desktop shortcut", self._create_shortcut),
            pystray.MenuItem("How to use", self._request_help),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._request_quit),
        )

    def _request_capture(self, _icon=None, _item=None) -> None:
        self.hotkeys.events.put("capture")

    def _request_help(self, _icon=None, _item=None) -> None:
        self.help_requested = True

    def _request_quit(self, _icon=None, _item=None) -> None:
        self.quit_requested = True

    def _toggle_f1(self, icon, _item) -> None:
        enabled = not bool(self.settings.get("hotkey_f1"))
        self.settings.set("hotkey_f1", enabled)
        self.hotkeys.configure(enabled, bool(self.settings.get("hotkey_printscreen")))
        icon.update_menu()

    def _toggle_printscreen(self, icon, _item) -> None:
        enabled = not bool(self.settings.get("hotkey_printscreen"))
        self.settings.set("hotkey_printscreen", enabled)
        self.hotkeys.configure(bool(self.settings.get("hotkey_f1")), enabled)
        icon.update_menu()

    def _toggle_startup(self, icon, _item) -> None:
        enabled = not bool(self.settings.get("start_with_windows"))
        try:
            set_run_at_startup(enabled)
        except OSError as exc:
            log(f"startup toggle failed: {exc}")
            return
        self.settings.set("start_with_windows", enabled)
        icon.update_menu()

    def _open_folder(self, _icon=None, _item=None) -> None:
        folder = pictures_dir() / "LightShort"
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # noqa: S606 - opens the user's own screenshots folder

    def _create_shortcut(self, icon, _item) -> None:
        try:
            path = create_desktop_shortcut(self._ensure_ico())
        except Exception as exc:
            log(f"shortcut failed: {exc}")
            try:
                icon.notify("Could not create the desktop shortcut.", "LightShort")
            except Exception:
                pass
            return
        try:
            icon.notify(f"Shortcut created on the desktop.", "LightShort")
        except Exception:
            pass
        log(f"shortcut created: {path}")

    def _poll(self) -> None:
        if self.quit_requested:
            self._shutdown()
            return
        if self.help_requested:
            self.help_requested = False
            self.show_welcome()
        capture = False
        if second_instance_requested():
            capture = True
        try:
            while True:
                self.hotkeys.events.get_nowait()
                capture = True
        except queue.Empty:
            pass
        if capture:
            self.toggle_capture()
        self.root.after(40, self._poll)

    def toggle_capture(self) -> None:
        self._close_welcome()
        if self.overlay is not None and not self.overlay.closed:
            self.overlay.close()
            return
        try:
            self.overlay = CaptureOverlay(
                self.root,
                self.settings,
                on_close=self._overlay_closed,
                on_notify=self.notify,
            )
        except Exception as exc:
            self.overlay = None
            log(f"capture failed: {exc}")
            self.notify("Could not take a screenshot. See the log in %APPDATA%\\LightShort.")

    def _overlay_closed(self) -> None:
        self.overlay = None

    def _log_callback_error(self, exc_type, value, tb) -> None:
        log("".join(traceback.format_exception(exc_type, value, tb)))

    def notify(self, message: str) -> None:
        try:
            self.icon.notify(message, "LightShort")
        except Exception as exc:
            log(f"notify failed: {exc}")

    def show_welcome(self) -> None:
        if self.welcome is not None:
            try:
                self.welcome.lift()
                return
            except tk.TclError:
                self.welcome = None
        win = tk.Toplevel(self.root)
        self.welcome = win
        win.title("LightShort")
        win.configure(bg="#1c1c1e")
        win.resizable(False, False)
        win.attributes("-topmost", True)
        width, height = 460, 280
        win.update_idletasks()
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        win.geometry(f"{width}x{height}+{max(0, (screen_w - width) // 2)}+{max(0, (screen_h - height) // 2)}")
        tk.Label(win, text="LightShort", bg="#1c1c1e", fg="#ffffff", font=("Segoe UI", 20, "bold")).pack(pady=(22, 8))
        if self.hotkeys.installed:
            body = (
                "Press F1 or Print Screen, then drag to select an area.\n\n"
                "Mark it with arrows, squares, circles, pen, marker, and text.\n"
                "Pick a color, line thickness, and font size on the toolbar.\n\n"
                "Copy stays on the clipboard. Save goes to Pictures\\LightShort.\n"
                "Turn each hotkey on or off from the tray icon."
            )
        else:
            body = (
                "The keyboard hook did not start, so F1 and Print Screen are off.\n\n"
                "Open the tray icon and choose Take screenshot.\n"
                "You can still mark the capture with arrows, squares, color, and text."
            )
        tk.Label(
            win,
            text=body,
            bg="#1c1c1e",
            fg="#d1d1d6",
            font=("Segoe UI", 10),
            justify="center",
        ).pack(padx=28)
        tk.Button(
            win,
            text="OK",
            command=self._close_welcome,
            bg="#0a84ff",
            fg="#ffffff",
            activebackground="#0066cc",
            activeforeground="#ffffff",
            relief="flat",
            padx=18,
            pady=6,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        ).pack(pady=16)
        win.protocol("WM_DELETE_WINDOW", self._close_welcome)
        self.settings.set("seen_welcome", True)
        win.focus_force()

    def _close_welcome(self) -> None:
        if self.welcome is None:
            return
        try:
            self.welcome.destroy()
        except tk.TclError:
            pass
        self.welcome = None

    def _shutdown(self) -> None:
        self.hotkeys.stop()
        if self.overlay is not None and not self.overlay.closed:
            self.overlay.close()
        self._close_welcome()
        try:
            self.icon.stop()
        except Exception:
            pass
        self.root.quit()

    def run(self) -> None:
        log("LightShort started")
        try:
            self.root.mainloop()
        finally:
            self.hotkeys.stop()
            log("LightShort stopped")
