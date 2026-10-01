"""Global F1 and Print Screen hook.

Only those two keys are watched. Every other key is passed through.
"""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_QUIT = 0x0012
VK_F1 = 0x70
VK_SNAPSHOT = 0x2C
LLKHF_UP = 0x80

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL

kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HotkeyService:
    """Background hook. Capture requests are placed on `events`."""

    def __init__(self) -> None:
        self.events: queue.Queue[str] = queue.Queue()
        self.want_f1 = False
        self.want_printscreen = False
        self.installed = False
        self.error = ""
        self._hook = None
        self._thread_id = 0
        self._last = 0.0
        self._held: set[int] = set()
        self._proc = HOOKPROC(self._callback)
        self._thread = threading.Thread(target=self._loop, name="lightshort-hotkeys", daemon=True)
        self._ready = threading.Event()
        self._thread.start()
        self._ready.wait(3)

    def configure(self, f1: bool, printscreen: bool) -> None:
        self.want_f1 = bool(f1)
        self.want_printscreen = bool(printscreen)

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _callback(self, n_code, w_param, l_param):
        try:
            if n_code == 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN, 0x0101, 0x0105):
                info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                watched = (info.vkCode == VK_F1 and self.want_f1) or (
                    info.vkCode == VK_SNAPSHOT and self.want_printscreen
                )
                if watched:
                    vk = int(info.vkCode)
                    is_up = bool(info.flags & LLKHF_UP)
                    if not is_up:
                        if vk not in self._held:
                            self._held.add(vk)
                            self._fire()
                    else:
                        # Some keyboards only report Print Screen on release.
                        if vk not in self._held:
                            self._fire()
                        self._held.discard(vk)
                    return 1
        except Exception as exc:
            self.error = str(exc)
        if self._hook:
            return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)
        return 0

    def _fire(self) -> None:
        now = time.monotonic()
        if now - self._last < 0.45:
            return
        self._last = now
        self.events.put("capture")

    def _loop(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._proc,
            kernel32.GetModuleHandleW(None),
            0,
        )
        self.installed = bool(self._hook)
        if not self.installed:
            self.error = f"SetWindowsHookExW failed ({ctypes.get_last_error()})"
        self._ready.set()
        message = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result == 0 or result == -1:
                break
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
            self.installed = False
