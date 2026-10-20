import tempfile
import unittest
from pathlib import Path

from dropwheel import commands as C
from dropwheel import naming
from dropwheel.probe import MediaInfo, ProbeError, parse


def info(path="/v/a.mov", **kw):
    base = dict(path=Path(path), format_name="mov,mp4,m4a,3gp,3g2,mj2", duration=10.0,
                width=1920, height=1080, fps=30.0, vcodec="h264", pix_fmt="yuv420p",
                is_hdr=False, has_audio=True, acodec="aac", abitrate=128000)
    base.update(kw)
    return MediaInfo(**base)


class Naming(unittest.TestCase):
    def test_unique_numbers_instead_of_overwriting(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "geese.mov"
            self.assertEqual(naming.output_for(src, "nén").name, "geese - nén.mp4")
            (Path(d) / "geese - nén.mp4").touch()
            self.assertEqual(naming.output_for(src, "nén").name, "geese - nén (2).mp4")
            (Path(d) / "geese - nén (2).mp4").touch()
            self.assertEqual(naming.output_for(src, "nén").name, "geese - nén (3).mp4")

    def test_mp4_name_and_part(self):
        with tempfile.TemporaryDirectory() as d:
            out = naming.output_for(Path(d) / "geese.mov", None)
            self.assertEqual(out.name, "geese.mp4")
            self.assertEqual(naming.part_path(out).name, ".geese.dropwheel-part.mp4")


class Probe(unittest.TestCase):
    def test_rotation_swaps_dimensions(self):
        data = {"format": {"format_name": "mov", "duration": "2"},
                "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
                             "avg_frame_rate": "30/1", "pix_fmt": "yuv420p",
                             "side_data_list": [{"rotation": -90}]}]}
        i = parse(Path("x.mov"), data)
        self.assertEqual((i.width, i.height), (1080, 1920))
        self.assertFalse(i.has_audio)

    def test_not_video(self):
        with self.assertRaises(ProbeError):
            parse(Path("x.mp3"), {"format": {}, "streams": [{"codec_type": "audio"}]})

    def test_cover_art_is_not_video(self):
        with self.assertRaises(ProbeError):
            parse(Path("x.mp3"), {"format": {}, "streams": [
                {"codec_type": "video", "disposition": {"attached_pic": 1}}]})


class Commands(unittest.TestCase):
    def test_mp4_remux_when_codecs_fit(self):
        p = C.mp4(info(), vaapi=True)
        self.assertIn("copy", p.args)
        self.assertNotIn("-vaapi_device", p.args)

    def test_mp4_reencode_when_codec_does_not_fit(self):
        p = C.mp4(info(vcodec="vp9", acodec="opus"), vaapi=True)
        self.assertIn("h264_vaapi", p.args)
        self.assertNotIn("copy", p.args)

    def test_mp4_already(self):
        with self.assertRaises(C.AlreadyDone):
            C.mp4(info("/v/a.mp4"), vaapi=True)

    def test_compress_strips_metadata_and_caps(self):
        p = C.compress(info(), vaapi=False)
        s = " ".join(p.args)
        self.assertIn("-map_metadata -1", s)
        self.assertIn("-maxrate 1350k", s)
        self.assertIn("+faststart", s)
        self.assertTrue(p.must_shrink)

    def test_compress_fps_cap_only_when_above_30(self):
        self.assertNotIn("fps=30", " ".join(C.compress(info(fps=30.0), vaapi=False).args))
        self.assertIn("fps=30", " ".join(C.compress(info(fps=60.0), vaapi=False).args))

    def test_compress_audio_copy_rule(self):
        self.assertIn("copy", C.compress(info(abitrate=96000), vaapi=False).args)
        self.assertNotIn("copy", C.compress(info(abitrate=320000), vaapi=False).args)

    def test_hdr_gets_tonemap(self):
        self.assertIn("tonemap", " ".join(C.compress(info(is_hdr=True), vaapi=False).args))

    def test_crop_rect_916(self):
        r = C.crop_rect_916(1920, 1080, center_x=1900)
        self.assertEqual((r.w, r.h), (606, 1080))
        self.assertEqual(r.x + r.w, 1920 - (1920 - r.x - r.w))
        self.assertLessEqual(r.x + r.w, 1920)
        r2 = C.crop_rect_916(720, 1280, center_x=360)  # nguồn đã dọc
        self.assertEqual((r2.w, r2.h), (720, 1280))

    def test_cut_separate_makes_one_file_per_segment(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "a.mov"
            r = C.crop_rect_916(1920, 1080, 960)
            segs = [C.Segment(0, 1, r), C.Segment(2, 3, r), C.Segment(4, 5, r)]
            p = C.cut(info(str(src)), segs, vertical=True, join=False, vaapi=False)
            self.assertEqual([f.name for f in p.finals],
                             ["a - 9x16 đoạn 1.mp4", "a - 9x16 đoạn 2.mp4", "a - 9x16 đoạn 3.mp4"])
            self.assertEqual(p.args.count("libx264"), 3)

    def test_cut_join_sorts_by_time(self):
        p = C.cut(info(), [C.Segment(5, 6), C.Segment(1, 2)], vertical=False, join=True, vaapi=False)
        g = p.args[p.args.index("-filter_complex") + 1]
        self.assertLess(g.index("start=1.000"), g.index("start=5.000"))
        self.assertIn("concat=n=2", g)
        self.assertEqual(p.duration, 2)

    def test_logo_clamped_inside_frame(self):
        r = C.clamp_logo(C.Rect(0, 0, 5000, 5000), 1920, 1080)
        self.assertGreaterEqual(r.x, 1)
        self.assertLessEqual(r.x + r.w, 1919)
        self.assertLessEqual(r.y + r.h, 1079)


if __name__ == "__main__":
    unittest.main()
