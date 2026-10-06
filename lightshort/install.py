"""Per-user installer used by LightShort-Setup.exe."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from lightshort.winutil import create_shortcut, desktop_dir, known_folder, set_run_at_startup

CSIDL_PROGRAMS = 0x0002
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(local) / "Programs" / "LightShort"


def install_exe() -> Path:
    return install_dir() / "LightShort.exe"


def programs_folder() -> Path:
    fallback = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return known_folder(CSIDL_PROGRAMS, fallback) / "LightShort"


def is_installed_copy() -> bool:
    if not getattr(sys, "frozen", False):
        return False
    try:
        current = str(Path(sys.executable).resolve())
        target = install_exe()
        if not target.exists():
            return False
        return current.casefold() == str(target.resolve()).casefold()
    except OSError:
        return False


def handle_install() -> bool:
    """Install, reinstall, or uninstall. Return True when this process should exit."""
    if not getattr(sys, "frozen", False):
        return False
    if "--uninstall" in sys.argv or "--uninstall-silent" in sys.argv:
        uninstall(silent="--uninstall-silent" in sys.argv)
        return True
    if is_installed_copy():
        return False
    if "--install-silent" in sys.argv:
        install_files()
        return True
    run_setup_window()
    return True


def install_files() -> Path:
    source = Path(sys.executable).resolve()
    target = install_exe()
    target.parent.mkdir(parents=True, exist_ok=True)
    if str(source).casefold() != str(target).casefold():
        _replace_exe(source, target)
    _create_shortcuts(target)
    set_run_at_startup(True, f'"{target}"')
    _remember_startup()
    stale = target.with_name("LightShort.exe.old")
    if stale.exists():
        try:
            stale.unlink()
        except OSError:
            pass
    return target


def _replace_exe(source: Path, target: Path) -> None:
    if target.exists():
        stale = target.with_name("LightShort.exe.old")
        try:
            if stale.exists():
                stale.unlink()
        except OSError:
            pass
        try:
            target.replace(stale)
        except OSError:
            pass
    shutil.copy2(source, target)


def _remember_startup() -> None:
    from lightshort.settings import Settings

    Settings().set("start_with_windows", True)


def _create_shortcuts(target: Path) -> None:
    workdir = str(target.parent)
    executable = str(target)
    create_shortcut(desktop_dir() / "LightShort.lnk", executable, workdir=workdir)
    folder = programs_folder()
    create_shortcut(folder / "LightShort.lnk", executable, workdir=workdir)
    create_shortcut(
        folder / "Uninstall LightShort.lnk",
        executable,
        arguments="--uninstall",
        workdir=workdir,
        description="Uninstall LightShort",
    )


def launch_installed() -> None:
    target = install_exe()
    subprocess.Popen(
        [str(target)],
        cwd=str(target.parent),
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def uninstall(silent: bool = False) -> None:
    if not silent and not _confirm_uninstall():
        return
    _remove_shortcuts()
    try:
        set_run_at_startup(False)
    except OSError:
        pass
    folder = install_dir()
    command = f'ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{folder}"'
    subprocess.Popen(
        ["cmd", "/c", command],
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


def _remove_shortcuts() -> None:
    paths = [
        desktop_dir() / "LightShort.lnk",
        programs_folder() / "LightShort.lnk",
        programs_folder() / "Uninstall LightShort.lnk",
    ]
    for path in paths:
        try:
            path.unlink()
        except OSError:
            pass
    try:
        programs_folder().rmdir()
    except OSError:
        pass


def _confirm_uninstall() -> bool:
    import tkinter as tk

    answer = {"ok": False}
    root = tk.Tk()
    root.title("Uninstall LightShort")
    root.configure(bg="#1c1c1e")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    width, height = 420, 200
    root.geometry(f"{width}x{height}+{(root.winfo_screenwidth() - width) // 2}+{(root.winfo_screenheight() - height) // 2}")
    tk.Label(root, text="Uninstall LightShort?", bg="#1c1c1e", fg="#ffffff", font=("Segoe UI", 16, "bold")).pack(pady=(22, 8))
    tk.Label(
        root,
        text="Shortcuts will be removed.\nScreenshots already saved in Pictures stay where they are.",
        bg="#1c1c1e",
        fg="#d1d1d6",
        font=("Segoe UI", 10),
        justify="center",
    ).pack(padx=24)

    def accept() -> None:
        answer["ok"] = True
        root.destroy()

    buttons = tk.Frame(root, bg="#1c1c1e")
    buttons.pack(pady=16)
    tk.Button(
        buttons,
        text="Uninstall",
        command=accept,
        bg="#ff453a",
        fg="#ffffff",
        activebackground="#d73229",
        activeforeground="#ffffff",
        relief="flat",
        padx=14,
        pady=6,
        font=("Segoe UI", 10, "bold"),
        cursor="hand2",
    ).pack(side="left", padx=6)
    tk.Button(
        buttons,
        text="Cancel",
        command=root.destroy,
        bg="#2a2a2c",
        fg="#f5f5f7",
        activebackground="#3a3a3c",
        activeforeground="#ffffff",
        relief="flat",
        padx=14,
        pady=6,
        font=("Segoe UI", 10),
        cursor="hand2",
    ).pack(side="left", padx=6)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return answer["ok"]


def run_setup_window() -> None:
    import tkinter as tk

    root = tk.Tk()
    root.title("LightShort Setup")
    root.configure(bg="#1c1c1e")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    width, height = 460, 280
    root.update_idletasks()
    root.geometry(
        f"{width}x{height}+{(root.winfo_screenwidth() - width) // 2}+{(root.winfo_screenheight() - height) // 2}"
    )
    tk.Label(root, text="Install LightShort", bg="#1c1c1e", fg="#ffffff", font=("Segoe UI", 18, "bold")).pack(pady=(22, 8))
    tk.Label(
        root,
        text=(
            "Screenshot tool for Windows 11.\n"
            "Press F1 or Print Screen, then drag to select an area.\n\n"
            f"Installs to:\n{install_dir()}"
        ),
        bg="#1c1c1e",
        fg="#d1d1d6",
        font=("Segoe UI", 10),
        justify="center",
    ).pack(padx=28)
    status = tk.StringVar(value="")
    tk.Label(root, textvariable=status, bg="#1c1c1e", fg="#ff9f0a", font=("Segoe UI", 9)).pack(pady=(8, 0))

    def accept() -> None:
        status.set("Installing...")
        root.update()
        try:
            install_files()
            launch_installed()
        except Exception as exc:
            status.set(f"Install failed: {exc}")
            return
        root.destroy()

    buttons = tk.Frame(root, bg="#1c1c1e")
    buttons.pack(pady=14)
    label = "Reinstall" if install_exe().exists() else "Install"
    tk.Button(
        buttons,
        text=label,
        command=accept,
        bg="#0a84ff",
        fg="#ffffff",
        activebackground="#0066cc",
        activeforeground="#ffffff",
        relief="flat",
        padx=16,
        pady=6,
        font=("Segoe UI", 10, "bold"),
        cursor="hand2",
    ).pack(side="left", padx=6)
    tk.Button(
        buttons,
        text="Cancel",
        command=root.destroy,
        bg="#2a2a2c",
        fg="#f5f5f7",
        activebackground="#3a3a3c",
        activeforeground="#ffffff",
        relief="flat",
        padx=16,
        pady=6,
        font=("Segoe UI", 10),
        cursor="hand2",
    ).pack(side="left", padx=6)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
