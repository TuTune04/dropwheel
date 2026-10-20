"""Đọc thông tin video bằng ffprobe."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}


class ProbeError(Exception):
    pass


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    format_name: str
    duration: float
    width: int            # kích thước hiển thị (đã tính xoay)
    height: int
    fps: float
    vcodec: str
    pix_fmt: str
    is_hdr: bool
    has_audio: bool
    acodec: str | None
    abitrate: int | None  # bit/s, None nếu không rõ
    rotation: int = 0     # độ xoay hiển thị (metadata)

    @property
    def is_10bit(self) -> bool:
        return "10" in self.pix_fmt or "12" in self.pix_fmt


def _rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list", []):
        if "rotation" in sd:
            return int(sd["rotation"])
    return int(stream.get("tags", {}).get("rotate", 0) or 0)


def _fps(stream: dict) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        val = stream.get(key, "0/0")
        try:
            f = Fraction(val)
        except (ValueError, ZeroDivisionError):
            continue
        if f > 0:
            return float(f)
    return 0.0


def parse(path: Path, data: dict) -> MediaInfo:
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise ProbeError("Không phải video")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    w, h = int(video.get("width", 0)), int(video.get("height", 0))
    rot = _rotation(video)
    if abs(rot) % 180 == 90:
        w, h = h, w

    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or video.get("duration") or 0)
    abitrate = None
    if audio and audio.get("bit_rate"):
        abitrate = int(audio["bit_rate"])

    return MediaInfo(
        path=path,
        format_name=fmt.get("format_name", ""),
        duration=duration,
        width=w,
        height=h,
        fps=_fps(video),
        vcodec=video.get("codec_name", ""),
        pix_fmt=video.get("pix_fmt", ""),
        is_hdr=video.get("color_transfer") in HDR_TRANSFERS,
        has_audio=audio is not None,
        acodec=audio.get("codec_name") if audio else None,
        abitrate=abitrate,
        rotation=rot,
    )


def probe(path: str | Path) -> MediaInfo:
    path = Path(path)
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise ProbeError("Không đọc được file") from e
    return parse(path, json.loads(out))
