"""Dựng lệnh ffmpeg cho bốn thao tác. Thuần: không chạy gì, chỉ trả về Plan."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import naming
from .encoders import VAAPI_DEVICE
from .probe import MediaInfo

# Thông số "Nén để gửi" (mức Cân bằng, thiết kế §8.2). Chỉnh một lần bằng clip thật rồi cố định.
SEND_VIDEO_KBPS = 1350
SEND_AUDIO_KBPS = 128
SEND_VAAPI_QUALITY = 25     # QVBR global_quality (thấp = đẹp hơn)
SEND_X264_CRF = 23
SEND_LONG_SIDE = 1280
SEND_MAX_FPS = 30

HIGH_VAAPI_QP = 20
HIGH_X264_CRF = 18
HIGH_AUDIO_KBPS = 192

REMUX_VCODECS = {"h264", "hevc"}
REMUX_ACODECS = {"aac", "mp3", "alac"}

TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
SEND_SCALE = (f"scale=w='if(gte(iw,ih),min({SEND_LONG_SIDE},iw),-2)'"
              f":h='if(gte(iw,ih),-2,min({SEND_LONG_SIDE},ih))'")


class AlreadyDone(Exception):
    """Không cần làm gì (ví dụ đã là MP4). Thông điệp dành cho user."""


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    crop: Rect | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Plan:
    title: str                       # chữ trên thẻ tiến độ, ví dụ "Đang nén…"
    args: list[str]
    finals: list[Path]
    parts: list[Path]
    duration: float                  # giây, để tính phần trăm
    must_shrink: bool = False        # Nén: bỏ kết quả nếu không nhỏ hơn gốc
    src: Path | None = None
    notes: list[str] = field(default_factory=list)


# --- mảnh ghép ---------------------------------------------------------------

def _head(vaapi: bool) -> list[str]:
    a = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
         "-progress", "pipe:1", "-nostats"]
    if vaapi:
        a += ["-vaapi_device", VAAPI_DEVICE]
    return a


def _venc(profile: str, vaapi: bool) -> list[str]:
    if profile == "send":
        if vaapi:
            return ["-c:v", "h264_vaapi", "-rc_mode", "QVBR",
                    "-global_quality", str(SEND_VAAPI_QUALITY),
                    "-b:v", f"{SEND_VIDEO_KBPS}k", "-maxrate", f"{SEND_VIDEO_KBPS}k"]
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(SEND_X264_CRF),
                "-maxrate", f"{SEND_VIDEO_KBPS}k", "-bufsize", f"{SEND_VIDEO_KBPS * 2}k",
                "-profile:v", "high"]
    if vaapi:
        return ["-c:v", "h264_vaapi", "-rc_mode", "CQP", "-qp", str(HIGH_VAAPI_QP)]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(HIGH_X264_CRF),
            "-profile:v", "high"]


def _upload(vaapi: bool) -> str:
    return "format=nv12,hwupload" if vaapi else "format=yuv420p"


def _color(info: MediaInfo) -> list[str]:
    return [TONEMAP] if info.is_hdr else []


def _send_shape(info: MediaInfo) -> list[str]:
    f = [SEND_SCALE]
    if info.fps > SEND_MAX_FPS + 0.5:
        f.append(f"fps={SEND_MAX_FPS}")
    return f


STRIP_META = ["-map_metadata", "-1", "-map_chapters", "-1",
              "-metadata:s:v", "handler_name=", "-metadata:s:a", "handler_name="]
FASTSTART = ["-movflags", "+faststart"]


def _aenc(kbps: int) -> list[str]:
    return ["-c:a", "aac", "-b:a", f"{kbps}k"]


def _outputs(finals: list[Path]) -> list[Path]:
    return [naming.part_path(p) for p in finals]


# --- bốn thao tác ------------------------------------------------------------

def mp4(info: MediaInfo, vaapi: bool) -> Plan:
    src = info.path
    if src.suffix.lower() == ".mp4" and "mp4" in info.format_name:
        raise AlreadyDone("Đã là MP4")
    final = naming.output_for(src, None)
    part = naming.part_path(final)
    remux = info.vcodec in REMUX_VCODECS and (not info.has_audio or info.acodec in REMUX_ACODECS)

    args = _head(vaapi and not remux) + ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
                                          "-map_metadata", "0"]
    if remux:
        args += ["-c", "copy"]
        if info.vcodec == "hevc":
            args += ["-tag:v", "hvc1"]
        title = "Đang chuyển MP4…"
    else:
        vf = ",".join(_color(info) + [EVEN, _upload(vaapi)])
        args += ["-vf", vf] + _venc("high", vaapi) + _aenc(HIGH_AUDIO_KBPS)
        title = "Đang chuyển MP4…"
    args += FASTSTART + [str(part)]
    return Plan(title, args, [final], [part], info.duration, src=src)


def compress(info: MediaInfo, vaapi: bool) -> Plan:
    src = info.path
    final = naming.output_for(src, "nén")
    part = naming.part_path(final)
    vf = ",".join(_color(info) + _send_shape(info) + ["setsar=1", EVEN, _upload(vaapi)])
    args = _head(vaapi) + ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf]
    args += _venc("send", vaapi)
    if info.has_audio:
        if info.acodec == "aac" and info.abitrate is not None and info.abitrate <= SEND_AUDIO_KBPS * 1000 + 2000:
            args += ["-c:a", "copy"]
        else:
            args += _aenc(SEND_AUDIO_KBPS)
    args += STRIP_META + FASTSTART + [str(part)]
    return Plan("Đang nén…", args, [final], [part], info.duration, must_shrink=True, src=src)


def cut(info: MediaInfo, segments: list[Segment], vertical: bool, join: bool, vaapi: bool) -> Plan:
    """Cắt đoạn (vertical=False) hoặc crop 9:16 (vertical=True), một lần chạy ffmpeg."""
    if not segments:
        raise ValueError("Chưa có đoạn nào")
    if vertical and any(s.crop is None for s in segments):
        raise ValueError("Đoạn 9:16 thiếu khung crop")
    segs = sorted(segments, key=lambda s: s.start) if join else list(segments)
    n = len(segs)
    src = info.path
    profile = "send" if vertical else "high"
    akbps = SEND_AUDIO_KBPS if vertical else HIGH_AUDIO_KBPS
    audio = info.has_audio

    g: list[str] = []
    vin = [f"[sv{i}]" for i in range(n)] if n > 1 else ["[0:v:0]"]
    ain = [f"[sa{i}]" for i in range(n)] if n > 1 else ["[0:a:0]"]
    if n > 1:
        g.append("[0:v:0]split=" + str(n) + "".join(vin))
        if audio:
            g.append("[0:a:0]asplit=" + str(n) + "".join(ain))

    for i, s in enumerate(segs):
        chain = [f"trim=start={s.start:.3f}:end={s.end:.3f}", "setpts=PTS-STARTPTS"]
        if vertical:
            c = s.crop
            chain.append(f"crop={c.w}:{c.h}:{c.x}:{c.y}")
        chain += _color(info)
        if vertical:
            chain += _send_shape(info)
        chain += ["setsar=1", EVEN]
        g.append(f"{vin[i]}{','.join(chain)}[v{i}]")
        if audio:
            g.append(f"{ain[i]}atrim=start={s.start:.3f}:end={s.end:.3f},asetpts=PTS-STARTPTS[a{i}]")

    label = "9x16" if vertical else "cắt"
    if join:
        pairs = "".join(f"[v{i}]" + (f"[a{i}]" if audio else "") for i in range(n))
        if n > 1:
            g.append(f"{pairs}concat=n={n}:v=1:a={1 if audio else 0}[vj]" + ("[aj]" if audio else ""))
            vlast, alast = "[vj]", "[aj]"
        else:
            vlast, alast = "[v0]", "[a0]"
        g.append(f"{vlast}{_upload(vaapi)}[vo0]")
        finals = [naming.output_for(src, label)]
        maps = [("[vo0]", alast if audio else None)]
        duration = sum(s.duration for s in segs)
    else:
        finals = []
        for i in range(n):
            g.append(f"[v{i}]{_upload(vaapi)}[vo{i}]")
            name = f"{label} đoạn {i + 1}" if vertical else f"đoạn {i + 1}"
            finals.append(naming.output_for(src, name))
        maps = [(f"[vo{i}]", f"[a{i}]" if audio else None) for i in range(n)]
        duration = max(s.duration for s in segs)

    parts = _outputs(finals)
    args = _head(vaapi) + ["-i", str(src), "-filter_complex", ";".join(g)]
    for (vm, am), part in zip(maps, parts):
        args += ["-map", vm]
        if am:
            args += ["-map", am] + _aenc(akbps)
        args += _venc(profile, vaapi) + STRIP_META + FASTSTART + [str(part)]
    title = "Đang crop 9:16…" if vertical else "Đang cắt…"
    return Plan(title, args, finals, parts, duration, src=src)


def clamp_logo(r: Rect, width: int, height: int) -> Rect:
    """delogo cần khung nằm trong ảnh, cách mép ít nhất 1 px."""
    x = min(max(1, r.x), width - 3)
    y = min(max(1, r.y), height - 3)
    w = max(2, min(r.w, width - 1 - x))
    h = max(2, min(r.h, height - 1 - y))
    return Rect(x, y, w, h)


def logo_filters(info: MediaInfo, rects: list[Rect]) -> list[str]:
    out = []
    for r in rects:
        c = clamp_logo(r, info.width, info.height)
        out.append(f"delogo=x={c.x}:y={c.y}:w={c.w}:h={c.h}")
    return out


def logo(info: MediaInfo, rects: list[Rect], vaapi: bool) -> Plan:
    if not rects:
        raise ValueError("Chưa chọn vùng logo")
    src = info.path
    final = naming.output_for(src, "xóa logo")
    part = naming.part_path(final)
    vf = ",".join(logo_filters(info, rects) + _color(info) + [EVEN, _upload(vaapi)])
    args = _head(vaapi) + ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf]
    args += _venc("high", vaapi)
    if info.has_audio:
        args += ["-c:a", "copy"] if info.acodec == "aac" else _aenc(HIGH_AUDIO_KBPS)
    args += STRIP_META + FASTSTART + [str(part)]
    return Plan("Đang xóa logo…", args, [final], [part], info.duration, src=src)


def crop_rect_916(width: int, height: int, center_x: float, center_y: float | None = None) -> Rect:
    """Khung 9:16 lớn nhất vừa trong ảnh, đặt quanh tâm cho trước (pixel ảnh gốc)."""
    w = int(height * 9 / 16) // 2 * 2
    h = height // 2 * 2
    if w > width:
        w = width // 2 * 2
        h = int(width * 16 / 9) // 2 * 2
    cy = height / 2 if center_y is None else center_y
    x = int(min(max(0, center_x - w / 2), width - w)) // 2 * 2
    y = int(min(max(0, cy - h / 2), height - h)) // 2 * 2
    return Rect(x, y, w, h)
