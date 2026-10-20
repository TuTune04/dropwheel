"""Vòng tròn kiểu A (thiết kế §7): một vành liền mạch 4 ô, tâm hiện tên thao tác, có chuyển động."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo
from gi.repository import Gtk4LayerShell as LS

from . import hypr

NAMESPACE = "dropwheel"
SIZE = 290
R_OUT, R_IN, R_HUB = 110, 46, 44
BULGE_OUT, BULGE_IN = 9, 3            # ô được rê vào phồng ra (px)

CREAM = (1.0, 0.973, 0.941, 0.93)
ORANGE = (0.941, 0.353, 0.157, 0.97)
INK = (0.23, 0.165, 0.133)

STAGGER, POP = 0.045, 0.32          # giây
AUTO_HIDE_MS, LEAVE_HIDE_MS = 2000, 1000   # user: không có file thì chỉ hiện 2 giây


@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    icon: str
    hint: str


SLOTS = (Slot("mp4", "MP4", "🎞", "Đổi sang MP4"),
         Slot("compress", "Nén", "🗜", "Nhẹ để gửi Zalo"),
         Slot("cut", "Cắt/Crop", "✂", "Mở cửa sổ cắt"),
         Slot("logo", "Logo", "🧽", "Xóa watermark"))


def ease_out_back(t: float, s: float = 1.9) -> float:
    t = min(max(t, 0.0), 1.0) - 1
    return t * t * ((s + 1) * t + s) + 1


def ease_in_back(t: float, s: float = 1.7) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * ((s + 1) * t - s)


def ease_out_cubic(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


class Wheel:
    def __init__(self, app: Gtk.Application, on_drop: Callable[[str, list[Path]], None]):
        self.on_drop = on_drop
        self.win = Gtk.Window(application=app)
        self.win.add_css_class("dropwheel")
        self.win.set_default_size(SIZE, SIZE)
        self.win.set_decorated(False)
        LS.init_for_window(self.win)
        LS.set_namespace(self.win, NAMESPACE)
        LS.set_layer(self.win, LS.Layer.OVERLAY)
        LS.set_anchor(self.win, LS.Edge.TOP, True)
        LS.set_anchor(self.win, LS.Edge.LEFT, True)
        LS.set_exclusive_zone(self.win, -1)
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)

        self.area = Gtk.DrawingArea(content_width=SIZE, content_height=SIZE)
        self.area.set_draw_func(self._draw)
        self.win.set_child(self.area)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop.connect("enter", self._on_enter)
        drop.connect("motion", self._on_motion)
        drop.connect("leave", self._on_leave)
        drop.connect("drop", self._on_drop)
        self.area.add_controller(drop)

        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_: self.close())
        self.area.add_controller(click)

        self.visible = False
        self.t_open = 0.0
        self.t_close: float | None = None    # bắt đầu thu lại
        self.t_drop: float | None = None     # bắt đầu hiệu ứng ✓
        self._close_len = 0.2
        self.hover: int | None = None
        self.hot = [0.0] * len(SLOTS)        # 0..1, mượt dần theo hover
        self.label = "Thả vào ô"
        self.t_label = 0.0
        self.last = 0.0
        self.timer = 0
        self.tick_id = 0
        self._warm_up()

    def _warm_up(self):
        """Vẽ thử một lần ra ảnh trong bộ nhớ để nạp sẵn font/emoji: lần Alt+Q đầu tiên không bị chậm."""
        import cairo
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
        self.t_open = time.monotonic() - 5
        self._draw(None, cairo.Context(surf), SIZE, SIZE)

    # --- hiện / ẩn ------------------------------------------------------------
    def show(self):
        t0 = time.perf_counter()
        x, y, mon = hypr.cursor_and_monitor()
        for gm in Gdk.Display.get_default().get_monitors():
            if gm.get_connector() == mon["name"]:
                LS.set_monitor(self.win, gm)
                geo = gm.get_geometry()
                mw, mh = geo.width, geo.height
                break
        else:
            mw, mh = 10_000, 10_000
        left = min(max(0, int(x - mon["x"] - SIZE / 2)), max(0, mw - SIZE))
        top = min(max(0, int(y - mon["y"] - SIZE / 2)), max(0, mh - SIZE))
        LS.set_margin(self.win, LS.Edge.LEFT, left)
        LS.set_margin(self.win, LS.Edge.TOP, top)

        now = time.monotonic()
        self.t_open, self.t_close, self.t_drop = now, None, None
        self.hover, self.hot = None, [0.0] * len(SLOTS)
        self._set_label("Thả vào ô", now)
        self.visible = True
        self.win.present()
        self._animate()
        self._arm(AUTO_HIDE_MS)
        return (time.perf_counter() - t0) * 1000

    def close(self, fast: bool = True):
        if not self.visible or self.t_close is not None:
            return
        self.t_close = time.monotonic()
        self._close_len = 0.2 if fast else 0.45
        self._animate()

    def _hide_now(self):
        self.visible = False
        self.win.set_visible(False)
        self._disarm()

    def _arm(self, ms: int):
        self._disarm()
        self.timer = GLib.timeout_add(ms, self._timeout)

    def _disarm(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    def _timeout(self):
        self.timer = 0
        self.close()
        return GLib.SOURCE_REMOVE

    # --- chuyển động ------------------------------------------------------------
    def _animate(self):
        if not self.tick_id:
            self.last = time.monotonic()
            self.tick_id = self.area.add_tick_callback(self._tick)

    def _tick(self, _w, _clock):
        now = time.monotonic()
        dt, self.last = now - self.last, now
        settled = True
        k = min(1.0, dt * 16)
        for i in range(len(SLOTS)):
            target = 1.0 if i == self.hover else 0.0
            self.hot[i] += (target - self.hot[i]) * k
            if abs(target - self.hot[i]) > 0.003:
                settled = False
        if now - self.t_open < STAGGER * len(SLOTS) + POP or now - self.t_label < 0.15:
            settled = False
        if self.t_close is not None:
            if now - self.t_close >= self._close_len + (0.25 if self.t_drop else 0):
                self.tick_id = 0
                self._hide_now()
                return GLib.SOURCE_REMOVE
            settled = False
        self.area.queue_draw()
        if settled:
            self.tick_id = 0
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _set_label(self, text: str, now: float):
        if text != self.label:
            self.label, self.t_label = text, now

    # --- kéo thả -----------------------------------------------------------------
    def slot_at(self, x: float, y: float) -> int | None:
        dx, dy = x - SIZE / 2, y - SIZE / 2
        r = math.hypot(dx, dy)
        if r < R_IN or r > R_OUT * 1.08:
            return None
        ang = (math.degrees(math.atan2(dy, dx)) + 90 + 45) % 360
        return int(ang // 90)

    def _on_enter(self, t, x, y):
        self._disarm()
        return self._on_motion(t, x, y)

    def _on_motion(self, t, x, y):
        if self.t_close is not None:
            return 0
        s = self.slot_at(x, y)
        if s != self.hover:
            self.hover = s
            self._set_label(SLOTS[s].label if s is not None else "Thả vào ô", time.monotonic())
            self._animate()
        if s is None:
            return 0
        drop = t.get_current_drop()
        offered = drop.get_actions() if drop else 0
        # Nautilus chỉ đề nghị MOVE. Nhận MOVE nhưng không bao giờ đụng tới file gốc.
        return Gdk.DragAction.COPY if offered & Gdk.DragAction.COPY else Gdk.DragAction.MOVE

    def _on_leave(self, _t):
        if self.t_close is None:
            self.hover = None
            self._set_label("Thả vào ô", time.monotonic())
            self._animate()
            self._arm(LEAVE_HIDE_MS)

    def _on_drop(self, _t, value, x, y):
        s = self.slot_at(x, y)
        if s is None or self.t_close is not None:
            self.close()
            return False
        paths = [Path(f.get_path()) for f in value.get_files() if f.get_path()]
        if not paths:
            self.close()
            return False
        self.hover = s
        now = time.monotonic()
        self.t_drop = now
        self.t_close = now
        self._close_len = 0.45
        self._disarm()
        self._animate()
        GLib.idle_add(lambda: (self.on_drop(SLOTS[s].key, paths), False)[1])
        return True

    # --- vẽ ------------------------------------------------------------------------
    def _draw(self, _a, cr, w, h):
        now = time.monotonic()
        cx, cy = w / 2, h / 2
        t = now - self.t_open
        if self.t_close is not None:
            c = min(1.0, (now - self.t_close) / self._close_len)
            close_scale = 1 - 0.75 * ease_in_back(c) if self.t_drop else 1 - 0.08 * c
            close_alpha = max(0.0, 1 - c) if not self.t_drop else max(0.0, 1 - c * c)
        else:
            close_scale, close_alpha = 1.0, 1.0

        grow = 0.6 + 0.4 * ease_out_back(t / 0.34, 1.6)
        sweep = 2 * math.pi * ease_out_cubic(t / 0.3)   # vành quét một vòng từ đỉnh
        top = -math.pi / 2

        cr.save()
        cr.translate(cx, cy)
        cr.scale(grow * close_scale, grow * close_scale)
        if sweep < 2 * math.pi - 1e-3:
            cr.move_to(0, 0)
            cr.arc(0, 0, R_OUT + BULGE_OUT + 20, top, top + sweep)
            cr.close_path()
            cr.clip()

        # bóng mềm dưới cả vành
        for k, a in ((7, 0.06), (4, 0.09), (2, 0.1)):
            self._annulus(cr, R_IN - 1, R_OUT + k * 0.6, dy=k)
            cr.set_source_rgba(0.25, 0.08, 0.03, a * close_alpha)
            cr.fill()

        # nền vành liền một khối
        self._annulus(cr, R_IN, R_OUT)
        cr.set_source_rgba(*CREAM[:3], CREAM[3] * close_alpha)
        cr.fill()

        # ô đang rê vào: phồng ra, liền với vành
        for i in range(len(SLOTS)):
            hot = self.hot[i]
            if hot < 0.01:
                continue
            mid = top + i * math.pi / 2
            ro, ri = R_OUT + BULGE_OUT * hot, R_IN - BULGE_IN * hot
            self._sector(cr, mid - math.pi / 4, mid + math.pi / 4, ri, ro)
            cr.set_source_rgba(*ORANGE[:3], ORANGE[3] * hot * close_alpha)
            cr.fill()

        # vạch chia mảnh, mờ đi khi ô bên cạnh đang sáng
        cr.set_line_width(1.2)
        for i in range(len(SLOTS)):
            a = top + math.pi / 4 + i * math.pi / 2
            fade = 1 - max(self.hot[i], self.hot[(i + 1) % len(SLOTS)])
            cr.set_source_rgba(*INK, 0.13 * fade * close_alpha)
            cr.move_to((R_IN + 8) * math.cos(a), (R_IN + 8) * math.sin(a))
            cr.line_to((R_OUT - 8) * math.cos(a), (R_OUT - 8) * math.sin(a))
            cr.stroke()

        # viền sáng kiểu kính
        cr.set_line_width(1)
        cr.arc(0, 0, R_OUT - 0.5, 0, 2 * math.pi)
        cr.set_source_rgba(1, 1, 1, 0.7 * close_alpha)
        cr.stroke()
        cr.arc(0, 0, R_IN + 0.5, 0, 2 * math.pi)
        cr.set_source_rgba(*INK, 0.08 * close_alpha)
        cr.stroke()

        # biểu tượng + chữ: hiện so le, trượt nhẹ ra ngoài
        for i, slot in enumerate(SLOTS):
            p = ease_out_cubic((t - 0.1 - i * STAGGER) / 0.2)
            if p <= 0:
                continue
            hot = self.hot[i]
            mid = top + i * math.pi / 2
            rr = (R_IN + R_OUT) / 2 + 2 - 6 * (1 - p) + 3 * hot
            tx, ty = rr * math.cos(mid), rr * math.sin(mid)
            ink = lerp(INK, (1, 1, 1), hot)
            alpha = p * close_alpha
            self._text(cr, slot.icon, tx, ty - 9, 17 + 2 * hot, (*ink, alpha))
            self._text(cr, slot.label, tx, ty + 11, 10.5, (*ink, alpha), bold=True)
        cr.restore()

        # tâm
        if self.t_drop is None:
            hub = ease_out_back(t / 0.3, 1.8) * close_scale
            cr.save()
            cr.translate(cx, cy)
            cr.scale(max(hub, 0.01), max(hub, 0.01))
            cr.arc(0, 0, R_HUB, 0, 2 * math.pi)
            cr.set_source_rgba(1, 1, 1, 0.94 * close_alpha)
            cr.fill()
            la = ease_out_cubic((now - self.t_label) / 0.14) * close_alpha
            if self.hover is None:
                self._text(cr, self.label, 0, 0, 9.5, (*INK, la * 0.8), bold=True, width=R_HUB * 1.7)
            else:
                slot = SLOTS[self.hover]
                self._text(cr, slot.label, 0, -6, 11.5, (*ORANGE[:3], la), bold=True, width=R_HUB * 1.8)
                self._text(cr, slot.hint, 0, 10, 7.5, (*INK, la * 0.75), width=R_HUB * 1.8)
            cr.restore()
        else:
            td = now - self.t_drop
            sc = ease_out_back(td / 0.3, 2.4) * (1 - 0.1 * max(0, td - 0.3))
            a = 1.0 if td < 0.45 else max(0.0, 1 - (td - 0.45) / 0.25)
            cr.save()
            cr.translate(cx, cy)
            cr.scale(max(sc, 0.01), max(sc, 0.01))
            cr.arc(0, 0, 32, 0, 2 * math.pi)
            cr.set_source_rgba(0.086, 0.639, 0.29, a)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, a)
            cr.set_line_width(5)
            cr.set_line_cap(1)
            cr.set_line_join(1)
            cr.move_to(-12, 1)
            cr.line_to(-3, 10)
            cr.line_to(13, -8)
            cr.stroke()
            cr.restore()

    @staticmethod
    def _annulus(cr, ri, ro, dy=0.0):
        cr.new_path()
        cr.arc(0, dy, ro, 0, 2 * math.pi)
        cr.new_sub_path()
        cr.arc_negative(0, dy, ri, 2 * math.pi, 0)
        cr.close_path()

    @staticmethod
    def _sector(cr, a0, a1, ri, ro):
        cr.new_path()
        cr.arc(0, 0, ro, a0, a1)
        cr.arc_negative(0, 0, ri, a1, a0)
        cr.close_path()

    @staticmethod
    def _text(cr, text, x, y, size, rgba, bold=False, width=None):
        layout = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription.from_string(f"sans {'Bold' if bold else ''} {size}")
        layout.set_font_description(fd)
        if width:
            layout.set_width(int(width * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD)
        layout.set_alignment(Pango.Alignment.CENTER)
        layout.set_text(text, -1)
        _ink, logical = layout.get_pixel_extents()
        cr.set_source_rgba(*rgba)
        cr.move_to(x - (width / 2 if width else logical.width / 2), y - logical.height / 2)
        PangoCairo.show_layout(cr, layout)
