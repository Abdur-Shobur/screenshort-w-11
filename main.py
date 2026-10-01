"""Start LightShort. A second launch asks the running copy to capture."""

from __future__ import annotations

import sys
import traceback

from lightshort.settings import log
from lightshort.winutil import claim_single_instance, enable_dpi_awareness


def main() -> None:
    enable_dpi_awareness()
    from lightshort.install import handle_install

    if handle_install():
        return
    if not claim_single_instance():
        return
    from lightshort.app import App

    App().run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log(traceback.format_exc())
        sys.exit(1)
