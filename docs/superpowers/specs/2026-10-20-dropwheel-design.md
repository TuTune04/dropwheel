# dropwheel: Thiết kế

Ngày: 2026-10-20 · Trạng thái: **bản nháp chờ user duyệt**

Quy ước: những gì không ghi chú là do **user quyết định** trong buổi brainstorm. Mục ghi *(Claude chọn)* là lựa chọn của Claude, user cần soát lại. Mục ghi *(để người làm quyết)* là chi tiết người làm tự chọn được.

---

## 1. Ý tưởng và lý do

**dropwheel** là công cụ chạy ngầm trên máy Linux của user. Nó thay thế việc lên trang web để đổi định dạng, nén hay cắt video (tải lên, chờ, tải về).

Cách dùng: đang **kéo một file video trong Nautilus** thì bấm **Alt+Q**. Một **vòng tròn có 4 ô** bung ra quanh con trỏ. **Thả file vào ô nào thì việc đó được làm ngay trên máy**, file kết quả nằm cạnh file gốc.

Ý tưởng lấy từ một video demo ứng dụng macOS: kéo file, giữ phím, menu tròn hiện ra, thả vào ô.

**Người dùng:** chỉ một người, chính user, trên máy chính. Video thường dài dưới 3 phút hoặc là reel ngắn. Hai mục đích chính:
- Gửi qua **Zalo/Messenger** cho nhiều người xem: người nhận phải tải nhanh và bấm là xem được ngay.
- Đăng **Reels/TikTok** (video dọc 9:16).

**Thành công là khi:** user không còn mở trang web đổi/nén/cắt video nữa.

## 2. Mục tiêu

1. Kéo file, bấm Alt+Q, thả vào ô. Không phải mở ứng dụng nào.
2. **Nhanh** (ưu tiên của user): những việc đơn giản xong trong vài giây. File hơi to cũng chấp nhận được. Không mã hóa lại khi không cần.
3. 4 thao tác: **MP4 · Nén · Cắt/Crop · Logo**.
4. Vòng tròn đẹp, gọn và **có chuyển động** (bắt buộc).
5. File gốc luôn an toàn.

## 3. Không làm trong bản đầu

- Các định dạng khác ngoài MP4 (MOV, MKV, GIF, M4A, MP3…) và các thao tác Mute, Speed, Snapshot, Split.
- Windows hay các môi trường desktop khác. Chỉ hỗ trợ Hyprland và Nautilus trên máy này.
- Xóa watermark bằng AI (WatermarkRemover-AI, video-subtitle-remover…). Để sau, gọi qua CLI như một công cụ cài riêng.
- Lựa chọn H.265/HEVC, "Nén kỹ" bằng ab-av1, nén theo một giới hạn dung lượng cụ thể. Để sau.
- Khung crop bám theo chuyển động, nền mờ, viền đen.
- Trang cài đặt hay thanh trượt thông số.

## 4. Những điều tuyệt đối không được xảy ra

- **Xóa, di chuyển hoặc ghi đè file gốc**, hay ghi đè bất kỳ file nào đã có. Nautilus chỉ đề nghị hành động MOVE khi kéo, nên dropwheel phải *nhận* MOVE nhưng **không bao giờ đụng tới file gốc** (xem §9).
- **Làm máy đơ** trong lúc xử lý.
- **Vòng tròn hiện ra hoặc chặn click khi user không muốn**, ví dụ treo trên màn hình.
- **Bắt user chọn thông số kỹ thuật.**

## 5. Ràng buộc môi trường (đã kiểm tra trên máy)

- Omarchy (Arch Linux), **Hyprland 0.56** (Wayland). Cấu hình Hyprland viết bằng **Lua** (`~/.config/hypr/*.lua`); phím tắt khai báo bằng `hl.bind` (hoặc helper `o.bind` của Omarchy). `F9` đã bị voxtype dùng; **Alt+Q còn trống**.
- File manager: **Nautilus**.
- Phần cứng: Intel Tiger Lake, **Iris Xe (Quick Sync)**, 8 luồng CPU, `/dev/dri/renderD128`. Chưa kiểm tra driver VAAPI.
- Đã cài sẵn: `ffmpeg` (có `h264_vaapi`, `hevc_vaapi`, `h264_qsv`, `libx264`, `libx265`), Python 3.14, GTK 4.22, `gtk4-layer-shell` 1.3, PyGObject 3.56, GStreamer 1.28 (good/bad/libav).

## 6. Kiến trúc *(Claude chọn, dựa trên spike đã chạy được)*

- **Ngôn ngữ/giao diện:** Python + GTK4 + `gtk4-layer-shell`. Bản spike đã chứng minh tổ hợp này chạy được. Phải nạp `LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so`, nếu không thì cửa sổ không thành layer surface.
- **Tiến trình nền `dropwheel`** chạy suốt phiên làm việc, giữ sẵn cửa sổ vòng tròn (ẩn) để hiện ra tức thì. Lệnh `dropwheel show` (được gán cho Alt+Q) báo cho tiến trình nền qua một Unix socket trong `$XDG_RUNTIME_DIR`.
- **Vị trí con trỏ và màn hình** lấy qua socket IPC của Hyprland, không gọi `hyprctl` qua subprocess. Spike gọi qua subprocess mất ~125 ms. **Mục tiêu: từ lúc bấm phím đến khi vòng tròn hiện dưới 50 ms.**
- **Xử lý video:** gọi `ffmpeg`/`ffprobe` qua subprocess; tiến độ đọc từ `-progress`. Các việc chạy **lần lượt từng việc một** với mức ưu tiên thấp (`nice`) để không làm máy đơ.
- **Xem trước video trong cửa sổ Cắt/Crop/Logo:** GStreamer (`Gtk.Video`/`GtkMediaFile`) hoặc ảnh khung hình do ffmpeg xuất ra *(để người làm quyết)*. Yêu cầu: kéo thanh thời gian thì xem được khung hình gần như ngay.
- **Cài đặt:** một script cài vào `~/.local` (code và lệnh `dropwheel`). Script này có thêm phím Alt+Q vào `~/.config/hypr/bindings.lua` và thêm lệnh tự khởi động vào `~/.config/hypr/autostart.lua`. **Trước khi sửa file cấu hình, script phải in đúng những dòng sẽ thêm và hỏi user.** Không được ghi đè hay xóa dòng có sẵn. Gỡ cài đặt cũng hỏi như vậy.

## 7. Vòng tròn

**Gọi ra:** Alt+Q, vòng tròn hiện **lấy con trỏ làm tâm**, trên màn hình đang chứa con trỏ, ở lớp overlay, không lấy focus bàn phím. Spike đã xác nhận phím tắt vẫn chạy khi Nautilus đang kéo file và vòng tròn hiện giữa chừng vẫn nhận được file thả vào. (Spike dùng F8. **Alt+Q cần được kiểm tra lại ngay từ đầu**, xem §13.)

**Hình dáng (kiểu A, user chọn):** vành khuyên kính mờ, 4 múi liền nhau theo thứ tự trên → phải → dưới → trái: **MP4 · Nén · Cắt/Crop · Logo**.
- Mỗi múi gồm biểu tượng và chữ. Múi đang được rê vào chuyển màu cam (#f05a28).
- **Tâm vòng hiện tên thao tác** của múi đang được rê vào. Khi chưa rê vào múi nào thì hiện "Thả vào ô".
- Đường kính khoảng 220 px. Màu kem trong mờ, hợp với giao diện Omarchy *(Claude chọn; tinh chỉnh khi làm)*.
- Mẫu tham khảo: `.superpowers/brainstorm/*/content/wheel-motion-v2.html` (mở bằng trình duyệt).

**Chuyển động (bắt buộc):**
- Hiện ra: các múi bung ra **so le** (~45 ms mỗi múi, tổng ~0,4 s), phóng to từ nhỏ, xoay nhẹ và nảy (overshoot).
- Rê vào múi: múi nảy lên ~7%, màu chuyển trong ~0,18 s, chữ ở tâm đổi theo.
- Thả: dấu ✓ xanh nảy lên ở tâm, vòng thu lại và mờ dần (~0,45 s), sau đó thông báo tiến độ trượt lên ở góc màn hình (§11).
- Chuyển động phải mượt trên Iris Xe. Không được làm chậm việc vòng tròn xuất hiện: vòng tròn phải hiện ra ngay rồi mới chạy hiệu ứng.

**Ẩn đi:**
- Nếu sau khi hiện **3 giây** mà không có file nào được kéo vào thì tự ẩn (user yêu cầu).
- File bị kéo ra khỏi vòng thì ẩn sau ~1 giây. Thả ra ngoài các múi thì ẩn, không làm gì.
- Vòng tròn chỉ chiếm vùng của chính nó, không phủ toàn màn hình, để click ở chỗ khác vẫn bình thường.

**Kiểu file nhận:**
- Chỉ nhận video (kiểm tra bằng `ffprobe`, có luồng video). File không phải video thì báo "Không phải video" và không làm gì.
- Thả **nhiều file**: MP4 và Nén xử lý **từng file một** (đưa vào hàng đợi). Cắt/Crop và Logo **chỉ lấy file đầu tiên** và báo cho user biết *(Claude chọn)*.

## 8. Bốn thao tác

### 8.1 MP4 *(Claude chọn chi tiết)*
- Nếu codec của nguồn đã hợp với MP4 (video H.264/HEVC, âm thanh AAC/MP3/ALAC) thì **chỉ đổi vỏ** (`-c copy`, `+faststart`). Xong trong khoảng một giây, không mất chất lượng.
- Nếu không, mã hóa lại sang H.264 bằng `h264_vaapi` ở **chất lượng cao, giữ nguyên độ phân giải và fps**, âm thanh AAC 192 kbps. Đây không phải nén.
- Giữ nguyên metadata. Nguồn đã là MP4 thì báo "Đã là MP4", không tạo file mới.

### 8.2 Nén ("Nén để gửi", đã chốt, không bàn lại)
Một chế độ duy nhất, không hỏi thông số. Mức **"Cân bằng"** do user chọn.
- Encoder `h264_vaapi`. Nếu VAAPI không chạy được thì tự chuyển sang `libx264 -preset veryfast`.
- Nén theo chất lượng **có trần**: QVBR/VBR trên VAAPI (hoặc CRF + `maxrate`/`bufsize` với libx264). Trần tổng **~1,5 Mbps (~11 MB/phút)**, gồm video ~1,35 Mbps và âm thanh 128 kbps. Ước lượng: reel 30 giây ~6 MB, video 3 phút ~34 MB; cảnh tĩnh sẽ nhỏ hơn. **Giá trị cụ thể chỉnh một lần bằng vài clip thật của user rồi cố định trong code.** **Bước chỉnh (user đồng ý):** khi bắt đầu làm, user chọn 2–3 clip tiêu biểu trong `~/Videos` (một reel ngắn, một video ~3 phút, một clip nhiều chuyển động). Chỉ **đọc** các clip đó để nén thử; file kết quả ghi vào thư mục tạm của dự án, **không ghi vào `~/Videos`**. User xem và chốt chất lượng/dung lượng, rồi mới cố định thông số. Ngoài bước này, test không dùng file thật của user.
- Cạnh dài tối đa **1280** (720p; video dọc thành 720×1280). **Không bao giờ phóng to.** Tối đa **30 fps**, không tăng.
- 8-bit `yuv420p`. Video HDR/10-bit (ví dụ quay bằng iPhone) **chuyển về SDR** để không bị bạc màu.
- Âm thanh AAC 128 kbps. Nguồn đã là AAC ≤128 kbps thì copy nguyên.
- MP4 `+faststart`. **Xóa toàn bộ metadata** (GPS, tên máy, ngày giờ).
- Nếu file kết quả **không nhỏ hơn** file gốc thì bỏ kết quả, giữ file gốc và báo "Đã đủ nhẹ".
- Chưa kiểm tra: giới hạn dung lượng của Zalo và việc Zalo có tự nén lại khi gửi hay không. Không ảnh hưởng tới bản đầu.

### 8.3 Cắt/Crop (một cửa sổ cho cả cắt đoạn lẫn crop 9:16)
Thả vào ô này thì mở **cửa sổ chỉnh** (cửa sổ nổi thường, không phải layer-shell), gồm:
- **Khung xem video** ở trên, **thanh thời gian** ở dưới, nút phát/dừng.
- **Công tắc "Khung 9:16"** (mặc định **bật**, vì mục đích chính là Reels *(Claude chọn)*).
- **Danh sách đoạn**, không giới hạn số đoạn. Mỗi đoạn có **một màu riêng**, gồm:
  - một **khoảng thời gian** (kéo hai đầu trên thanh thời gian), và
  - khi "Khung 9:16" bật: **một khung 9:16 đứng yên** suốt đoạn, kéo trái/phải (và lên/xuống nếu nguồn không phải ảnh ngang), chiều cao bằng chiều cao video.
  - "＋ Thêm đoạn", xóa đoạn (chỉ xóa trong danh sách, không đụng file).
- **Công tắc "Nối thành 1 video"**: bật thì nối các đoạn theo **thứ tự thời gian** thành một file; tắt thì **mỗi đoạn một file**.
- Nút **Xuất** và **Hủy**. Esc = Hủy.

Ví dụ của user: video ngang 3 người nói chuyện. Tạo 3 đoạn, mỗi đoạn khung 9:16 đặt vào một người với khoảng thời gian riêng, rồi nối thành một video dọc hoặc xuất thành 3 reel.

**Cách xuất:**
- Có crop 9:16: dùng **đúng thiết lập "Nén để gửi"** (§8.2), kể cả quy tắc **không bao giờ phóng to**. Kích thước ra là kích thước khung crop gốc, thu nhỏ nếu vượt 720×1280. Ví dụ: nguồn 1080p ngang → khung ~608×1080 → xuất **608×1080**; nguồn 4K → 720×1280; nguồn 720p → 404×720 *(Claude chọn: không phóng to, vì Reels/TikTok tự co giãn và phóng to chỉ làm file nặng hơn mà không nét hơn)*. Chiều rộng/cao làm tròn về số chẵn.
- Chỉ cắt đoạn (Khung 9:16 tắt): **mã hóa lại bằng `h264_vaapi`, giữ nguyên độ phân giải**, chất lượng cao, để điểm cắt chính xác tới từng khung hình *(Claude chọn: chọn chính xác thay vì cắt nhanh không mã hóa, vì cắt nhanh lệch 1–2 giây; với VAAPI, clip ngắn vẫn chỉ mất vài giây)*.
- Toàn bộ các đoạn xử lý trong **một lần chạy ffmpeg** (`trim`/`crop`/`concat` trong filter graph), không mã hóa nhiều lần.

**Metadata** *(Claude chọn)*: mọi kết quả của Cắt/Crop đều **xóa toàn bộ metadata**, giống Nén, vì kết quả thường được gửi Zalo/đăng mạng.

### 8.4 Logo (xóa watermark, tầng nhanh)
- Dùng **chung thành phần cửa sổ** với Cắt/Crop nhưng ở chế độ "khung tự do": kéo **một hoặc nhiều hình chữ nhật** quanh logo trên khung hình *(nhiều hình là Claude chọn)*. Áp dụng cho **toàn bộ video**. Có nút xem trước kết quả trên khung hình hiện tại.
- Xử lý bằng ffmpeg `delogo` (mỗi hình chữ nhật một bộ lọc). Mã hóa lại bằng `h264_vaapi`, giữ nguyên độ phân giải, chất lượng cao, giữ âm thanh.
- Chấp nhận là vẫn còn vết nhòe; logo di chuyển thì không xử lý được. Tầng AI để sau.
- Xóa toàn bộ metadata, giống Nén *(Claude chọn)*. Chỉ thao tác MP4 là giữ metadata.

## 9. An toàn file

- **Không bao giờ** xóa, di chuyển hay ghi đè file gốc. Drop target phải nhận hành động MOVE (Nautilus chỉ đề nghị MOVE). Spike đã thả 4 lần kiểu MOVE và **file gốc vẫn còn nguyên**. Code chỉ đọc đường dẫn, không bao giờ thao tác lên file nguồn.
- **Không bao giờ ghi đè file đã có.** Nếu trùng tên thì đánh số: `tên (2).mp4`, `tên (3).mp4`…
- Ghi ra **file tạm** trong cùng thư mục (`.tên.dropwheel-part.mp4`). Khi thành công thì đổi tên thành file chính thức. Khi lỗi hoặc bị hủy thì xóa file tạm. File tạm này do chính dropwheel tạo trong lúc đang chạy, xóa nó không động tới dữ liệu của user.
- Thư mục nguồn không ghi được: báo lỗi, không ghi chỗ khác *(Claude chọn)*.

## 10. Tên file kết quả *(Claude chọn)*

Kết quả nằm cạnh file gốc:

| Thao tác | Tên |
|---|---|
| MP4 | `tên.mp4` |
| Nén | `tên - nén.mp4` |
| Cắt (nối / riêng) | `tên - cắt.mp4` / `tên - đoạn 1.mp4`, `tên - đoạn 2.mp4`… |
| Crop 9:16 (nối / riêng) | `tên - 9x16.mp4` / `tên - 9x16 đoạn 1.mp4`… |
| Logo | `tên - xóa logo.mp4` |

File kết quả có thể kéo tiếp vào vòng tròn để xử lý thêm, giống trong video.

## 11. Thông báo tiến độ *(Claude chọn chi tiết)*

- Một thẻ nhỏ ở **góc dưới bên phải** màn hình (layer-shell, cùng phong cách với vòng tròn), **trượt lên** khi bắt đầu. Thẻ gồm tên việc ("Đang nén…"), tên file, thanh tiến độ và nút ✕ để hủy.
- Khi xong: hiện "Xong · 34 MB", bấm vào thì mở thư mục chứa file trong Nautilus; tự ẩn sau ~4 giây.
- Khi lỗi: thẻ màu đỏ kèm câu ngắn dễ hiểu. Chi tiết đầy đủ ghi vào `~/.local/state/dropwheel/dropwheel.log`.
- Nhiều việc trong hàng đợi thì thẻ hiện "1/3". Nút ✕ **chỉ hủy việc đang chạy**, việc kế tiếp chạy tiếp; khi hàng đợi còn từ 2 việc trở lên thì thẻ có thêm nút "Hủy hết" *(Claude chọn)*.

## 12. Hiệu năng

- Bấm phím đến khi vòng tròn hiện: **< 50 ms** (dùng socket Hyprland, cửa sổ đã dựng sẵn).
- MP4 khi chỉ cần đổi vỏ: khoảng 1 giây.
- Nén reel 30 giây 1080p trên VAAPI: mục tiêu **vài giây**. Cần đo thật và ghi lại.
- Khi rảnh, tiến trình nền gần như không tốn CPU.

## 13. Rủi ro đã biết, cần kiểm tra sớm

1. **Alt+Q khi đang kéo:** spike mới thử F8 và Shift. Phải kiểm tra rằng Alt+Q cũng chạy khi Nautilus đang kéo file, và giữ phím Super không làm hủy thao tác kéo. Nếu không chạy được thì **báo user**, không tự đổi phím.
2. **Driver VAAPI** (`intel-media-driver`) có thể chưa cài. Nếu thiếu: thứ nhất, cách lùi về `libx264` vẫn phải chạy được; thứ hai, **hỏi user trước khi cài gói**.
3. Chất lượng của `delogo` có thể không đạt kỳ vọng. Chấp nhận được trong bản đầu.

## 14. Kiểm thử *(Claude chọn hướng)*

- Unit test cho phần tạo lệnh ffmpeg (đầu vào: thông tin `ffprobe` + thao tác → lệnh) và phần đặt tên tránh trùng.
- Test tích hợp với video tự sinh bằng `ffmpeg -f lavfi` (ngang, dọc, HDR 10-bit, không có âm thanh, nhiều luồng âm thanh): kiểm tra kết quả bằng `ffprobe` (độ phân giải, fps, codec, metadata đã xóa, dung lượng nằm dưới trần).
- Kéo thả và chuyển động: kiểm tra bằng tay theo danh sách các bước.
- Không bao giờ dùng file thật của user trong test.

## 15. Phần để người làm quyết

- Cấu trúc thư mục code, cách đóng gói, cách viết filter graph.
- Xem trước bằng GStreamer hay bằng ảnh khung hình, miễn là đáp ứng yêu cầu ở §6.
- Thông số cụ thể của QVBR/VBR (sau khi đo với clip thật, xem §8.2), cách tonemap HDR.
- Biểu tượng, đường cong chuyển động và màu cụ thể, bám theo mockup.
