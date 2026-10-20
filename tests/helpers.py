"""Sinh video thử bằng lavfi. Không bao giờ dùng file thật của user."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def make_video(path: Path, *, w=1920, h=1080, dur=3, fps=30, audio=True,
               vcodec="libx264", acodec="aac", hdr=False, rotate=None) -> Path:
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", f"testsrc2=duration={dur}:size={w}x{h}:rate={fps}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"]
    if hdr:
        args += ["-pix_fmt", "yuv420p10le", "-c:v", "libx265", "-x265-params", "log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc",
                 "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc"]
    else:
        args += ["-pix_fmt", "yuv420p", "-c:v", vcodec]
    if audio:
        args += ["-c:a", acodec]
    args += ["-metadata", "location=+10.7769+106.7009/", "-metadata", "title=secret"]
    if rotate is None:
        subprocess.run(args + [str(path)], check=True)
        return path
    # -display_rotation là tùy chọn đầu vào, nên tạo bản thường rồi remux kèm xoay.
    tmp = path.with_name("unrotated-" + path.name)
    subprocess.run(args + [str(tmp)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-display_rotation:v:0", str(rotate),
                    "-i", str(tmp), "-c", "copy", str(path)], check=True)
    return path


def ffprobe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                          "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def vstream(data: dict) -> dict:
    return next(s for s in data["streams"] if s["codec_type"] == "video")
