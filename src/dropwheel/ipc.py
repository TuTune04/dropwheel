"""Unix socket để `dropwheel show` báo cho tiến trình nền."""
from __future__ import annotations

import logging
import os
import socket
from typing import Callable


def sock_path() -> str:
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "dropwheel.sock")


def send(cmd: str) -> bool:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect(sock_path())
        s.sendall(cmd.encode() + b"\n")
        s.shutdown(socket.SHUT_WR)
        return True
    except OSError:
        return False
    finally:
        s.close()


class Server:
    def __init__(self, handler: Callable[[str], None]):
        from gi.repository import GLib

        self.handler = handler
        path = sock_path()
        if os.path.exists(path):
            if send("ping"):
                raise RuntimeError("dropwheel đang chạy rồi")
            os.unlink(path)  # socket cũ do lần chạy trước của dropwheel để lại
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        os.chmod(path, 0o600)
        self.sock.listen(8)
        self.sock.setblocking(False)
        GLib.io_add_watch(self.sock.fileno(), GLib.PRIORITY_HIGH, GLib.IO_IN, self._accept)

    def _accept(self, *_):
        try:
            conn, _ = self.sock.accept()
        except BlockingIOError:
            return True
        conn.settimeout(0.5)
        chunks = []
        try:
            while len(chunks) < 64:          # tối đa ~4 MB
                c = conn.recv(65536)
                if not c:
                    break
                chunks.append(c)
        except OSError:
            pass
        finally:
            conn.close()
        data = b"".join(chunks).decode(errors="replace").strip()
        for line in data.splitlines():
            if line and line != "ping":
                try:
                    self.handler(line)
                except Exception:
                    # Lỗi trong một lệnh không được làm ngừng socket.
                    logging.getLogger(__name__).exception("lệnh %r lỗi", line)
        return True
