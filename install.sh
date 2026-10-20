#!/bin/sh
# Cài dropwheel cho người dùng hiện tại (thiết kế §6).
#   - chép mã nguồn vào ~/.local/share/dropwheel, lệnh vào ~/.local/bin/dropwheel
#   - thêm Alt+Q vào ~/.config/hypr/bindings.lua và tự khởi động vào autostart.lua
# Không xóa hay sửa dòng có sẵn nào; chỉ thêm dòng mới có đánh dấu. Mọi thay đổi đều hỏi trước.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
share="$HOME/.local/share/dropwheel"
bin="$HOME/.local/bin/dropwheel"
hypr="$HOME/.config/hypr"
mark="-- dropwheel (install.sh)"
bind_line="o.bind(\"ALT + Q\", \"dropwheel: vòng tròn xử lý video\", \"$bin show\")"
auto_line="o.launch_on_start(\"$bin daemon\")"

ask() {
    printf '%s [y/N] ' "$1"
    read -r ans || ans=
    case "$ans" in y|Y|yes|có|co) return 0 ;; *) return 1 ;; esac
}

need() {
    command -v "$1" >/dev/null 2>&1 || { echo "Thiếu: $1"; exit 1; }
}
need python3
need ffmpeg
need ffprobe
need hyprctl
[ -e /usr/lib/libgtk4-layer-shell.so ] || { echo "Thiếu gtk4-layer-shell (pacman -S gtk4-layer-shell)"; exit 1; }

if [ -e "$bin" ] && ! grep -q "dropwheel" "$bin" 2>/dev/null; then
    echo "$bin đã tồn tại và không phải của dropwheel. Dừng lại, không ghi đè."
    exit 1
fi

echo "Sẽ cài:"
echo "  $share/src   (mã nguồn; nếu đã có bản cũ của dropwheel thì thay bằng bản mới)"
echo "  $bin"
ask "Tiếp tục?" || { echo "Đã hủy."; exit 0; }

mkdir -p "$share" "$HOME/.local/bin"
tmp="$share/src.new"
rm -rf "$tmp"
cp -r "$here/src" "$tmp"
find "$tmp" -name __pycache__ -type d -prune -exec rm -rf {} +
[ -d "$share/src" ] && mv "$share/src" "$share/src.old"
mv "$tmp" "$share/src"
rm -rf "$share/src.old"
sed "s|src=\${DROPWHEEL_SRC:-\$here/../src}|src=\${DROPWHEEL_SRC:-$share/src}|" "$here/bin/dropwheel" > "$bin"
chmod +x "$bin"
echo "✓ Đã cài $bin"

add_line() {  # $1 = file, $2 = dòng, $3 = mô tả
    if grep -qF "$2" "$1" 2>/dev/null; then
        echo "✓ $3 đã có sẵn trong $1"
        return
    fi
    echo
    echo "Sẽ THÊM vào cuối $1:"
    echo "  $mark"
    echo "  $2"
    if ask "Đồng ý?"; then
        printf '\n%s\n%s\n' "$mark" "$2" >> "$1"
        echo "✓ Đã thêm $3"
    else
        echo "Bỏ qua $3"
    fi
}
add_line "$hypr/bindings.lua" "$bind_line" "phím Alt+Q"
add_line "$hypr/autostart.lua" "$auto_line" "tự khởi động"

if ! "$bin" ping 2>/dev/null; then
    setsid -f "$bin" daemon >/dev/null 2>&1
    echo "✓ Đã chạy tiến trình nền"
else
    echo "Tiến trình nền đang chạy; muốn dùng bản vừa cài thì chạy: $bin quit && setsid -f $bin daemon"
fi
echo "Xong. Kéo một video trong Nautilus rồi bấm Alt+Q."
