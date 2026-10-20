#!/usr/bin/env python3
"""THROWAWAY SPIKE: kiểm tra trên Hyprland có thể
1) bấm phím lúc đang kéo file từ Nautilus để hiện vòng tròn, và
2) vòng tròn (layer-shell) nhận được file thả vào hay không.

Chạy:  python3 wheel_spike.py
Hiện vòng tròn:  kill -USR1 $(cat <PIDFILE>)   (gán vào phím bằng hyprctl)
Cần: LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so
"""
import json
import os
import math
import signal
import subprocess
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LS  # noqa: E402

SIZE = 360
R_OUT, R_IN = 170, 55
SLOTS = ["MP4", "NÉN", "CẮT/CROP", "LOGO"]
PIDFILE = "/tmp/claude-1000/-home-tutusk4-Documents-Project/b44eed95-b09c-4e16-8d42-ddffe4a4f9f7/scratchpad/dropwheel-spike.pid"
LOG = "/tmp/claude-1000/-home-tutusk4-Documents-Project/b44eed95-b09c-4e16-8d42-ddffe4a4f9f7/scratchpad/dropwheel-spike.log"


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def hypr(cmd):
    return json.loads(subprocess.run(["hyprctl", "-j", cmd], capture_output=True, text=True).stdout)


class Wheel(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="dev.dropwheel.spike",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.win = None
        self.hover = None
        self.status = ""
        self.hide_id = 0
        self.shown_at = 0.0

    def do_activate(self):
        self.hold()
        css = Gtk.CssProvider()
        css.load_from_string("window, .bg { background: transparent; }")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        win = Gtk.Window(application=self)
        win.set_default_size(SIZE, SIZE)
        LS.init_for_window(win)
        LS.set_layer(win, LS.Layer.OVERLAY)
        LS.set_anchor(win, LS.Edge.TOP, True)
        LS.set_anchor(win, LS.Edge.LEFT, True)
        LS.set_exclusive_zone(win, -1)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        LS.set_namespace(win, "dropwheel-spike")

        area = Gtk.DrawingArea()
        area.set_content_width(SIZE)
        area.set_content_height(SIZE)
        area.set_draw_func(self.draw)
        self.area = area

        # Nautilus chỉ đề nghị MOVE (actions=2), nên phải nhận cả MOVE.
        # Spike KHÔNG bao giờ đụng tới file; chỉ thử bằng file test để xem Nautilus có tự xóa gốc không.
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop.connect("enter", self.on_enter)
        drop.connect("motion", self.on_motion)
        drop.connect("leave", self.on_leave)
        drop.connect("drop", self.on_drop)
        area.add_controller(drop)

        # Bắt mọi sự kiện kéo đi qua, kể cả khi định dạng/hành động không khớp.
        dm = Gtk.DropControllerMotion()
        dm.connect("enter", lambda c, x, y: log(f"DND MOTION ENTER (raw) {self.describe(c.get_drop())}"))
        dm.connect("leave", lambda c: log("DND MOTION LEAVE (raw)"))
        area.add_controller(dm)

        win.set_child(area)
        self.win = win
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self.show)
        with open(PIDFILE, "w") as f:
            f.write(str(os.getpid()))
        log("spike sẵn sàng; gửi SIGUSR1 để hiện vòng tròn")

    # --- hiện / ẩn -------------------------------------------------------
    def show(self, *_):
        t0 = time.perf_counter()
        cur = hypr("cursorpos")
        mons = hypr("monitors")
        mon = next((m for m in mons
                    if m["x"] <= cur["x"] < m["x"] + m["width"] / m["scale"]
                    and m["y"] <= cur["y"] < m["y"] + m["height"] / m["scale"]), mons[0])
        for gm in Gdk.Display.get_default().get_monitors():
            if gm.get_connector() == mon["name"]:
                LS.set_monitor(self.win, gm)
        LS.set_margin(self.win, LS.Edge.LEFT, int(cur["x"] - mon["x"] - SIZE / 2))
        LS.set_margin(self.win, LS.Edge.TOP, int(cur["y"] - mon["y"] - SIZE / 2))
        self.hover, self.status = None, ""
        self.win.present()
        self.area.queue_draw()
        self.shown_at = time.monotonic()
        log(f"HIỆN tại {cur['x']},{cur['y']} trên {mon['name']} ({(time.perf_counter()-t0)*1000:.0f} ms)")
        self.schedule_hide(8000, "không có file kéo vào trong 8 giây")
        return GLib.SOURCE_CONTINUE

    def schedule_hide(self, ms, why):
        if self.hide_id:
            GLib.source_remove(self.hide_id)
        def _hide():
            self.hide_id = 0
            self.win.set_visible(False)
            log(f"ẨN ({why})")
            return GLib.SOURCE_REMOVE
        self.hide_id = GLib.timeout_add(ms, _hide)

    def cancel_hide(self):
        if self.hide_id:
            GLib.source_remove(self.hide_id)
            self.hide_id = 0

    # --- kéo thả ---------------------------------------------------------
    def slot_at(self, x, y):
        dx, dy = x - SIZE / 2, y - SIZE / 2
        r = math.hypot(dx, dy)
        if r < R_IN or r > R_OUT:
            return None
        ang = (math.degrees(math.atan2(dy, dx)) + 90 + 45) % 360  # 0 = ô trên cùng
        return int(ang // 90)

    def describe(self, drop):
        if drop is None:
            return "drop=None"
        return f"formats={drop.get_formats().to_string()} actions={drop.get_actions()}"

    def on_enter(self, _t, x, y):
        self.cancel_hide()
        log(f"{self.describe(_t.get_current_drop())} | DRAG ENTER sau {(time.monotonic()-self.shown_at)*1000:.0f} ms kể từ khi hiện")
        return self.on_motion(_t, x, y)

    def on_motion(self, _t, x, y):
        s = self.slot_at(x, y)
        if s != self.hover:
            self.hover = s
            self.area.queue_draw()
        if s is None:
            return 0
        offered = _t.get_current_drop().get_actions() if _t.get_current_drop() else 0
        return Gdk.DragAction.COPY if offered & Gdk.DragAction.COPY else Gdk.DragAction.MOVE

    def on_leave(self, _t):
        self.hover = None
        self.area.queue_draw()
        self.schedule_hide(1200, "file bị kéo ra ngoài")

    def on_drop(self, _t, value, x, y):
        s = self.slot_at(x, y)
        files = [f.get_path() for f in value.get_files()]
        if s is None:
            log(f"THẢ ngoài ô: {files}")
            return False
        self.status = f"✓ {SLOTS[s]}"
        log(f"THẢ vào ô {SLOTS[s]}: {files}")
        self.area.queue_draw()
        self.schedule_hide(900, "đã thả")
        return True

    # --- vẽ --------------------------------------------------------------
    def draw(self, _a, cr, w, h):
        cx, cy = w / 2, h / 2
        for i, name in enumerate(SLOTS):
            a0 = math.radians(-90 - 45 + i * 90 + 2)
            a1 = math.radians(-90 + 45 + i * 90 - 2)
            cr.new_path()
            cr.arc(cx, cy, R_OUT, a0, a1)
            cr.arc_negative(cx, cy, R_IN, a1, a0)
            cr.close_path()
            if i == self.hover:
                cr.set_source_rgba(0.93, 0.36, 0.18, 0.95)
            else:
                cr.set_source_rgba(0.98, 0.88, 0.82, 0.92)
            cr.fill()
            mid = math.radians(-90 + i * 90)
            rr = (R_IN + R_OUT) / 2
            cr.set_source_rgba(0.2, 0.15, 0.12, 1)
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(16)
            ext = cr.text_extents(name)
            cr.move_to(cx + rr * math.cos(mid) - ext.width / 2, cy + rr * math.sin(mid) + ext.height / 2)
            cr.show_text(name)
        if self.status:
            cr.set_source_rgba(0.1, 0.5, 0.2, 1)
            cr.set_font_size(18)
            ext = cr.text_extents(self.status)
            cr.move_to(cx - ext.width / 2, cy + ext.height / 2)
            cr.show_text(self.status)


if __name__ == "__main__":
    Wheel().run(None)
