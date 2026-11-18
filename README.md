# Telegram -> Exness MT5 Grid Copier (macOS)

Bot tự động đọc tín hiệu Vàng (`XAUUSD`) từ Group/Channel Telegram và đặt lệnh vào tài khoản **Exness MT5** trên máy Mac.

## Quy tắc giao dịch của Bot
1. **Rải 10 lệnh tự động theo vùng giá (SL 10 giá, TP 10 giá cho tất cả các lệnh):**
   - Nhận tin nhắn dạng:
     ```text
     Sell vàng 3776-3778
     Sl 3788
     Tp 100 150pip
     ```
   - Tự động chia đều **10 lệnh** (mỗi lệnh `0.01` lot) từ `3776.00` đến `3778.00`.
   - **SL cố định = 10 giá (`100 pips`)** và **TP cố định = 10 giá (`100 pips`)** tính từ mức giá vào của từng lệnh (bỏ qua SL/TP ghi trong tin nhắn):
     - VD với lệnh **SELL**:
       - Lệnh #1 tại `3776.00` $\rightarrow$ `SL = 3786.00`, `TP = 3766.00`
       - Lệnh #10 tại `3778.00` $\rightarrow$ `SL = 3788.00`, `TP = 3768.00`
     - VD với lệnh **BUY**:
       - Lệnh #1 tại `3776.00` $\rightarrow$ `SL = 3766.00`, `TP = 3786.00`
       - Lệnh #10 tại `3778.00` $\rightarrow$ `SL = 3768.00`, `TP = 3788.00`
2. **Khi có tin báo lãi `Vàng +(x)pip` (Chốt 50% số lệnh + Dời SL về mốc đầu vùng):**
   - Nhận tin nhắn dạng: `Vàng +40pip💰💰` (hoặc từ khóa `chốt nửa`, `chốt 1/2`, `chốt 50%`).
   - Tự động hủy các lệnh chờ Limit chưa khớp, **đóng 50% số lệnh đang mở** (VD: 10 lệnh $\rightarrow$ đóng 5 lệnh).
   - **50% số lệnh còn lại:** Tự động **dời SL của tất cả các lệnh còn lại về cùng 1 mốc**:
     - Nếu là lệnh **BUY `3776-3778`** $\rightarrow$ Dời SL tất cả về **`3778.00`**
     - Nếu là lệnh **SELL `3776-3778`** $\rightarrow$ Dời SL tất cả về **`3776.00`**
     - Sau đó gồng tới khi chạm **TP 10 giá (100 pips)**.

---

## Cấu trúc thư mục
- `telegram_bot.py`: Script chính lắng nghe Telegram và gửi lệnh sang MT5.
- `signal_parser.py`: Bộ phân tích cú pháp tin nhắn, chia lưới 10 lệnh với SL 10 giá & TP 10 giá.
- `list_chats.py`: Công cụ lấy `CHAT_ID` của các Group/Channel trong tài khoản Telegram.
- `test_parser.py`: Script kiểm tra nhanh bộ lọc tin nhắn.
- `mql5/TelegramGridCopier.mq5`: Expert Advisor (EA) chạy trên phần mềm MT5 Mac.
