# calendar-kindle

Website đơn giản lấy dữ liệu từ **Apple Calendar (iCloud)** và hiển thị trên **trình duyệt Kindle**.

- Render hoàn toàn phía server — **không cần JavaScript**, chạy tốt trên trình duyệt "Experimental" cũ của Kindle.
- Giao diện đen trắng, chữ to, độ tương phản cao cho màn hình e-ink.
- 4 chế độ xem: **Sắp tới** (N ngày tới), **Ngày**, **Tuần**, **Tháng**.
- Hỗ trợ sự kiện lặp lại, cả ngày, kéo dài nhiều ngày, qua đêm, múi giờ.
- Tự tải lại trang định kỳ (mặc định 5 phút), có cache để không gọi iCloud liên tục.
- Bảo vệ bằng `ACCESS_TOKEN` (tuỳ chọn).

## 1. Lấy dữ liệu từ Apple Calendar

Chọn **một** (hoặc cả hai) cách:

### Cách A — Link lịch công khai (đơn giản nhất)
1. iPhone/Mac: mở **Lịch** → bấm ⓘ cạnh tên lịch → bật **Lịch công khai** → **Chia sẻ liên kết** → sao chép.
   (Trên icloud.com/calendar: biểu tượng chia sẻ cạnh tên lịch → tick *Lịch công khai*.)
2. Đặt link (dạng `webcal://p..-caldav.icloud.com/published/2/...`) vào `ICS_URLS`. Nhiều lịch thì phân tách bằng dấu phẩy.

> Lưu ý: ai có link đều xem được lịch đó.

### Cách B — iCloud CalDAV (giữ lịch riêng tư)
1. Vào https://account.apple.com → **Đăng nhập và Bảo mật** → **Mật khẩu dành riêng cho ứng dụng** → tạo mật khẩu mới.
2. Điền `ICLOUD_USERNAME` (Apple ID/email) và `ICLOUD_APP_PASSWORD` (dạng `xxxx-xxxx-xxxx-xxxx`).
3. Tuỳ chọn: `ICLOUD_CALENDARS=Công việc,Gia đình` để chỉ lấy một số lịch.

## 2. Chạy

```bash
cp .env.example .env      # rồi sửa .env
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py   # http://localhost:8000
```

Chạy thử không cần tài khoản Apple: `DEMO=1 .venv/bin/python app.py`

Chạy production bằng Docker:

```bash
docker compose up -d --build
```

## 3. Mở trên Kindle

1. Máy chạy server và Kindle phải cùng mạng Wi-Fi (hoặc deploy lên server/VPS có Internet).
2. Kindle: **⋮ Menu → Trình duyệt thử nghiệm (Experimental Browser)**.
3. Nhập `http://<IP-máy-chủ>:8000` (thêm `/?key=<ACCESS_TOKEN>` nếu có đặt token) → bookmark lại.
4. Mẹo: Chọn chế độ xem "Tháng" khi xoay ngang; trang tự tải lại theo `REFRESH_SECONDS`.

## Cấu hình (biến môi trường / `.env`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ICS_URLS` | | Link `.ics`/`webcal://`, phân tách bằng dấu phẩy |
| `ICLOUD_USERNAME` / `ICLOUD_APP_PASSWORD` | | Đăng nhập iCloud CalDAV |
| `ICLOUD_CALENDARS` | tất cả | Tên lịch cần lấy |
| `TIMEZONE` | `Asia/Ho_Chi_Minh` | Múi giờ hiển thị |
| `LANGUAGE` | `vi` | `vi` hoặc `en` |
| `AGENDA_DAYS` | `7` | Số ngày ở trang "Sắp tới" |
| `REFRESH_SECONDS` | `300` | Tự tải lại trang (0 = tắt) |
| `CACHE_MINUTES` | `10` | Thời gian cache dữ liệu iCloud |
| `MONTH_MAX_EVENTS` | `3` | Số sự kiện tối đa mỗi ô ở chế độ Tháng |
| `ACCESS_TOKEN` | | Nếu đặt, cần `?key=...` để truy cập |
| `PORT` | `8000` | Cổng web |
| `DEMO` | `0` | `1` = dùng dữ liệu mẫu `tests/sample.ics` |

## Đường dẫn

- `/` — Sắp tới (`?date=YYYY-MM-DD` để đổi ngày bắt đầu)
- `/day?date=YYYY-MM-DD`
- `/week?date=YYYY-MM-DD`
- `/month?date=YYYY-MM-DD`
- `/healthz` — kiểm tra trạng thái

## Kiểm thử

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```
