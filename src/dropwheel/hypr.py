"""Socket IPC của Hyprland (nhanh hơn gọi `hyprctl` qua subprocess ~100 lần)."""
from __future__ import annotations

import json
import os
import socket
import subprocess


def _sock_path() -> str:
    return os.path.join(os.environ["XDG_RUNTIME_DIR"], "hypr",
                        os.environ["HYPRLAND_INSTANCE_SIGNATURE"], ".socket.sock")


def request(cmd: str) -> str:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect(_sock_path())
        s.sendall(cmd.encode())
        chunks = []
        while True:
            c = s.recv(65536)
            if not c:
                break
            chunks.append(c)
    finally:
        s.close()
    return b"".join(chunks).decode()


def query(cmd: str):
    return json.loads(request("j/" + cmd))


def cursor_and_monitor() -> tuple[float, float, dict]:
    """(x, y) toàn cục theo tọa độ logic và monitor đang chứa con trỏ."""
    cur = query("cursorpos")
    x, y = cur["x"], cur["y"]
    mons = query("monitors")
    for m in mons:
        mw, mh = m["width"] / m["scale"], m["height"] / m["scale"]
        if m["transform"] % 2 == 1:
            mw, mh = mh, mw
        if m["x"] <= x < m["x"] + mw and m["y"] <= y < m["y"] + mh:
            return x, y, m
    return x, y, next((m for m in mons if m.get("focused")), mons[0])


def eval_lua(code: str) -> bool:
    """Áp quy tắc lúc chạy (không sửa file cấu hình). Trả về False nếu Hyprland từ chối."""
    try:
        r = subprocess.run(["hyprctl", "eval", code], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and r.stdout.strip() == "ok"


def watch_events(on_event) -> None:
    """Nghe socket sự kiện của Hyprland (.socket2.sock); gọi on_event(tên, dữ liệu) trong vòng lặp GLib."""
    from gi.repository import GLib

    path = _sock_path().replace(".socket.sock", ".socket2.sock")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    s.setblocking(False)
    buf = bytearray()

    def readable(*_):
        try:
            chunk = s.recv(65536)
        except BlockingIOError:
            return True
        if not chunk:
            return False
        buf.extend(chunk)
        while b"\n" in buf:
            line, _, rest = bytes(buf).partition(b"\n")
            buf[:] = rest
            name, _, data = line.decode(errors="replace").partition(">>")
            on_event(name, data)
        return True

    GLib.io_add_watch(s.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, readable)
    watch_events._sock = s  # giữ tham chiếu
