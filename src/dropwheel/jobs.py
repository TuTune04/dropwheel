"""Hàng đợi chạy ffmpeg tuần tự, mức ưu tiên thấp. Không phụ thuộc GTK.

An toàn file (thiết kế §9): chỉ ghi vào file tạm `.tên.dropwheel-part.mp4` do chính
dropwheel tạo; xong thì gắn sang tên chính thức bằng os.link (không bao giờ ghi đè),
lỗi/hủy thì bỏ file tạm. File nguồn không bao giờ bị đụng tới.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import naming
from .commands import AlreadyDone, Plan
from .probe import ProbeError

log = logging.getLogger(__name__)


@dataclass
class Job:
    title: str                        # hiện trên thẻ trước khi plan sẵn sàng
    build: Callable[[], Plan]          # gọi trong luồng worker (có thể probe, có thể lỗi)
    name: str = ""                     # tên file nguồn để hiển thị


@dataclass
class Event:
    kind: str                          # start | progress | done | skipped | error | cancelled | idle
    job: Job | None = None
    index: int = 0
    total: int = 0
    fraction: float = 0.0
    message: str = ""
    outputs: tuple[Path, ...] = ()
    bytes: int = 0


class Runner:
    def __init__(self, on_event: Callable[[Event], None]):
        self.on_event = on_event
        self._q: deque[Job] = deque()
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._proc: subprocess.Popen | None = None
        self._cancel_current = False
        self._done_count = 0
        threading.Thread(target=self._loop, daemon=True, name="dropwheel-jobs").start()

    # --- API --------------------------------------------------------------
    def submit(self, jobs: list[Job]) -> None:
        with self._lock:
            self._q.extend(jobs)
            self._wake.notify()

    def pending(self) -> int:
        with self._lock:
            return len(self._q)

    def cancel_current(self) -> None:
        with self._lock:
            self._cancel_current = True
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    def cancel_all(self) -> None:
        with self._lock:
            self._q.clear()
        self.cancel_current()

    # --- worker -----------------------------------------------------------
    def _loop(self):
        while True:
            with self._lock:
                while not self._q:
                    if self._done_count:
                        self._done_count = 0
                        self._emit(Event("idle"))
                    self._wake.wait()
                job = self._q.popleft()
                total = self._done_count + 1 + len(self._q)
                index = self._done_count + 1
                self._cancel_current = False
            try:
                self._run(job, index, total)
            except Exception as e:  # không để luồng chết
                log.exception("job lỗi")
                self._emit(Event("error", job, index, total, message=str(e) or "Lỗi không rõ"))
            with self._lock:
                self._done_count += 1

    def _emit(self, ev: Event):
        try:
            self.on_event(ev)
        except Exception:
            log.exception("on_event lỗi")

    def _run(self, job: Job, index: int, total: int):
        self._emit(Event("start", job, index, total, message=job.title))
        try:
            plan = job.build()
        except AlreadyDone as e:
            self._emit(Event("skipped", job, index, total, message=str(e)))
            return
        except (ProbeError, ValueError) as e:
            self._emit(Event("error", job, index, total, message=str(e)))
            return
        self._emit(Event("start", job, index, total, message=plan.title))
        while True:
            rc, cancelled, err = self._exec(plan, job, index, total)
            if rc != 0 and not cancelled and plan.fallback is not None:
                log.warning("cách nhanh lỗi, chạy lại bằng cách dự phòng:\n%s", err)
                self._discard(plan.parts)
                plan = plan.fallback
                continue
            break
        self._finish(plan, job, index, total, rc, cancelled, err)

    def _exec(self, plan: Plan, job: Job, index: int, total: int) -> tuple[int, bool, str]:
        log.info("chạy: %s", " ".join(plan.args))

        stderr_tail: list[str] = []
        with self._lock:
            if self._cancel_current:
                return -1, True, ""
            self._proc = subprocess.Popen(
                ["nice", "-n", "10", *plan.args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, stdin=subprocess.DEVNULL)
        proc = self._proc

        def read_err():
            for line in proc.stderr:
                stderr_tail.append(line.rstrip())
                del stderr_tail[:-20]
        t = threading.Thread(target=read_err, daemon=True)
        t.start()

        dur = max(plan.duration, 0.001)
        for line in proc.stdout:
            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                self._emit(Event("progress", job, index, total, fraction=min(1.0, us / 1e6 / dur)))
        proc.wait()
        t.join(timeout=2)
        with self._lock:
            self._proc = None
            cancelled = self._cancel_current
        return proc.returncode, cancelled, "\n".join(stderr_tail)

    def _finish(self, plan: Plan, job: Job, index: int, total: int, rc: int, cancelled: bool, err: str):
        if cancelled or rc != 0:
            self._discard(plan.parts)
            if cancelled:
                self._emit(Event("cancelled", job, index, total, message="Đã hủy"))
            else:
                log.error("ffmpeg lỗi %s:\n%s", rc, err)
                self._emit(Event("error", job, index, total, message="ffmpeg báo lỗi, xem log"))
            return

        if plan.must_shrink and plan.src is not None:
            new = plan.parts[0].stat().st_size
            if new >= plan.src.stat().st_size:
                self._discard(plan.parts)
                self._emit(Event("skipped", job, index, total, message="Đã đủ nhẹ"))
                return

        outs = tuple(self._publish(p, f) for p, f in zip(plan.parts, plan.finals))
        size = sum(o.stat().st_size for o in outs)
        self._emit(Event("done", job, index, total, fraction=1.0, outputs=outs, bytes=size))

    @staticmethod
    def _publish(part: Path, final: Path) -> Path:
        """Gắn file tạm sang tên chính thức mà không bao giờ ghi đè."""
        while True:
            final = naming.unique(final)
            try:
                os.link(part, final)
                break
            except FileExistsError:
                continue
            except OSError:
                # Ổ không hỗ trợ hard link (FAT/exFAT): đổi tên ngay sau khi kiểm tra trùng.
                os.rename(part, final)
                return final
        part.unlink()
        return final

    @staticmethod
    def _discard(parts: list[Path]):
        for p in parts:
            # Chỉ xóa file tạm do chính dropwheel tạo.
            if p.name.endswith(".dropwheel-part.mp4") and p.exists():
                p.unlink()
