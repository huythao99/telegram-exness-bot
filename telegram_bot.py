import os
import sys
from dotenv import load_dotenv
from telethon import TelegramClient, events
from signal_parser import SignalParser

load_dotenv()

# Đọc cấu hình từ file .env
API_ID_RAW = os.getenv("TG_API_ID", "").strip()
API_HASH = os.getenv("TG_API_HASH", "").strip()
SESSION_NAME = os.getenv("TG_SESSION_NAME", "exness_copier_session").strip()
TARGET_CHAT_IDS_RAW = os.getenv("TARGET_CHAT_IDS", "").strip()
MT5_FILES_DIR = os.getenv("MT5_FILES_DIR", "").strip()

GRID_COUNT = int(os.getenv("GRID_COUNT", "10"))
LOT_PER_ORDER = float(os.getenv("LOT_PER_ORDER", "0.01"))
FIXED_SL_PRICE_DISTANCE = float(os.getenv("FIXED_SL_PRICE_DISTANCE", "10.0"))
FIXED_TP_PRICE_DISTANCE = float(os.getenv("FIXED_TP_PRICE_DISTANCE", "10.0"))

PARTIAL_PROFIT_PIPS = int(os.getenv("PARTIAL_PROFIT_PIPS", "1"))
PARTIAL_CLOSE_RATIO = float(os.getenv("PARTIAL_CLOSE_RATIO", "0.5"))


def parse_chat_ids(raw: str):
    chat_ids = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            chat_ids.append(int(item))
        except ValueError:
            chat_ids.append(item)
    return chat_ids


def send_command_to_mt5(command_str: str):
    """
    Ghi lệnh sang thư mục MQL5/Files theo cơ chế Atomic Write (ghi vào file .tmp rồi đổi tên)
    để EA trên MT5 không bao giờ đọc phải file đang ghi dở.
    """
    if not MT5_FILES_DIR:
        print("⚠️ Chưa cấu hình MT5_FILES_DIR trong file .env! Chỉ in lệnh ra màn hình:")
        print(f"   -> {command_str}")
        return

    os.makedirs(MT5_FILES_DIR, exist_ok=True)
    tmp_path = os.path.join(MT5_FILES_DIR, "tg_command.tmp")
    final_path = os.path.join(MT5_FILES_DIR, "tg_command.txt")

    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(command_str)
    os.replace(tmp_path, final_path)
    print(f"🚀 Đã gửi lệnh sang MT5: {command_str}")


def main():
    if not API_ID_RAW or not API_HASH or API_HASH == "your_api_hash_here":
        print("❌ Lỗi: Vui lòng tạo file .env (copy từ .env.example) và điền TG_API_ID, TG_API_HASH.")
        sys.exit(1)

    target_chats = parse_chat_ids(TARGET_CHAT_IDS_RAW)
    if not target_chats:
        print("❌ Lỗi: Vui lòng cấu hình TARGET_CHAT_IDS trong file .env (chạy `python3 list_chats.py` để lấy ID).")
        sys.exit(1)

    parser = SignalParser(
        grid_count=GRID_COUNT,
        lot_per_order=LOT_PER_ORDER,
        fixed_sl_distance=FIXED_SL_PRICE_DISTANCE,
        fixed_tp_distance=FIXED_TP_PRICE_DISTANCE,
        partial_profit_pips=PARTIAL_PROFIT_PIPS,
        partial_close_ratio=PARTIAL_CLOSE_RATIO,
    )

    state = {
        "partial_closed_for_current_signal": False,
        "current_be_sl_price": 0.0,
    }

    client = TelegramClient(SESSION_NAME, int(API_ID_RAW), API_HASH)

    @client.on(events.NewMessage(chats=target_chats))
    async def on_new_message(event):
        text = event.raw_text or ""
        print(f"\n📩 [Chat {event.chat_id}] Tin nhắn mới:\n{text}")

        result = parser.parse_message(text)
        if not result:
            print("ℹ️ Tin nhắn không phải lệnh giao dịch hoặc báo chốt.")
            return

        if result["type"] == "OPEN":
            state["partial_closed_for_current_signal"] = False
            state["current_be_sl_price"] = result["be_sl_price"]
            print(
                f"✅ Phát hiện lệnh {result['side']} Vàng ({result['entry_min']} - {result['entry_max']}), "
                f"SL: {result['sl_distance']} giá, TP: {result['tp_distance']} giá, "
                f"Mốc dời SL khi báo lãi: {result['be_sl_price']}"
            )
            send_command_to_mt5(result["mt5_command"])

        elif result["type"] == "PARTIAL_BE":
            if state["partial_closed_for_current_signal"]:
                print("ℹ️ Kèo hiện tại đã chốt 50% & dời SL trước đó. Bỏ qua.")
                return
            state["partial_closed_for_current_signal"] = True
            be_price = state["current_be_sl_price"]
            cmd = f"{result['mt5_command']}|{be_price:.2f}"
            print(
                f"💰 Đạt +{result['pips']} pip -> "
                f"Chốt {int(result['ratio']*100)}% số lệnh & dời SL các lệnh còn lại về {be_price}!"
            )
            send_command_to_mt5(cmd)

    print("🤖 Đang khởi động Telegram -> Exness MT5 Bot...")
    client.start()
    print(f"✅ Đang lắng nghe tin nhắn từ các kênh: {target_chats}")
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
