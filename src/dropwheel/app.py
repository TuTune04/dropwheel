"""Tiến trình nền: nối vòng tròn, thẻ tiến độ, cửa sổ chỉnh và hàng đợi."""
from __future__ import annotations

import logging
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk

from . import commands as C
from . import hypr, ipc
from .editor import Editor
from .encoders import has_vaapi
from .jobs import Job, Runner
from .probe import ProbeError, probe
from .toast import Toast
from .wheel import Wheel

log = logging.getLogger(__name__)
APP_ID = "dev.dropwheel"

CSS = """
window.dropwheel { background: transparent; }
.dw-card { background: rgba(255,248,240,0.94); color: #3a2a22; border-radius: 14px; padding: 12px 14px;
           box-shadow: 0 8px 24px rgba(40,15,5,0.28); margin: 10px; }
.dw-card.dw-done { background: rgba(236,253,243,0.96); }
.dw-card.dw-error { background: rgba(254,228,226,0.97); color: #7a1c12; }
.dw-title { font-weight: 700; }
.dw-dim { opacity: 0.7; font-size: 0.9em; }
.dw-x, .dw-link { background: none; border: none; box-shadow: none; color: inherit; padding: 0 4px; min-height: 0; }
.dw-link { font-size: 0.9em; text-decoration: underline; }
.dw-bar trough { min-height: 5px; border-radius: 3px; background: rgba(0,0,0,0.08); }
.dw-bar progress { min-height: 5px; border-radius: 3px; background: #f05a28; }
.dw-editor-root { padding: 14px; }
.dw-view { background: #111; border-radius: 10px; }
.dw-chip { background: alpha(currentColor, 0.08); border-radius: 999px; padding: 0 6px; }
.dw-export { background: #f05a28; color: white; }
.dw-export:disabled { opacity: 0.4; }
.dw-mono { font-family: monospace; }
"""

LAYER_RULE = ('hl.layer_rule({ match = { namespace = "^dropwheel" }, blur = true, '
              'ignore_alpha = 0.3, no_anim = true })')
WINDOW_RULE = ('hl.window_rule({ match = { class = "^dev\\\\.dropwheel$" }, float = true, center = true, size = "86% 88%", opaque = true })')


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.vaapi = False

    def do_startup(self):
        Gtk.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        self.hold()
        for rule in (LAYER_RULE, WINDOW_RULE):
            if not hypr.eval_lua(rule):
                log.warning("Hyprland không nhận quy tắc: %s", rule)
        self.vaapi = has_vaapi()
        log.info("encoder: %s", "h264_vaapi" if self.vaapi else "libx264")
        self.runner = Runner(lambda ev: GLib.idle_add(self._on_event, ev))
        self.toast = Toast(self, self.runner.cancel_current, self.runner.cancel_all)
        self.wheel = Wheel(self, self._on_drop)
        self.server = ipc.Server(self._on_command)
        log.info("dropwheel sẵn sàng")

    def _on_event(self, ev):
        self.toast.handle(ev)
        return False

    def _on_command(self, cmd: str):
        if cmd == "show":
            ms = self.wheel.show()
            log.debug("vòng tròn hiện sau %.1f ms", ms)
        elif cmd.startswith("edit-cut ") or cmd.startswith("edit-logo "):
            kind, path = cmd.split(" ", 1)
            self._open_editor(Path(path), kind.removeprefix("edit-"))
        elif cmd == "quit":
            self.quit()

    # --- thả file ---------------------------------------------------------------
    def _on_drop(self, key: str, paths: list[Path]):
        log.info("thả %d file vào %s", len(paths), key)
        if key in ("mp4", "compress"):
            build = C.mp4 if key == "mp4" else C.compress
            title = "Đang chuyển MP4…" if key == "mp4" else "Đang nén…"
            jobs = [Job(title, (lambda p=p: build(probe(p), self.vaapi)), p.name) for p in paths]
            self.runner.submit(jobs)
            return
        if len(paths) > 1:
            self.toast.info("Chỉ mở file đầu tiên", paths[0].name)
        self._open_editor(paths[0], key)

    def _open_editor(self, path: Path, mode: str):
        try:
            info = probe(path)
        except ProbeError as e:
            self.toast.info(str(e), path.name, error=True)
            return
        win = Editor(self, info, mode, lambda job: self.runner.submit([job]), self.vaapi)
        win.present()
