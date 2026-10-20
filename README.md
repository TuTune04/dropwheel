# dropwheel

Xử lý video bằng kéo thả trên Hyprland. Đang kéo một file video trong Nautilus, bấm **Alt+Q**: một vòng tròn bung ra quanh con trỏ. Thả file vào ô nào thì việc đó được làm ngay trên máy, file kết quả nằm cạnh file gốc.

| Ô | Làm gì |
|---|---|
| **MP4** | Chuyển sang MP4. Chỉ đổi vỏ file nếu được, nên xong trong khoảng 1 giây |
| **Nén** | Nén để gửi Zalo/Messenger: 720p, H.264, ~11 MB/phút, xóa GPS/metadata |
| **Cắt/Crop** | Cắt nhiều đoạn theo thời gian, crop dọc 9:16 cho Reels/TikTok; xuất mỗi đoạn một file hoặc nối thành một video |
| **Logo** | Xóa watermark cố định bằng `delogo` của ffmpeg |

File gốc không bao giờ bị xóa, di chuyển hay ghi đè. Trùng tên thì tự đánh số.

## Yêu cầu

Hyprland (cấu hình Lua), Nautilus, Python 3, GTK 4, `gtk4-layer-shell`, PyGObject, GStreamer, `ffmpeg`. Mã hóa phần cứng qua VAAPI (Intel Quick Sync) nếu có; không có thì dùng `libx264`.

## Chạy thử

```sh
bin/dropwheel daemon      # tiến trình nền
bin/dropwheel show        # hiện vòng tròn (gán vào Alt+Q)
bin/dropwheel cut  video.mov
bin/dropwheel logo video.mov
```

Gán phím tạm thời (mất khi Hyprland nạp lại cấu hình):

```sh
hyprctl eval 'hl.bind("ALT + Q", hl.dsp.exec_cmd("'"$PWD"'/bin/dropwheel show"))'
```

## Test

```sh
PYTHONPATH=src:tests python3 -m unittest discover -s tests
```

Test tích hợp tự sinh video bằng `lavfi`, không dùng file thật.

Thiết kế: [`docs/superpowers/specs/2026-10-20-dropwheel-design.md`](docs/superpowers/specs/2026-10-20-dropwheel-design.md)
