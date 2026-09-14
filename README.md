# Elyriax API

Backend API đa nhiệm hiệu năng cao cho hệ sinh thái Elyriax, được chuyển đổi hoàn chỉnh từ Node.js Express sang **Python FastAPI (Python 3.11/3.12+)** với kiến trúc bất đồng bộ (async/await), hỗ trợ đầy đủ WebSocket/Socket.IO, bảo mật AES-256-CBC, và xử lý tác vụ nền.

---

## 🌟 Tính năng chính

1. **Hệ thống Vietsub Studio**:
   - Trích xuất âm thanh, bóc băng tự động (Transcription với Whisper / Gemini).
   - Dịch phụ đề văn hóa đa ngôn ngữ (Translation pipeline).
   - Render video phụ đề cứng (Hardsub rendering với FFmpeg).
   - Tải video đa nền tảng (Downloader với yt-dlp).

2. **Cửa hàng & Đơn hàng (Shop & E-commerce)**:
   - Quản lý danh mục sản phẩm, biến thể, tồn kho real-time.
   - Giỏ hàng (Cart) & Danh sách yêu thích (Wishlist).
   - Đặt hàng với cơ chế khóa hàng ACID (`SELECT ... FOR UPDATE`), trừ số dư ví tự động khi thanh toán.
   - Tự động giao mã sản phẩm / tài khoản sau khi hoàn tất thanh toán.

3. **Ví & Cổng thanh toán (Wallet & Payment)**:
   - Hệ thống số dư ví người dùng với mã giao dịch tự sinh chuẩn hóa.
   - Tích hợp SePay Webhook tự động cộng tiền ngay khi nhận thông báo chuyển khoản ngân hàng.
   - Tạo mã VietQR động theo đơn nạp.

4. **Xác thực & Bảo mật (Auth & Security)**:
   - Đăng nhập / Liên kết tài khoản qua Discord OAuth và Google OAuth.
   - Quản lý phiên làm việc (Session SHA256) lưu trữ trong cơ sở dữ liệu.
   - Quản lý API Key (`sk_syr_...`) cho các ứng dụng tích hợp bên ngoài.
   - Mã hóa cookie Genshin với thuật toán AES-256-CBC tương thích 100% với phiên bản Node.js cũ (không mất dữ liệu).

5. **Tự động hóa Genshin Impact (Genshin Automation)**:
   - Tự động điểm danh hàng ngày HoYoLAB / Genshin qua cron scheduler.
   - Nhập giftcode tự động, tra cứu danh sách code khả dụng.
   - Theo dõi Banner gacha, Daily note (nhựa, nhiệm vụ, boss), nhân vật và chỉ số tài khoản.
   - Thông báo kết quả điểm danh qua email (Resend API).

6. **Dịch vụ Cào dữ liệu & Proxy (Media & Crawler)**:
   - Proxy hình ảnh bypass CDN Truyện tranh (`/v1/truyen`).
   - Cào dữ liệu chi tiết anime / hentai (`/v1/crawl/hentai`, `/v1/hentai`).
   - Tra cứu lịch cúp điện EVN Miền Nam theo Mã khách hàng / Đơn vị (`/v1/evn`).
   - Pipeline dịch nghĩa ngôn ngữ văn hóa 2 bước qua Groq LLM (`/v1/translate`).

7. **Giám sát hệ thống Realtime (System Monitoring)**:
   - Socket.IO phát sóng trực tiếp chỉ số CPU, RAM, Disk, Network và biểu đồ lịch sử mỗi 2 giây (`system_realtime_update`).
   - Endpoint REST `/v1/host/system` đo độ trễ và thông số máy chủ.

8. **Rút gọn link & Lưu trữ file (Shortlinks & Storage)**:
   - Rút gọn link chuyển tiếp thiết bị Netflix (`/v1/go`, `/n/{device}/{id}`).
   - Upload file, tải file qua mã ngắn (`/d/{id}`).
   - Tạo tự động cấu trúc Minecraft (`/v1/mc/auto-build`).

---

## 🚀 Hướng dẫn triển khai trên Ubuntu VPS

### 1. Cài đặt các gói hệ thống cần thiết

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git ffmpeg
```

### 2. Clone Repository & Thiết lập Virtualenv

```bash
git clone https://github.com/Saiky988/Elyriax-api.git
cd Elyriax-api

python3 -m venv .venv
source .venv/bin/activate
```

### 3. Cài đặt thư viện Python

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Cấu hình Biến môi trường (`.env`)

Sao chép file mẫu và điền các thông tin kết nối:

```bash
cp .env.example .env
nano .env
```

> **LƯU Ý QUAN TRỌNG:**
> - Tuyệt đối không xóa hoặc thay đổi `GENSHIN_COOKIE_SECRET` nếu đang dùng cơ sở dữ liệu có sẵn cookie đã mã hóa từ trước.
> - Đảm bảo cấu hình MySQL chính xác để hệ thống tạo pool kết nối async.

### 5. Kiểm tra chạy thử nghiệm

```bash
uvicorn main:app --host 0.0.0.0 --port 25243
```

Kiểm tra trạng thái server:
```bash
curl http://127.0.0.1:25243/v1/host/system
```

---

## ⚙️ Thiết lập chạy nền với Systemd Service (Khuyên dùng trên Production)

Tạo file service:

```bash
sudo nano /etc/systemd/system/elyriax.service
```

Nội dung file:

```ini
[Unit]
Description=Elyriax FastAPI Service
After=network.target mysql.service

[Service]
User=root
WorkingDirectory=/root/Elyriax-api
Environment="PATH=/root/Elyriax-api/.venv/bin"
ExecStart=/root/Elyriax-api/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 25243 --workers 2

Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Kích hoạt và khởi chạy service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable elyriax
sudo systemctl start elyriax
sudo systemctl status elyriax
```

Xem log theo thời gian thực:

```bash
sudo journalctl -u elyriax -f
```

---

## 🔒 Quy tắc bảo mật

- File `.env` chứa các API Key, secret keys và thông tin cơ sở dữ liệu đã được đưa vào `.gitignore`.
- Tuyệt đối không commit file `.env`, file `.sql` dump hoặc credentials lên GitHub.
