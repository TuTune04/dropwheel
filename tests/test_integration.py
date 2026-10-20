"""Chạy ffmpeg thật trên video tự sinh (lavfi). Chậm hơn unit test (~vài chục giây)."""
import tempfile
import threading
import time
import unittest
from pathlib import Path

from helpers import ffprobe, make_video, vstream

from dropwheel import commands as C
from dropwheel.encoders import has_vaapi
from dropwheel.jobs import Job, Runner
from dropwheel.probe import probe


def run_plan(build, timeout=120):
    events = []
    done = threading.Event()

    def on(ev):
        if ev.kind in ("done", "skipped", "error", "cancelled"):
            events.append(ev)
            done.set()
    r = Runner(on)
    r.submit([Job("test", build)])
    if not done.wait(timeout):
        raise AssertionError("job quá thời gian")
    return events[-1], r


class Base(unittest.TestCase):
    vaapi = False

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def assert_no_parts(self):
        self.assertEqual(list(self.d.glob(".*dropwheel-part*")), [])

    def test_compress_1080p_to_720p_and_strips_metadata(self):
        src = make_video(self.d / "clip.mov", dur=4, fps=60)
        before = src.stat().st_size
        t0 = time.monotonic()
        ev, _ = run_plan(lambda: C.compress(probe(src), self.vaapi))
        took = time.monotonic() - t0
        if ev.kind == "skipped":
            self.assertEqual(ev.message, "Đã đủ nhẹ")
            return
        self.assertEqual(ev.kind, "done", ev.message)
        out = ev.outputs[0]
        self.assertEqual(out.name, "clip - nén.mp4")
        d = ffprobe(out)
        v = vstream(d)
        self.assertEqual((v["width"], v["height"]), (1280, 720))
        self.assertEqual(v["codec_name"], "h264")
        self.assertEqual(v["pix_fmt"], "yuv420p")
        self.assertLessEqual(eval(v["avg_frame_rate"]), 30.01)
        tags = d["format"].get("tags", {})
        self.assertNotIn("location", tags)
        self.assertNotIn("title", tags)
        self.assertEqual(src.stat().st_size, before)  # gốc nguyên vẹn
        self.assert_no_parts()
        print(f"\n  nén 4s 1080p60 ({'vaapi' if self.vaapi else 'x264'}): {took:.1f}s, "
              f"{out.stat().st_size / 1e6:.2f} MB")

    def test_compress_never_upscales_small_video(self):
        src = make_video(self.d / "small.mov", w=640, h=360, dur=2, vcodec="mpeg4")
        ev, _ = run_plan(lambda: C.compress(probe(src), self.vaapi))
        if ev.kind == "done":
            v = vstream(ffprobe(ev.outputs[0]))
            self.assertEqual((v["width"], v["height"]), (640, 360))

    def test_compress_portrait_rotated(self):
        src = make_video(self.d / "phone.mp4", w=1920, h=1080, dur=2, rotate=90, vcodec="mpeg4")
        info = probe(src)
        self.assertEqual((info.width, info.height), (1080, 1920))
        ev, _ = run_plan(lambda: C.compress(info, self.vaapi))
        self.assertEqual(ev.kind, "done", ev.message)
        v = vstream(ffprobe(ev.outputs[0]))
        self.assertEqual((v["width"], v["height"]), (720, 1280))

    def test_hdr_is_tonemapped_to_8bit(self):
        src = make_video(self.d / "hdr.mov", w=1280, h=720, dur=2, hdr=True)
        self.assertTrue(probe(src).is_hdr)
        ev, _ = run_plan(lambda: C.compress(probe(src), self.vaapi))
        if ev.kind == "done":
            v = vstream(ffprobe(ev.outputs[0]))
            self.assertEqual(v["pix_fmt"], "yuv420p")

    def test_mp4_remux_and_existing_name_not_overwritten(self):
        src = make_video(self.d / "geese.mov", dur=2)
        (self.d / "geese.mp4").write_bytes(b"keep me")
        ev, _ = run_plan(lambda: C.mp4(probe(src), self.vaapi))
        self.assertEqual(ev.kind, "done", ev.message)
        self.assertEqual(ev.outputs[0].name, "geese (2).mp4")
        self.assertEqual((self.d / "geese.mp4").read_bytes(), b"keep me")
        self.assert_no_parts()

    def test_mp4_reencode_from_vp9(self):
        src = make_video(self.d / "web.webm", w=1280, h=720, dur=2, vcodec="libvpx-vp9", acodec="libopus")
        ev, _ = run_plan(lambda: C.mp4(probe(src), self.vaapi))
        self.assertEqual(ev.kind, "done", ev.message)
        d = ffprobe(ev.outputs[0])
        self.assertEqual(vstream(d)["codec_name"], "h264")
        self.assertEqual((vstream(d)["width"], vstream(d)["height"]), (1280, 720))

    def test_mp4_already(self):
        src = make_video(self.d / "a.mp4", dur=1)
        ev, _ = run_plan(lambda: C.mp4(probe(src), self.vaapi))
        self.assertEqual((ev.kind, ev.message), ("skipped", "Đã là MP4"))

    def test_crop_three_people_joined(self):
        src = make_video(self.d / "talk.mov", dur=6)
        info = probe(src)
        segs = [C.Segment(0, 1.5, C.crop_rect_916(1920, 1080, 300)),
                C.Segment(2, 3.5, C.crop_rect_916(1920, 1080, 960)),
                C.Segment(4, 5.5, C.crop_rect_916(1920, 1080, 1700))]
        ev, _ = run_plan(lambda: C.cut(info, segs, vertical=True, join=True, vaapi=self.vaapi))
        self.assertEqual(ev.kind, "done", ev.message)
        d = ffprobe(ev.outputs[0])
        v = vstream(d)
        self.assertEqual((v["width"], v["height"]), (606, 1080))  # không phóng to
        self.assertAlmostEqual(float(d["format"]["duration"]), 4.5, delta=0.3)
        self.assertNotIn("location", d["format"].get("tags", {}))

    def test_crop_separate_files(self):
        src = make_video(self.d / "talk.mov", dur=4)
        info = probe(src)
        segs = [C.Segment(0, 1, C.crop_rect_916(1920, 1080, 300)),
                C.Segment(2, 3, C.crop_rect_916(1920, 1080, 1600))]
        ev, _ = run_plan(lambda: C.cut(info, segs, vertical=True, join=False, vaapi=self.vaapi))
        self.assertEqual(ev.kind, "done", ev.message)
        self.assertEqual([o.name for o in ev.outputs], ["talk - 9x16 đoạn 1.mp4", "talk - 9x16 đoạn 2.mp4"])
        for o in ev.outputs:
            self.assertAlmostEqual(float(ffprobe(o)["format"]["duration"]), 1.0, delta=0.2)

    def test_trim_only_keeps_resolution_no_audio(self):
        src = make_video(self.d / "mute.mov", dur=4, audio=False)
        ev, _ = run_plan(lambda: C.cut(probe(src), [C.Segment(1, 2.5)], vertical=False, join=True,
                                       vaapi=self.vaapi))
        self.assertEqual(ev.kind, "done", ev.message)
        d = ffprobe(ev.outputs[0])
        self.assertEqual((vstream(d)["width"], vstream(d)["height"]), (1920, 1080))
        self.assertAlmostEqual(float(d["format"]["duration"]), 1.5, delta=0.2)
        self.assertEqual(ev.outputs[0].name, "mute - cắt.mp4")

    def test_logo(self):
        src = make_video(self.d / "logo.mov", dur=2)
        ev, _ = run_plan(lambda: C.logo(probe(src), [C.Rect(1700, 20, 200, 80), C.Rect(0, 0, 50, 50)],
                                        self.vaapi))
        self.assertEqual(ev.kind, "done", ev.message)
        self.assertEqual(ev.outputs[0].name, "logo - xóa logo.mp4")

    def test_cancel_removes_temp_only(self):
        src = make_video(self.d / "long.mov", dur=20)
        before = src.stat().st_size
        events, done = [], threading.Event()

        def on(ev):
            if ev.kind != "idle":
                events.append(ev)
            if ev.kind == "progress" and ev.fraction > 0.05:
                r.cancel_current()
            if ev.kind in ("done", "cancelled", "error", "skipped"):
                done.set()
        r = Runner(on)
        r.submit([Job("t", lambda: C.cut(probe(src), [C.Segment(0, 20)], vertical=False, join=True,
                                         vaapi=False))])
        self.assertTrue(done.wait(60))
        if events[-1].kind == "cancelled":
            self.assert_no_parts()
            self.assertFalse((self.d / "long - cắt.mp4").exists())
        self.assertEqual(src.stat().st_size, before)

    def test_not_video(self):
        f = self.d / "note.txt"
        f.write_text("hi")
        ev, _ = run_plan(lambda: C.compress(probe(f), self.vaapi))
        self.assertEqual(ev.kind, "error")


class X264(Base):
    vaapi = False


@unittest.skipUnless(has_vaapi(), "không có VAAPI")
class Vaapi(Base):
    vaapi = True


del Base

if __name__ == "__main__":
    unittest.main()
