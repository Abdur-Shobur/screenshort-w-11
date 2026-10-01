"""Small JSON settings stored under %APPDATA%\\LightShort."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "LightShort"

DEFAULTS = {
    "hotkey_f1": True,
    "hotkey_printscreen": True,
    "start_with_windows": False,
    "seen_welcome": False,
    "color": "#ff3b30",
    "stroke": 4,
    "font_size": 20,
    "tool": "arrow",
}


def log(message: str) -> None:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        with (APP_DIR / "log.txt").open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (APP_DIR / "settings.json")
        self.data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(stored, dict):
            self.data.update({key: stored[key] for key in DEFAULTS if key in stored})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def get(self, key: str):
        return self.data.get(key, DEFAULTS[key])

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()
