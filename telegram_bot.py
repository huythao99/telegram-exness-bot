import os
import sys

from dotenv import load_dotenv
from telethon import TelegramClient, events

from exness_client import ExnessClient
from signal_parser import SignalParser

load_dotenv()

# ---- Telegram ----
API_ID_RAW = os.getenv("TG_API_ID", "").strip()
API_HASH = os.getenv("TG_API_HASH", "").strip()
SESSION_NAME = os.getenv("TG_SESSION_NAME", "exness_copier_session").strip()
TARGET_CHAT_IDS_RAW = os.getenv("TARGET_CHAT_IDS", "").strip()

# ---- Exness Trader API ----
EXN_API_KEY = os.getenv("EXN_API_KEY", "").strip()
EXN_PRIVATE_KEY = os.getenv("EXN_PRIVATE_KEY", "").strip()
EXN_PRIVATE_KEY_PATH = os.getenv("EXN_PRIVATE_KEY_PATH", "").strip()
EXN_ACCOUNT_ID = os.getenv("EXN_ACCOUNT_ID", "").strip()
EXN_DISCOVERY_BASE_URL = os.getenv("EXN_DISCOVERY_BASE_URL", "").strip()
EXN_API_BASE_URL = os.getenv("EXN_API_BASE_URL", "").strip()  # để trống -> tự tìm Access Point
DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() in ("1", "true", "yes", "on")

# ---- Giao dịch ----
SYMBOL = os.getenv("SYMBOL", "XAUUSDm").strip()
ORDER_TAG = os.getenv("ORDER_TAG", "TGBOT").strip()
LOT_PER_ORDER = float(os.getenv("LOT_PER_ORDER", "0.01"))
FIXED_SL_PRICE_DISTANCE = float(os.getenv("FIXED_SL_PRICE_DISTANCE", "10.0"))
FIXED_TP_PRICE_DISTANCE = float(os.getenv("FIXED_TP_PRICE_DISTANCE", "10.0"))
MARKET_TOLERANCE = float(os.getenv("MARKET_TOLERANCE", "0.30"))
SLIPPAGE_POINTS = int(os.getenv("SLIPPAGE_POINTS", "50"))
CANCEL_PENDING_ON_BE = os.getenv("CANCEL_PENDING_ON_BE", "true").strip().lower() in ("1", "true", "yes", "on")

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


def read_private_key() -> str:
    if EXN_PRIVATE_KEY_PATH:
        with open(os.path.expanduser(EXN_PRIVATE_KEY_PATH), "r", encoding="utf-8") as f:
            return f.read()
    return EXN_PRIVATE_KEY


async def open_signal(exn: ExnessClient, result: dict, sig_id: str):
    """Đặt 2 lệnh tại 2 điểm giá của tín hiệu."""
    side = result["side"]
    try:
        bid, ask = await exn.quote(SYMBOL)
        print(f"   Giá hiện tại {SYMBOL}: bid={bid} ask={ask}")
    except Exception as e:  # noqa: BLE001
        bid = ask = None
        print(f"   ⚠️ Không lấy được giá hiện tại ({e}) -> đặt tất cả là lệnh chờ Limit.")

    for i, o in enumerate(result["orders"], 1):
        entry, sl, tp, lot = o["entry"], o["sl"], o["tp"], o["lot"]
        comment = f"{ORDER_TAG}_{i}"
        idem = f"{sig_id}-o{i}"
        try:
            if side == "SELL":
                if bid is not None and bid >= entry - MARKET_TOLERANCE:
                    msl, mtp = round(bid + FIXED_SL_PRICE_DISTANCE, 2), round(bid - FIXED_TP_PRICE_DISTANCE, 2)
                    print(f"   #{i} SELL MARKET {lot} @~{bid} SL={msl} TP={mtp}")
                    await exn.open_market(SYMBOL, side, lot, msl, mtp, comment, idem)
                else:
                    kind = "limit" if bid is None or entry > bid else "stop"
                    print(f"   #{i} SELL {kind.upper()} {lot} @ {entry} SL={sl} TP={tp}")
                    await exn.place_pending(SYMBOL, side, kind, lot, entry, sl, tp, comment, idem)
            else:  # BUY
                if ask is not None and ask <= entry + MARKET_TOLERANCE:
                    msl, mtp = round(ask - FIXED_SL_PRICE_DISTANCE, 2), round(ask + FIXED_TP_PRICE_DISTANCE, 2)
                    print(f"   #{i} BUY MARKET {lot} @~{ask} SL={msl} TP={mtp}")
                    await exn.open_market(SYMBOL, side, lot, msl, mtp, comment, idem)
                else:
                    kind = "limit" if ask is None or entry < ask else "stop"
                    print(f"   #{i} BUY {kind.upper()} {lot} @ {entry} SL={sl} TP={tp}")
                    await exn.place_pending(SYMBOL, side, kind, lot, entry, sl, tp, comment, idem)
        except Exception as e:  # noqa: BLE001
            print(f"   ❌ Lỗi đặt lệnh #{i}: {e}")
    print(f"✅ Đã gửi {len(result['orders'])} lệnh {side} lên Exness.")


async def partial_close_and_be(exn: ExnessClient, ratio: float, be_price: float, sig_id: str):
    """Hủy lệnh chờ chưa khớp, chốt `ratio` số lệnh đang mở, dời SL phần còn lại về be_price."""
    positions, orders = await exn.bot_items(SYMBOL, ORDER_TAG)

    if CANCEL_PENDING_ON_BE:
        for o in orders:
            try:
                await exn.cancel_order(o["id"], f"{sig_id}-cancel-{o['id']}")
                print(f"   🗑️ Đã hủy lệnh chờ #{o['id']}")
            except Exception as e:  # noqa: BLE001
                print(f"   ❌ Lỗi hủy lệnh chờ #{o['id']}: {e}")

    if not positions:
        print("ℹ️ Không có lệnh nào đang mở để chốt.")
        return

    num_to_close = max(1, int(len(positions) * ratio + 0.5))
    for i, p in enumerate(positions):
        try:
            if i < num_to_close:
                await exn.close_position(p["id"], f"{sig_id}-close-{p['id']}")
                print(f"   💰 Đã đóng lệnh #{p['id']}")
            elif be_price > 0:
                await exn.modify_sl(p["id"], SYMBOL, be_price, p["tp"], f"{sig_id}-sl-{p['id']}")
                print(f"   🛡️ Đã dời SL lệnh #{p['id']} về {be_price}")
        except Exception as e:  # noqa: BLE001
            print(f"   ❌ Lỗi xử lý lệnh #{p['id']}: {e}")


def main():
    if not API_ID_RAW or not API_HASH or API_HASH == "your_api_hash_here":
        print("❌ Lỗi: Vui lòng tạo file .env (copy từ .env.example) và điền TG_API_ID, TG_API_HASH.")
        sys.exit(1)

    target_chats = parse_chat_ids(TARGET_CHAT_IDS_RAW)
    if not target_chats:
        print("❌ Lỗi: Vui lòng cấu hình TARGET_CHAT_IDS trong file .env (chạy `python3 list_chats.py` để lấy ID).")
        sys.exit(1)

    if not (EXN_API_KEY and (EXN_PRIVATE_KEY or EXN_PRIVATE_KEY_PATH) and EXN_ACCOUNT_ID
            and (EXN_DISCOVERY_BASE_URL or EXN_API_BASE_URL)):
        print("❌ Lỗi: Thiếu cấu hình Exness API (EXN_API_KEY, EXN_PRIVATE_KEY/EXN_PRIVATE_KEY_PATH, "
              "EXN_ACCOUNT_ID, EXN_DISCOVERY_BASE_URL) trong file .env.")
        sys.exit(1)

    parser = SignalParser(
        lot_per_order=LOT_PER_ORDER,
        fixed_sl_distance=FIXED_SL_PRICE_DISTANCE,
        fixed_tp_distance=FIXED_TP_PRICE_DISTANCE,
        partial_profit_pips=PARTIAL_PROFIT_PIPS,
        partial_close_ratio=PARTIAL_CLOSE_RATIO,
    )

    exn = ExnessClient(
        api_key=EXN_API_KEY,
        private_key_text=read_private_key(),
        account_id=EXN_ACCOUNT_ID,
        gateway_url=EXN_DISCOVERY_BASE_URL,
        access_point=EXN_API_BASE_URL,
        dry_run=DRY_RUN,
        deviation_points=SLIPPAGE_POINTS,
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

        sig_id = f"tg{abs(int(event.chat_id or 0))}-{event.id}"

        if result["type"] == "OPEN":
            state["partial_closed_for_current_signal"] = False
            state["current_be_sl_price"] = result["be_sl_price"]
            pts = " & ".join(f"{o['entry']}" for o in result["orders"])
            print(
                f"✅ Phát hiện lệnh {result['side']} Vàng -> 2 lệnh tại {pts}, "
                f"SL: {result['sl_distance']} giá, TP: {result['tp_distance']} giá, "
                f"Mốc dời SL khi báo lãi: {result['be_sl_price']}"
            )
            await open_signal(exn, result, sig_id)

        elif result["type"] == "PARTIAL_BE":
            if state["partial_closed_for_current_signal"]:
                print("ℹ️ Kèo hiện tại đã chốt 50% & dời SL trước đó. Bỏ qua.")
                return
            state["partial_closed_for_current_signal"] = True
            be_price = state["current_be_sl_price"]
            print(
                f"💰 Đạt +{result['pips']} pip -> "
                f"Chốt {int(result['ratio'] * 100)}% số lệnh & dời SL lệnh còn lại về {be_price}!"
            )
            await partial_close_and_be(exn, result["ratio"], be_price, sig_id)

    print("🤖 Đang khởi động Telegram -> Exness API Bot...")
    if DRY_RUN:
        print("🧪 DRY_RUN=true: chỉ in lệnh ra màn hình, KHÔNG gửi lệnh thật. Đặt DRY_RUN=false để chạy thật.")
    client.start()
    client.loop.run_until_complete(exn.connect())
    print(f"✅ Đang lắng nghe tin nhắn từ các kênh: {target_chats}")
    try:
        client.run_until_disconnected()
    finally:
        client.loop.run_until_complete(exn.close())


if __name__ == "__main__":
    main()
