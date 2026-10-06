"""Windows helpers: DPI, single instance, pictures folder, startup."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.SetEvent.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.GetLastError.restype = wintypes.DWORD

user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND

shell32.SHGetFolderPathW.argtypes = [
    wintypes.HWND,
    ctypes.c_int,
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.c_wchar),
]
shell32.SHGetFolderPathW.restype = ctypes.HRESULT

ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0
CSIDL_DESKTOP = 0x0000
CSIDL_MYPICTURES = 0x0027
MUTEX_NAME = "Local\\LightShort.Mutex"
EVENT_NAME = "Local\\LightShort.Capture"

# Kept alive so Windows does not release the single-instance mutex.
_mutex_handle = None
capture_event = None


def enable_dpi_awareness() -> None:
    """Match screenshot pixels to window coordinates on Windows 11."""
    try:
        # PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def claim_single_instance() -> bool:
    """Return False when another LightShort is already running.

    The existing instance is asked to open a capture.
    """
    global _mutex_handle, capture_event
    _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        existing = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, EVENT_NAME)
        if existing:
            kernel32.SetEvent(existing)
            kernel32.CloseHandle(existing)
        return False
    capture_event = kernel32.CreateEventW(None, False, False, EVENT_NAME)
    return True


def second_instance_requested() -> bool:
    if not capture_event:
        return False
    return kernel32.WaitForSingleObject(capture_event, 0) == WAIT_OBJECT_0


def known_folder(csidl: int, fallback: Path) -> Path:
    buffer = ctypes.create_unicode_buffer(260)
    try:
        if shell32.SHGetFolderPathW(None, csidl, None, 0, buffer) == 0 and buffer.value:
            return Path(buffer.value)
    except Exception:
        pass
    return fallback


def pictures_dir() -> Path:
    return known_folder(CSIDL_MYPICTURES, Path.home() / "Pictures")


def desktop_dir() -> Path:
    return known_folder(CSIDL_DESKTOP, Path.home() / "Desktop")


def focus_window(widget_id: int) -> None:
    hwnd = user32.GetAncestor(widget_id, 2) or widget_id
    user32.ShowWindow(hwnd, 5)
    if not user32.SetForegroundWindow(hwnd):
        # Windows blocks focus theft unless an input event is synthesized.
        user32.keybd_event(0x12, 0, 0, 0)
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 2, 0)


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    executable = Path(sys.executable)
    if executable.name.lower() == "python.exe":
        windowless = executable.with_name("pythonw.exe")
        if windowless.exists():
            executable = windowless
    script = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{executable}" "{script}"'


def set_run_at_startup(enabled: bool, command: str | None = None) -> None:
    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    )
    try:
        if enabled:
            winreg.SetValueEx(key, "LightShort", 0, winreg.REG_SZ, command or launch_command())
        else:
            try:
                winreg.DeleteValue(key, "LightShort")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def create_shortcut(
    link: Path,
    target: str,
    arguments: str = "",
    workdir: str = "",
    icon: str = "",
    description: str = "LightShort screenshot tool",
) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "LS_LINK": str(link),
            "LS_TARGET": target,
            "LS_ARGS": arguments,
            "LS_WORKDIR": workdir or str(Path(target).parent),
            "LS_ICON": icon or target,
            "LS_DESC": description,
        }
    )
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LS_LINK); "
        "$s.TargetPath = $env:LS_TARGET; "
        "$s.Arguments = $env:LS_ARGS; "
        "$s.WorkingDirectory = $env:LS_WORKDIR; "
        "$s.IconLocation = $env:LS_ICON; "
        "$s.Description = $env:LS_DESC; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        env=environment,
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def create_desktop_shortcut(icon_path: Path) -> Path:
    link = desktop_dir() / "LightShort.lnk"
    if getattr(sys, "frozen", False):
        target_path = sys.executable
        arguments = ""
        workdir = str(Path(sys.executable).parent)
    else:
        executable = Path(sys.executable)
        if executable.name.lower() == "python.exe":
            windowless = executable.with_name("pythonw.exe")
            if windowless.exists():
                executable = windowless
        target_path = str(executable)
        arguments = f'"{Path(__file__).resolve().parent.parent / "main.py"}"'
        workdir = str(Path(__file__).resolve().parent.parent)
    create_shortcut(link, target_path, arguments, workdir, str(icon_path))
    return link
