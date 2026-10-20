# dropwheel

Công cụ xử lý file media bằng kéo thả: khi đang kéo một file và giữ phím bổ trợ, một menu hình tròn hiện quanh con trỏ; thả file vào ô nào thì công cụ làm thao tác đó và tạo file kết quả ngay cạnh file gốc.

## Nguồn cảm hứng

Video demo một ứng dụng macOS (22 giây, không lời thoại):
- Kéo file + **Shift** → vòng chuyển định dạng: MP4, MOV, MKV, M4A, MP3, GIF.
- Kéo file + **Shift + Option** → vòng chỉnh sửa: Compress, Remove Meta, Mute, Trim, Crop, Speed, Snapshot, Split.
- Crop/Trim mở một cửa sổ nhỏ để chỉnh rồi bấm Apply.
- Có thông báo tiến trình ("Converting to MP4"); file kết quả đặt cạnh file gốc (`geese.mp4`, `geese Cropped.mp4`) và có thể kéo tiếp để xử lý thêm.

## Môi trường đích

- Trước mắt chỉ chạy trên máy của user: Omarchy (Arch Linux), Hyprland 0.56 (Wayland), file manager Nautilus. Đây là máy chính của user; Windows có thể làm sau.
- Hiện user đổi/cắt video bằng trang web online (tải lên, chờ, tải về). Công cụ này để bỏ các bước đó.
- Đã có sẵn `ffmpeg` tại `/usr/bin/ffmpeg`, bản build có h264/hevc_vaapi, h264/hevc_qsv, libx264, libx265.
- Phần cứng: Intel Tiger Lake, Iris Xe (có Quick Sync, mã hóa H.264/HEVC bằng phần cứng), 8 luồng CPU, `/dev/dri/renderD128`. Chưa kiểm tra driver VAAPI (chưa có `vainfo`).

## Phạm vi bản đầu (user chọn)

1. Chuyển sang MP4
2. Nén video: mục đích là gửi qua Zalo và Messenger
3. Cắt đoạn (trim theo thời gian)

Hướng tương lai: chọn được codec khi xuất (H.264, H.265/HEVC).

Ưu tiên của user: **nhanh** (xong trong vài giây) hơn file nhỏ; file hơi to cũng được. Tránh mã hóa lại khi có thể.

Đang cân nhắc thêm: xóa metadata, xóa watermark.

Xóa watermark: bản đầu **chỉ làm tầng nhanh** (ffmpeg `delogo`, user kéo khung quanh logo). Tầng AI (WatermarkRemover-AI / video-subtitle-remover, cài riêng, gọi qua CLI) để sau.

## Quyết định đã chốt: Nén (không bàn lại)

User chốt ngày 2026-10-20. Phần lớn chi tiết kỹ thuật là lựa chọn của Claude; mức "Cân bằng" do user chọn.

Một chế độ mặc định duy nhất: **"Nén để gửi"** (Zalo/Messenger). Không có thanh trượt bitrate hay hỏi thông số.

- **Encoder:** `h264_vaapi` (Quick Sync qua VAAPI). Nếu VAAPI không dùng được thì tự lùi về `libx264 -preset veryfast`.
- **Video của user:** dài dưới 3 phút hoặc reel ngắn, gửi Zalo cho nhiều người xem. Mục tiêu là người nhận tải nhanh, bấm là xem được; quan trọng hơn độ nét tối đa.
- **Kiểm soát chất lượng (user chọn mức "Cân bằng"):** nén theo chất lượng **có trần**: QVBR/VBR trên VAAPI (hoặc CRF + `maxrate`/`bufsize` với libx264). Trần tổng khoảng **1,5 Mbps (~11 MB/phút)**: video ~1,35 Mbps + âm thanh 128 kbps. Ước lượng: reel 30 giây ~6 MB, video 3 phút ~34 MB. Cảnh tĩnh sẽ nhỏ hơn trần. Giá trị cụ thể chỉnh một lần bằng vài clip thật của user rồi giữ cố định.
- Chưa kiểm tra: giới hạn dung lượng video của Zalo, và việc Zalo có tự nén lại khi gửi hay không.
- **Độ phân giải:** cạnh dài tối đa 1280 (720p; video dọc thành 720×1280). Không bao giờ phóng to.
- **Khung hình:** tối đa 30 fps, không tăng.
- **Màu:** 8-bit `yuv420p` (tương thích mọi điện thoại). Video HDR/10-bit (ví dụ iPhone) được chuyển về SDR 8-bit.
- **Âm thanh:** AAC 128 kbps. Nguồn đã là AAC ≤128 kbps thì copy nguyên.
- **File:** MP4, `+faststart` (mở là phát ngay trên Messenger), xóa toàn bộ metadata (GPS, tên máy).
- **Bỏ qua thông minh:** nếu file kết quả không nhỏ hơn file gốc thì giữ file gốc và báo "đã đủ nhẹ".
- **Một lần chạy:** khi cắt đoạn/crop kèm nén thì gộp thành một lệnh ffmpeg, không encode hai lần.

Để sau (không thuộc bản đầu):
- Tùy chọn **H.265/HEVC** (`hevc_vaapi`), cùng pipeline. Không làm mặc định vì có máy/ứng dụng không phát được.
- **"Nén kỹ"** bằng ab-av1 (tìm CRF theo VMAF), chạy ngầm, chậm hơn.
- Nén theo giới hạn dung lượng cụ thể.

## Crop

Mục đích chính: đổi video ngang thành dọc **9:16** cho Reels/TikTok. Dùng chung cửa sổ "kéo khung" với xóa logo.

User chọn cách **A: cắt khung 9:16** (kéo khung chọn phần giữ lại, mất hai bên). Không làm nền mờ hay viền đen. Xuất 720×1280 theo phần nén đã chốt.

- Khung **đứng yên** trong mỗi đoạn; không cần bám theo chuyển động hay AI.
- Một video có thể tạo **nhiều đoạn crop**, mỗi đoạn có vị trí khung + thời gian bắt đầu/kết thúc riêng. Ví dụ của user: khung hình 3 người nói chuyện, crop lần lượt từng người, mỗi người một khoảng thời gian.
- **"Cắt đoạn" (trim) dùng chung cửa sổ này** (user đồng ý): công tắc "Khung 9:16" tắt thì chỉ cắt theo thời gian, giữ khung ngang. Trên vòng tròn chỉ có một ô "Cắt / Crop".
- Mọi đoạn xử lý trong một lần chạy ffmpeg (lựa chọn của Claude).
- Khi xuất, user chọn (công tắc "Nối thành 1 video"): **mỗi đoạn một file riêng**, hoặc **nối các đoạn thành một video dọc** theo thứ tự thời gian.

## Cách gọi vòng tròn

User chọn **giống hệt video**: đang kéo file (từ Nautilus) thì bấm phím, vòng tròn hiện quanh con trỏ, thả file vào ô.
**Phím gọi (user chọn): `SUPER + Q`.** Đã kiểm tra là chưa bị chiếm (2026-10-20). Không dùng Shift vì sẽ đụng việc gõ chữ hoa.

### Giao diện vòng tròn (user chọn)

- Kiểu **A: vành khuyên kính mờ**, 4 múi liền nhau (MP4 · Nén · Cắt/Crop · Logo), ô đang rê vào bật màu cam; **tâm vòng hiện tên thao tác** đang rê vào ("Thả vào ô" khi chưa vào ô nào).
- **Bắt buộc có chuyển động:** các múi bung ra so le (~0,4 s, nảy nhẹ); ô nảy khi rê vào; khi thả thì dấu ✓ nảy lên, vòng thu lại, thông báo tiến độ trượt lên ở góc màn hình.
- Không có file kéo vào thì tự ẩn sau 3 giây.
- Mockup: `.superpowers/brainstorm/*/content/wheel-motion-v2.html`.

### Kết quả spike (2026-10-20, `spike/wheel_spike.py`, code bỏ đi): **KHẢ THI**

- Phím tắt Hyprland (gán bằng `hyprctl eval` Lua, `hl.bind`) **vẫn chạy khi Nautilus đang kéo file**.
- Cửa sổ layer-shell (GTK4 + `gtk4-layer-shell`, Python/PyGObject, đã có sẵn trên máy) hiện ra giữa lúc kéo **vẫn nhận được sự kiện kéo thả**: đổi màu ô khi rê vào, nhận đường dẫn file khi thả.
- **Nautilus chỉ đề nghị hành động MOVE** (`actions=2`). Drop target phải nhận MOVE. Đã thả 4 lần kiểu MOVE vào vòng tròn: **file gốc vẫn còn nguyên**, Nautilus không tự xóa. Vòng tròn tuyệt đối không được di chuyển hay xóa file.
- Python + gtk4-layer-shell cần `LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so`.
- Từ lúc bấm phím đến khi vòng tròn hiện mất ~125 ms, phần lớn do gọi `hyprctl` qua subprocess; dùng socket Hyprland trực tiếp sẽ nhanh hơn.
- Cấu hình Hyprland của user là **Lua** (`~/.config/hypr/*.lua`, Omarchy). `F9` đã bị voxtype dùng.
- Shift trên Linux nghĩa là "di chuyển" khi kéo; vì nhận MOVE nên vẫn chạy được.
- **UX user yêu cầu:** nếu không có file kéo vào thì vòng tròn chỉ hiện **3 giây** rồi tự ẩn.

## Trạng thái

**Thiết kế đã được user duyệt ngày 2026-10-20**: `docs/superpowers/specs/2026-10-20-dropwheel-design.md`. Tài liệu đó là nguồn sự thật; mục nào trong file này mâu thuẫn với nó thì theo tài liệu.
Đang triển khai theo `docs/superpowers/plans/2026-10-20-dropwheel-plan.md`.

## Quy tắc

- Mọi thao tác xóa hoặc ghi đè phải hỏi user trước (xem `~/.claude/CLAUDE.md`).
- Trao đổi với user bằng tiếng Việt.
