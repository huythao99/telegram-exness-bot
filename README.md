# Telegram -> Exness Trader API Copier (macOS)

Bot tự động đọc tín hiệu Vàng (`XAUUSD`) từ Group/Channel Telegram và đặt lệnh **trực tiếp qua Exness Trader API** (REST, ký Ed25519).

## Quy tắc giao dịch của Bot
1. **Đặt 2 lệnh tại 2 điểm giá trong tin nhắn:**
   - Nhận tin nhắn dạng:
     ```text
     Sell vàng 3776-3778
     Sl 3788
     Tp 100 150pip
     ```
   - Bot đặt **1 lệnh tại `3776.00`** và **1 lệnh tại `3778.00`** (mỗi lệnh `LOT_PER_ORDER`, mặc định `0.01`). Nếu tin chỉ có 1 giá thì đặt 2 lệnh cùng giá đó.
   - Nếu giá hiện tại đã chạm/vượt điểm vào (trong `MARKET_TOLERANCE`) thì vào Market ngay, ngược lại đặt lệnh chờ Limit.
   - **SL cố định = 10 giá** và **TP cố định = 10 giá** tính từ giá vào của từng lệnh (bỏ qua SL/TP ghi trong tin nhắn):
     - **SELL**: `3776 → SL 3786 / TP 3766`, `3778 → SL 3788 / TP 3768`
     - **BUY**:  `3776 → SL 3766 / TP 3786`, `3778 → SL 3768 / TP 3788`
2. **Khi có tin báo lãi `Vàng +(x)pip`** (hoặc `chốt nửa`, `chốt 1/2`, `chốt 50%`):
   - Hủy lệnh chờ chưa khớp, **đóng 50% số lệnh đang mở** (2 lệnh → đóng 1).
   - Lệnh còn lại được **dời SL** về: BUY `3776-3778` → `3778.00`, SELL `3776-3778` → `3776.00`.

## Cài đặt
```bash
pip3 install -r requirements.txt
cp .env.example .env     # điền thông tin Telegram + Exness API
python3 list_chats.py    # lấy CHAT_ID
python3 exness_probe.py  # kiểm tra kết nối Exness API (không đặt lệnh)
python3 telegram_bot.py  # chạy bot (mặc định DRY_RUN=true)
```

Khi đã thấy lệnh in ra đúng ở chế độ thử, đổi `DRY_RUN=false` trong `.env` để đặt lệnh thật.

## Đối chiếu tên trường API
Đường dẫn API và cách ký request theo tài liệu công khai của Exness. Một số tên trường JSON trong body lệnh (đánh dấu `VERIFY` trong `exness_client.py`, ví dụ `side`, `type`, `price`) cần đối chiếu với spec chính thức: <https://www.exness-api.com/openapi/trading.public.yaml>. Nếu khác, tạo file `exness_schema.json` cạnh code để ghi đè, ví dụ:
```json
{ "b_instrument": "symbol", "side_buy": "BUY", "side_sell": "SELL" }
```

## Cấu trúc thư mục
- `telegram_bot.py`: Script chính, lắng nghe Telegram và gọi Exness API.
- `exness_client.py`: Client Exness Trader API (ký request, đặt/đóng/hủy lệnh, dời SL).
- `exness_probe.py`: Kiểm tra kết nối và in dữ liệu thô từ tài khoản.
- `signal_parser.py`: Phân tích tin nhắn và tạo 2 lệnh tại 2 điểm giá.
- `list_chats.py`: Lấy `CHAT_ID` của các Group/Channel.
- `test_parser.py`: Kiểm tra nhanh bộ phân tích tin nhắn.
