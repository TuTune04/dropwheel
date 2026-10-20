"""Thẻ tiến độ ở góc dưới bên phải (thiết kế §11)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from gi.repository import GLib, Gtk
from gi.repository import Gtk4LayerShell as LS

from .jobs import Event

DONE_HIDE_MS = 4000
SLIDE_MS = 320


def human_size(n: int) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB" if n >= 1e7 else f"{n / 1e6:.1f} MB"
    return f"{max(1, n // 1000)} KB"


class Toast:
    def __init__(self, app: Gtk.Application, cancel_current: Callable[[], None],
                 cancel_all: Callable[[], None]):
        self.win = Gtk.Window(application=app)
        self.win.add_css_class("dropwheel")
        LS.init_for_window(self.win)
        LS.set_namespace(self.win, "dropwheel-toast")
        LS.set_layer(self.win, LS.Layer.OVERLAY)
        LS.set_anchor(self.win, LS.Edge.BOTTOM, True)
        LS.set_anchor(self.win, LS.Edge.RIGHT, True)
        LS.set_margin(self.win, LS.Edge.BOTTOM, 18)
        LS.set_margin(self.win, LS.Edge.RIGHT, 18)
        LS.set_exclusive_zone(self.win, -1)
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)

        self.rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
                                transition_duration=SLIDE_MS)
        self.win.set_child(self.rev)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("dw-card")
        card.set_size_request(280, -1)
        self.card = card
        top = Gtk.Box(spacing=8)
        self.title = Gtk.Label(xalign=0, hexpand=True)
        self.title.add_css_class("dw-title")
        self.count = Gtk.Label()
        self.count.add_css_class("dw-dim")
        self.close_btn = Gtk.Button(label="✕", tooltip_text="Hủy việc đang chạy")
        self.close_btn.add_css_class("dw-x")
        self.close_btn.connect("clicked", lambda *_: self._on_x())
        top.append(self.title)
        top.append(self.count)
        top.append(self.close_btn)
        self.name = Gtk.Label(xalign=0, ellipsize=3)
        self.name.add_css_class("dw-dim")
        self.bar = Gtk.ProgressBar()
        self.bar.add_css_class("dw-bar")
        self.all_btn = Gtk.Button(label="Hủy hết", halign=Gtk.Align.END)
        self.all_btn.add_css_class("dw-link")
        self.all_btn.connect("clicked", lambda *_: cancel_all())
        for w in (top, self.name, self.bar, self.all_btn):
            card.append(w)

        click = Gtk.GestureClick()
        click.connect("released", self._on_card_click)
        card.add_controller(click)
        self.rev.set_child(card)

        self.cancel_current = cancel_current
        self.state = "hidden"
        self.outputs: tuple[Path, ...] = ()
        self.hide_id = 0

    # --- API ----------------------------------------------------------------
    def info(self, title: str, detail: str = "", error: bool = False):
        self._show()
        self._style("error" if error else "info")
        self.title.set_text(title)
        self.name.set_text(detail)
        self.name.set_visible(bool(detail))
        self.bar.set_visible(False)
        self.count.set_text("")
        self.close_btn.set_visible(False)
        self.all_btn.set_visible(False)
        self._hide_later(DONE_HIDE_MS + (2000 if error else 0))

    def handle(self, ev: Event):
        if ev.kind == "idle":
            if self.state == "running":
                self._hide_later(300)
            return
        self._show()
        multi = ev.total > 1
        self.count.set_text(f"{ev.index}/{ev.total}" if multi else "")
        self.all_btn.set_visible(ev.total - ev.index >= 1 and ev.kind in ("start", "progress"))
        name = ev.job.name if ev.job else ""
        if ev.kind == "start":
            self._cancel_hide()
            self.state = "running"
            self._style("info")
            self.title.set_text(ev.message)
            self.name.set_text(name)
            self.name.set_visible(True)
            self.bar.set_visible(True)
            self.bar.set_fraction(0)
            self.close_btn.set_visible(True)
        elif ev.kind == "progress":
            self.bar.set_fraction(ev.fraction)
        elif ev.kind == "done":
            self.state = "done"
            self.outputs = ev.outputs
            self._style("done")
            n = len(ev.outputs)
            self.title.set_text(f"Xong · {human_size(ev.bytes)}" + (f" · {n} file" if n > 1 else ""))
            self.name.set_text(ev.outputs[0].name + "  ·  bấm để mở thư mục")
            self.bar.set_fraction(1)
            self.close_btn.set_visible(False)
            self._hide_later(DONE_HIDE_MS)
        elif ev.kind in ("skipped", "cancelled", "error"):
            self.state = ev.kind
            self._style("error" if ev.kind == "error" else "info")
            self.title.set_text(ev.message)
            self.name.set_text(name)
            self.bar.set_visible(False)
            self.close_btn.set_visible(False)
            self._hide_later(DONE_HIDE_MS + (2000 if ev.kind == "error" else 0))

    # --- nội bộ ---------------------------------------------------------------
    def _style(self, kind: str):
        for c in ("info", "done", "error"):
            self.card.remove_css_class("dw-" + c)
        self.card.add_css_class("dw-" + kind)

    def _show(self):
        self._cancel_hide()
        if not self.win.get_visible():
            self.win.present()
        self.rev.set_reveal_child(True)

    def _hide_later(self, ms: int):
        self._cancel_hide()
        self.hide_id = GLib.timeout_add(ms, self._hide)

    def _cancel_hide(self):
        if self.hide_id:
            GLib.source_remove(self.hide_id)
            self.hide_id = 0

    def _hide(self):
        self.hide_id = 0
        self.rev.set_reveal_child(False)
        GLib.timeout_add(SLIDE_MS + 30, self._unmap)
        return GLib.SOURCE_REMOVE

    def _unmap(self):
        if not self.rev.get_reveal_child():
            self.win.set_visible(False)
            self.state = "hidden"
        return GLib.SOURCE_REMOVE

    def _on_x(self):
        if self.state == "running":
            self.cancel_current()

    def _on_card_click(self, *_):
        if self.state == "done" and self.outputs:
            # Mở thư mục và chọn sẵn file kết quả.
            subprocess.Popen(["nautilus", "--select", str(self.outputs[0])],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._hide_later(200)
