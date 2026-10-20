# dropwheel: Kế hoạch triển khai

Thiết kế: `docs/superpowers/specs/2026-10-20-dropwheel-design.md` (đã duyệt 2026-10-20).

## Bố cục code

```
bin/dropwheel              launcher shell: đặt LD_PRELOAD rồi chạy python -m dropwheel
src/dropwheel/
  __main__.py              CLI: `dropwheel daemon` | `dropwheel show` | `dropwheel edit <file>` (debug)
  probe.py                 ffprobe → MediaInfo (thuần, test được)
  naming.py                tên file kết quả + tránh trùng (thuần)
  encoders.py              phát hiện VAAPI, lùi về libx264
  commands.py              dựng lệnh ffmpeg cho MP4 / Nén / Cắt-Crop / Logo (thuần)
  jobs.py                  hàng đợi, chạy ffmpeg (nice), đọc -progress, file tạm → đổi tên, hủy
  hypr.py                  socket IPC Hyprland: cursorpos, monitors
  ipc.py                   Unix socket $XDG_RUNTIME_DIR/dropwheel.sock (lệnh "show")
  wheel.py                 vòng tròn layer-shell + chuyển động (cairo, đồng hồ khung hình)
  toast.py                 thẻ tiến độ layer-shell
  editor.py                cửa sổ Cắt/Crop + chế độ Logo
  app.py                   Gtk.Application nối mọi thứ
tests/                     unittest (stdlib; máy không có pytest, không cài thêm)
install.sh                 cài vào ~/.local, hỏi trước khi sửa bindings.lua / autostart.lua
```

## Các bước

1. **Lõi thuần + test:** `probe`, `naming`, `encoders`, `commands`. Unit test cho đặt tên và dựng lệnh; test tích hợp với video tự sinh bằng `lavfi`, kiểm tra kết quả bằng `ffprobe`.
2. **`jobs`:** hàng đợi tuần tự, `nice`, tiến độ, file tạm `.tên.dropwheel-part.mp4`, hủy; quy tắc "Đã đủ nhẹ" và "Đã là MP4".
3. **Daemon + IPC + `hypr`:** `dropwheel show` hiện vòng tròn tại con trỏ; mục tiêu dưới 50 ms.
4. **Kiểm tra rủi ro số 1 cùng user:** gán Super+Q tạm thời (`hyprctl eval`), user thử kéo file.
5. **`wheel`:** kiểu A, tâm hiện tên thao tác, chuyển động (bung so le, nảy khi rê, ✓ rồi thu lại), tự ẩn sau 3 giây, nhận MOVE, không đụng file gốc.
6. **`toast`:** trượt lên, tiến độ, ✕ / Hủy hết, "Xong · N MB" (bấm vào mở thư mục), thẻ lỗi màu đỏ.
7. **`editor`:** xem trước bằng GStreamer, thanh thời gian, các đoạn có màu, khung 9:16, Nối thành 1 video, chế độ Logo nhiều hình chữ nhật + xem trước.
8. **`install.sh`:** cài và gán phím, có hỏi trước.
9. **Chỉnh mức nén** bằng 2–3 clip trong `~/Videos` do user chọn (chỉ đọc; kết quả ghi vào scratchpad); user chốt.
10. **Danh sách kiểm tra bằng tay** cùng user.
