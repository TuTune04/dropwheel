"""Chọn encoder H.264: VAAPI (Quick Sync) nếu chạy được, không thì libx264."""
from __future__ import annotations

import functools
import os
import subprocess

VAAPI_DEVICE = os.environ.get("DROPWHEEL_VAAPI_DEVICE", "/dev/dri/renderD128")


@functools.cache
def has_vaapi() -> bool:
    if os.environ.get("DROPWHEEL_NO_VAAPI"):
        return False
    if not os.path.exists(VAAPI_DEVICE):
        return False
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-vaapi_device", VAAPI_DEVICE,
             "-f", "lavfi", "-i", "color=c=black:s=256x144:d=0.2",
             "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-f", "null", "-"],
            capture_output=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0
