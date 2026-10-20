"""Tên file kết quả. Không bao giờ trả về đường dẫn đã tồn tại."""
from __future__ import annotations

from pathlib import Path


def unique(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def output_for(src: Path, label: str | None) -> Path:
    """`label=None` → `tên.mp4`; còn lại → `tên - label.mp4`."""
    name = src.stem if label is None else f"{src.stem} - {label}"
    return unique(src.with_name(name + ".mp4"))


def part_path(final: Path) -> Path:
    """File tạm cùng thư mục, đổi tên thành `final` khi xong."""
    return final.with_name(f".{final.stem}.dropwheel-part.mp4")
