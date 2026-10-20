"""dropwheel daemon | show | cut <file> | logo <file> | quit | ping"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

USAGE = "Cách dùng: dropwheel daemon | show | cut <file> | logo <file> | quit | ping"


def state_dir() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    d = base / "dropwheel"
    d.mkdir(parents=True, exist_ok=True)
    return d


def main(argv: list[str]) -> int:
    if not argv:
        print(USAGE)
        return 2
    cmd = argv[0]
    if cmd == "daemon":
        logging.basicConfig(
            level=logging.DEBUG if os.environ.get("DROPWHEEL_DEBUG") else logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            handlers=[logging.FileHandler(state_dir() / "dropwheel.log"), logging.StreamHandler()])
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        gi.require_version("Gtk4LayerShell", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from .app import App
        return App().run([sys.argv[0]])

    from .ipc import send  # không cần GTK cho phía gửi lệnh
    if cmd in ("show", "quit", "ping"):
        msg = cmd
    elif cmd in ("cut", "logo") and len(argv) == 2:
        msg = f"edit-{cmd} {Path(argv[1]).resolve()}"
    else:
        print(USAGE)
        return 2
    if not send(msg):
        print("dropwheel chưa chạy (thiếu `dropwheel daemon`)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
