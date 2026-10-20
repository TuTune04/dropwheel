"""Cửa sổ Cắt/Crop (thiết kế §8.3) và chế độ Logo (§8.4)."""
from __future__ import annotations

import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gi.repository import Gdk, GLib, Gtk

from . import commands as C
from .jobs import Job
from .probe import MediaInfo

COLORS = ["#e63946", "#2a9d8f", "#f4a261", "#457b9d", "#9b5de5", "#00bbf9", "#e9c46a", "#ff70a6"]
MIN_SEG = 0.3
TL_PAD = 14
HANDLE_PX = 8


def rgba(hex_: str, a: float = 1.0):
    c = Gdk.RGBA()
    c.parse(hex_)
    return c.red, c.green, c.blue, a


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:04.1f}"


@dataclass
class Seg:
    start: float
    end: float
    cx: float          # tâm khung 9:16 (pixel ảnh gốc)
    cy: float
    color: str


class Editor(Gtk.Window):
    """mode = "cut" | "logo". `submit` nhận Job đã dựng sẵn."""

    def __init__(self, app: Gtk.Application, info: MediaInfo, mode: str,
                 submit: Callable[[Job], None], vaapi: bool):
        super().__init__(application=app, title=("Cắt / Crop" if mode == "cut" else "Xóa logo")
                         + f" — {info.path.name}")
        self.add_css_class("dw-editor")
        self.info, self.mode, self.submit, self.vaapi = info, mode, submit, vaapi
        self.W, self.H, self.dur = info.width, info.height, max(info.duration, 0.1)
        self.segs: list[Seg] = []
        self.sel = 0
        self.rects: list[C.Rect] = []
        self.rect_sel: int | None = None
        self.preview_png: str | None = None
        mon = self._monitor_size()
        self.set_default_size(int(min(1100, mon[0] * 0.86)), int(min(820, mon[1] * 0.88)))

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.add_css_class("dw-editor-root")
        self.set_child(root)

        # --- khung xem -------------------------------------------------------------
        self.media = Gtk.MediaFile.new_for_filename(str(info.path))
        self.media.set_loop(False)
        self.picture = Gtk.Picture(paintable=self.media, content_fit=Gtk.ContentFit.CONTAIN,
                                   hexpand=True, vexpand=True)
        self.still = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, hexpand=True, vexpand=True,
                                 visible=False)
        self.overlay_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.overlay_area.set_draw_func(self._draw_overlay)
        ov = Gtk.Overlay()
        ov.set_child(self.picture)
        ov.add_overlay(self.still)
        ov.add_overlay(self.overlay_area)
        frame = Gtk.Frame(child=ov)
        frame.add_css_class("dw-view")
        root.append(frame)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._ov_begin)
        drag.connect("drag-update", self._ov_update)
        drag.connect("drag-end", self._ov_end)
        self.overlay_area.add_controller(drag)

        # --- điều khiển phát ----------------------------------------------------------
        ctl = Gtk.Box(spacing=8)
        self.play_btn = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Phát / dừng (Space)")
        self.play_btn.connect("clicked", lambda *_: self._toggle_play())
        self.time_lbl = Gtk.Label(label="0:00.0", xalign=0)
        self.time_lbl.add_css_class("dw-mono")
        ctl.append(self.play_btn)
        ctl.append(self.time_lbl)
        ctl.append(Gtk.Box(hexpand=True))
        root.append(ctl)

        if mode == "cut":
            self.timeline = Gtk.DrawingArea(content_height=58, hexpand=True)
            self.timeline.set_draw_func(self._draw_timeline)
            tdrag = Gtk.GestureDrag()
            tdrag.connect("drag-begin", self._tl_begin)
            tdrag.connect("drag-update", self._tl_update)
            tdrag.connect("drag-end", lambda *_: setattr(self, "_tl_mode", None))
            self.timeline.add_controller(tdrag)
            root.append(self.timeline)

            self.chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8,
                                     column_spacing=6, row_spacing=6)
            add = Gtk.Button(label="＋ Thêm đoạn")
            add.add_css_class("dw-add")
            add.connect("clicked", lambda *_: self._add_segment())
            chips_row = Gtk.Box(spacing=8)
            chips_row.append(add)
            chips_row.append(self.chips)
            root.append(chips_row)

            opts = Gtk.Box(spacing=18)
            self.sw_916 = self._switch(opts, "Khung 9:16", True)
            self.sw_join = self._switch(opts, "Nối thành 1 video", True)
            self.sw_916.connect("notify::active", lambda *_: self._changed())
            self.sw_join.connect("notify::active", lambda *_: self._changed())
            root.append(opts)
            self.hint = Gtk.Label(xalign=0, wrap=True)
            self.hint.add_css_class("dw-dim")
            root.append(self.hint)
        else:
            self.chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8)
            self.hint = Gtk.Label(xalign=0, wrap=True,
                                  label="Kéo chuột trên hình để khoanh vùng logo. Kéo trong khung để di chuyển, "
                                        "kéo góc dưới phải để đổi cỡ. Có thể khoanh nhiều vùng.")
            self.hint.add_css_class("dw-dim")
            root.append(self.hint)
            row = Gtk.Box(spacing=8)
            self.preview_btn = Gtk.ToggleButton(label="Xem trước kết quả")
            self.preview_btn.connect("toggled", lambda *_: self._logo_preview())
            row.append(self.preview_btn)
            row.append(self.chips)
            root.append(row)

        # --- nút ---------------------------------------------------------------------
        btns = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Hủy")
        cancel.connect("clicked", lambda *_: self.close())
        self.export_btn = Gtk.Button(label="Xuất")
        self.export_btn.add_css_class("suggested-action")
        self.export_btn.add_css_class("dw-export")
        self.export_btn.connect("clicked", lambda *_: self._export())
        btns.append(cancel)
        btns.append(self.export_btn)
        root.append(btns)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.connect("close-request", self._on_close)
        self._tick = GLib.timeout_add(80, self._poll)
        self._ov_mode = None
        self._tl_mode = None
        if mode == "cut":
            self._add_segment(at=0.0, length=self.dur)
        else:
            self._changed()

    # --- tiện ích -----------------------------------------------------------------
    @staticmethod
    def _monitor_size() -> tuple[int, int]:
        try:
            from . import hypr
            _x, _y, m = hypr.cursor_and_monitor()
            w, h = m["width"] / m["scale"], m["height"] / m["scale"]
            return (int(h), int(w)) if m["transform"] % 2 else (int(w), int(h))
        except Exception:
            return 1280, 800

    @staticmethod
    def _switch(box: Gtk.Box, label: str, active: bool) -> Gtk.Switch:
        b = Gtk.Box(spacing=8)
        sw = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
        b.append(sw)
        b.append(Gtk.Label(label=label))
        box.append(b)
        return sw

    def _now(self) -> float:
        return self.media.get_timestamp() / 1e6

    def _seek(self, t: float):
        t = min(max(0.0, t), self.dur)
        if self.media.is_seekable():
            self.media.seek(int(t * 1e6))
        self._last_seek = t
        self.timeline_redraw()

    def timeline_redraw(self):
        if self.mode == "cut":
            self.timeline.queue_draw()
        self.overlay_area.queue_draw()

    def _toggle_play(self):
        if self.media.get_playing():
            self.media.pause()
        else:
            if self.media.get_ended():
                self._seek(0)
            self.media.play()

    def _poll(self):
        playing = self.media.get_playing()
        self.play_btn.set_icon_name("media-playback-pause-symbolic" if playing else "media-playback-start-symbolic")
        self.time_lbl.set_text(f"{fmt_time(self._now())} / {fmt_time(self.dur)}")
        if self.mode == "cut":
            # Đang phát qua đoạn khác thì khung 9:16 đi theo đoạn đó.
            t = self._now()
            for i, s in enumerate(self.segs):
                if s.start <= t <= s.end and i != self.sel and playing:
                    self.sel = i
                    self._changed(rebuild=False)
                    break
        self.timeline_redraw()
        return GLib.SOURCE_CONTINUE

    def _on_key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_space:
            self._toggle_play()
            return True
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_close(self, *_):
        GLib.source_remove(self._tick)
        self.media.pause()
        if self.preview_png and os.path.exists(self.preview_png):
            os.unlink(self.preview_png)  # ảnh xem trước do chính editor tạo
        return False

    # --- vùng hiển thị video ----------------------------------------------------------
    def _view_box(self):
        aw, ah = self.overlay_area.get_width(), self.overlay_area.get_height()
        sc = min(aw / self.W, ah / self.H) if self.W and self.H else 1
        vw, vh = self.W * sc, self.H * sc
        return (aw - vw) / 2, (ah - vh) / 2, sc

    def _to_src(self, x, y):
        ox, oy, sc = self._view_box()
        return (x - ox) / sc, (y - oy) / sc

    def _crop_rect(self, seg: Seg) -> C.Rect:
        return C.crop_rect_916(self.W, self.H, seg.cx, seg.cy)

    def _draw_overlay(self, _a, cr, w, h):
        ox, oy, sc = self._view_box()
        if self.mode == "cut":
            if not self.segs or not self.sw_916.get_active():
                return
            seg = self.segs[self.sel]
            r = self._crop_rect(seg)
            rx, ry, rw, rh = ox + r.x * sc, oy + r.y * sc, r.w * sc, r.h * sc
            vw, vh = self.W * sc, self.H * sc
            cr.set_source_rgba(0, 0, 0, 0.6)  # làm tối phần bị cắt bỏ
            cr.rectangle(ox, oy, rx - ox, vh)
            cr.rectangle(rx + rw, oy, ox + vw - rx - rw, vh)
            cr.rectangle(rx, oy, rw, ry - oy)
            cr.rectangle(rx, ry + rh, rw, oy + vh - ry - rh)
            cr.fill()
            cr.set_source_rgba(*rgba(seg.color))
            cr.set_line_width(3)
            cr.rectangle(rx, ry, rw, rh)
            cr.stroke()
            # đường chia ba
            cr.set_source_rgba(1, 1, 1, 0.25)
            cr.set_line_width(1)
            for k in (1, 2):
                cr.move_to(rx + rw * k / 3, ry)
                cr.line_to(rx + rw * k / 3, ry + rh)
                cr.move_to(rx, ry + rh * k / 3)
                cr.line_to(rx + rw, ry + rh * k / 3)
            cr.stroke()
        else:
            if self.preview_btn.get_active():
                return
            for i, r in enumerate(self.rects):
                rx, ry, rw, rh = ox + r.x * sc, oy + r.y * sc, r.w * sc, r.h * sc
                col = rgba(COLORS[i % len(COLORS)])
                cr.set_source_rgba(col[0], col[1], col[2], 0.18)
                cr.rectangle(rx, ry, rw, rh)
                cr.fill()
                cr.set_source_rgba(*col)
                cr.set_line_width(3 if i == self.rect_sel else 2)
                cr.rectangle(rx, ry, rw, rh)
                cr.stroke()
                cr.rectangle(rx + rw - 8, ry + rh - 8, 10, 10)
                cr.fill()

    def _ov_begin(self, g, x, y):
        self._ov_start = (x, y)
        sx, sy = self._to_src(x, y)
        if self.mode == "cut":
            if self.segs and self.sw_916.get_active():
                seg = self.segs[self.sel]
                self._ov_mode = ("move", seg.cx, seg.cy)
                seg.cx, seg.cy = sx, sy   # bấm vào đâu thì khung nhảy tới đó
                self.overlay_area.queue_draw()
            return
        self.preview_btn.set_active(False)
        ox, oy, sc = self._view_box()
        for i in reversed(range(len(self.rects))):
            r = self.rects[i]
            if abs(sx - (r.x + r.w)) * sc < 12 and abs(sy - (r.y + r.h)) * sc < 12:
                self.rect_sel, self._ov_mode = i, ("resize", r)
                return
            if r.x <= sx <= r.x + r.w and r.y <= sy <= r.y + r.h:
                self.rect_sel, self._ov_mode = i, ("move", r)
                return
        sx, sy = min(max(sx, 0), self.W), min(max(sy, 0), self.H)
        self.rects.append(C.Rect(int(sx), int(sy), 2, 2))
        self.rect_sel = len(self.rects) - 1
        self._ov_mode = ("new", (sx, sy))
        self._changed()

    def _ov_update(self, g, dx, dy):
        if not self._ov_mode:
            return
        x0, y0 = self._ov_start
        sx, sy = self._to_src(x0 + dx, y0 + dy)
        if self.mode == "cut":
            seg = self.segs[self.sel]
            seg.cx, seg.cy = sx, sy
            self.overlay_area.queue_draw()
            return
        kind, ref = self._ov_mode[0], self._ov_mode[1]
        _, _, sc = self._view_box()
        i = self.rect_sel
        if kind == "new":
            ax, ay = ref
            bx, by = min(max(sx, 0), self.W), min(max(sy, 0), self.H)
            self.rects[i] = C.Rect(int(min(ax, bx)), int(min(ay, by)), int(abs(bx - ax)), int(abs(by - ay)))
        elif kind == "move":
            nx = min(max(0, ref.x + dx / sc), self.W - ref.w)
            ny = min(max(0, ref.y + dy / sc), self.H - ref.h)
            self.rects[i] = C.Rect(int(nx), int(ny), ref.w, ref.h)
        elif kind == "resize":
            nw = min(max(8, ref.w + dx / sc), self.W - ref.x)
            nh = min(max(8, ref.h + dy / sc), self.H - ref.y)
            self.rects[i] = C.Rect(ref.x, ref.y, int(nw), int(nh))
        self.overlay_area.queue_draw()

    def _ov_end(self, *_):
        if self.mode == "logo" and self._ov_mode and self._ov_mode[0] == "new":
            r = self.rects[self.rect_sel]
            if r.w < 6 or r.h < 6:
                self.rects.pop(self.rect_sel)
                self.rect_sel = None
        self._ov_mode = None
        self._changed()

    # --- thanh thời gian -------------------------------------------------------------
    def _t2x(self, t):
        w = self.timeline.get_width() - 2 * TL_PAD
        return TL_PAD + w * t / self.dur

    def _x2t(self, x):
        w = max(1, self.timeline.get_width() - 2 * TL_PAD)
        return min(max(0.0, (x - TL_PAD) / w * self.dur), self.dur)

    def _draw_timeline(self, _a, cr, w, h):
        y0, y1 = 14, 44
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.25)
        self._round(cr, TL_PAD, y0 + 8, w - 2 * TL_PAD, y1 - y0 - 16, 4)
        cr.fill()
        for i, s in enumerate(self.segs):
            x0, x1 = self._t2x(s.start), self._t2x(s.end)
            sel = i == self.sel
            cr.set_source_rgba(*rgba(s.color, 0.92 if sel else 0.5))
            self._round(cr, x0, y0, max(4, x1 - x0), y1 - y0, 6)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.95)
            cr.select_font_face("sans", 0, 1)
            cr.set_font_size(11)
            cr.move_to(x0 + 6, y0 + 19)
            cr.show_text(str(i + 1))
            if sel:
                for hx in (x0, x1):
                    self._round(cr, hx - 3, y0 - 3, 6, y1 - y0 + 6, 3)
                    cr.set_source_rgba(1, 1, 1, 1)
                    cr.fill()
        px = self._t2x(self._now())
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.set_line_width(2)
        cr.move_to(px, 4)
        cr.line_to(px, h - 4)
        cr.stroke()
        cr.arc(px, 6, 4, 0, 2 * math.pi)
        cr.fill()

    @staticmethod
    def _round(cr, x, y, w, h, r):
        r = min(r, w / 2, h / 2)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def _tl_begin(self, g, x, y):
        self._tl_x0 = x
        if self.segs:
            s = self.segs[self.sel]
            if abs(x - self._t2x(s.start)) <= HANDLE_PX:
                self._tl_mode = ("start",)
                return
            if abs(x - self._t2x(s.end)) <= HANDLE_PX:
                self._tl_mode = ("end",)
                return
        t = self._x2t(x)
        if 14 <= y <= 44:
            for i, s in enumerate(self.segs):
                if s.start <= t <= s.end:
                    if i != self.sel:
                        self.sel = i
                        self._changed(rebuild=False)
                    self._tl_mode = ("move", s.start, s.end)
                    self._seek(t)
                    return
        self._tl_mode = ("seek",)
        self._seek(t)

    def _tl_update(self, g, dx, dy):
        if not self._tl_mode:
            return
        t = self._x2t(self._tl_x0 + dx)
        s = self.segs[self.sel] if self.segs else None
        kind = self._tl_mode[0]
        if kind == "seek":
            self._seek(t)
        elif kind == "start":
            s.start = min(max(0.0, t), s.end - MIN_SEG)
            self._seek(s.start)
        elif kind == "end":
            s.end = max(min(self.dur, t), s.start + MIN_SEG)
            self._seek(s.end)
        elif kind == "move":
            _, a, b = self._tl_mode
            shift = self._x2t(self._tl_x0 + dx) - self._x2t(self._tl_x0)
            shift = min(max(shift, -a), self.dur - b)
            s.start, s.end = a + shift, b + shift
        self._changed(rebuild=False)

    # --- đoạn ------------------------------------------------------------------------
    def _add_segment(self, at: float | None = None, length: float = 5.0):
        t = self._now() if at is None else at
        if t >= self.dur - MIN_SEG:
            t = max(0.0, self.dur - length)
        end = min(self.dur, t + length)
        cx = self.segs[self.sel].cx if self.segs else self.W / 2
        used = {s.color for s in self.segs}
        color = next((c for c in COLORS if c not in used), COLORS[len(self.segs) % len(COLORS)])
        self.segs.append(Seg(t, end, cx, self.H / 2, color))
        self.sel = len(self.segs) - 1
        self._changed()

    def _remove(self, i: int):
        if self.mode == "cut":
            if len(self.segs) <= 1:
                return
            self.segs.pop(i)
            self.sel = min(self.sel, len(self.segs) - 1)
        else:
            self.rects.pop(i)
            self.rect_sel = None
            self.preview_btn.set_active(False)
        self._changed()

    def _changed(self, rebuild: bool = True):
        if rebuild:
            self._chip_labels = {}
            while (c := self.chips.get_first_child()) is not None:
                self.chips.remove(c)
            items = self.segs if self.mode == "cut" else self.rects
            for i, item in enumerate(items):
                color = item.color if self.mode == "cut" else COLORS[i % len(COLORS)]
                chip = Gtk.Box(spacing=4)
                chip.add_css_class("dw-chip")
                dot = Gtk.Label(label="●")
                dot.set_markup(f'<span foreground="{color}">●</span>')
                txt = Gtk.Button(label=f"{i + 1}" if self.mode == "cut" else f"Vùng {i + 1}")
                txt.add_css_class("flat")
                txt.connect("clicked", lambda _b, k=i: self._select(k))
                chip.append(dot)
                chip.append(txt)
                if self.mode == "logo" or len(self.segs) > 1:
                    x = Gtk.Button(label="✕", tooltip_text="Bỏ khỏi danh sách")
                    x.add_css_class("flat")
                    x.connect("clicked", lambda _b, k=i: self._remove(k))
                    chip.append(x)
                self.chips.append(chip)
                self._chip_labels[i] = txt
        if self.mode == "cut":
            for i, s in enumerate(self.segs):
                lbl = self._chip_labels.get(i)
                if lbl:
                    lbl.set_label(f"{i + 1} · {fmt_time(s.start)}–{fmt_time(s.end)}")
            total = sum(s.end - s.start for s in self.segs)
            v = self.sw_916.get_active()
            j = self.sw_join.get_active() or len(self.segs) == 1
            shape = "dọc 9:16" if v else "giữ khung ngang"
            if j:
                self.hint.set_text(f"Xuất 1 video {shape}, dài {fmt_time(total)}.")
            else:
                self.hint.set_text(f"Xuất {len(self.segs)} video {shape}, mỗi đoạn một file.")
            self.export_btn.set_sensitive(bool(self.segs))
        else:
            self.export_btn.set_sensitive(bool(self.rects))
        self.timeline_redraw()

    def _select(self, i: int):
        if self.mode == "cut":
            self.sel = i
            self._seek(self.segs[i].start)
            self._changed(rebuild=False)
        else:
            self.rect_sel = i
            self.overlay_area.queue_draw()

    # --- xem trước logo ---------------------------------------------------------------
    def _logo_preview(self):
        if not self.preview_btn.get_active() or not self.rects:
            self.still.set_visible(False)
            self.preview_btn.set_active(False) if not self.rects else None
            self.overlay_area.queue_draw()
            return
        self.media.pause()
        if self.preview_png is None:
            fd, self.preview_png = tempfile.mkstemp(prefix="dropwheel-preview-", suffix=".png",
                                                    dir=os.environ.get("XDG_RUNTIME_DIR"))
            os.close(fd)
        vf = ",".join(C.logo_filters(self.info, self.rects))
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{self._now():.3f}", "-i", str(self.info.path),
                            "-vf", vf, "-frames:v", "1", self.preview_png], capture_output=True, timeout=20)
        if r.returncode == 0:
            self.still.set_filename(self.preview_png)
            self.still.set_visible(True)
        self.overlay_area.queue_draw()

    # --- xuất ------------------------------------------------------------------------
    def _export(self):
        info, vaapi = self.info, self.vaapi
        if self.mode == "cut":
            vertical = self.sw_916.get_active()
            join = self.sw_join.get_active()
            segs = [C.Segment(s.start, s.end, self._crop_rect(s) if vertical else None) for s in self.segs]
            job = Job("Đang chuẩn bị…", lambda: C.cut(info, segs, vertical, join, vaapi), info.path.name)
        else:
            rects = list(self.rects)
            job = Job("Đang chuẩn bị…", lambda: C.logo(info, rects, vaapi), info.path.name)
        self.submit(job)
        self.close()
