"""
Kiểm tra kết nối Exness Trader API và in dữ liệu thô (không đặt lệnh).
Dùng để xác nhận key/account đúng và đối chiếu tên trường JSON trước khi chạy bot thật.

    python3 exness_probe.py
"""
import asyncio
import json

from telegram_bot import (EXN_ACCOUNT_ID, EXN_API_BASE_URL, EXN_API_KEY,
                          EXN_DISCOVERY_BASE_URL, ORDER_TAG, SYMBOL, read_private_key)
from exness_client import ExnessClient


def show(title, data):
    print(f"\n===== {title} =====")
    print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])


async def main():
    exn = ExnessClient(EXN_API_KEY, read_private_key(), EXN_ACCOUNT_ID,
                       EXN_DISCOVERY_BASE_URL, EXN_API_BASE_URL, dry_run=True)
    try:
        await exn.connect()
        show("ACCOUNT", await exn.account())
        show(f"CONDITIONS {SYMBOL}", await exn.conditions(SYMBOL))
        try:
            bid, ask = await exn.quote(SYMBOL)
            print(f"\n===== QUOTE {SYMBOL} =====\nbid={bid} ask={ask}")
        except Exception as e:  # noqa: BLE001
            print(f"\n⚠️ Không lấy được giá: {e}")
        show("SNAPSHOT", await exn.snapshot())
        pos, orders = await exn.bot_items(SYMBOL, ORDER_TAG)
        print(f"\nLệnh của bot ({ORDER_TAG}): {len(pos)} position, {len(orders)} lệnh chờ")
    finally:
        await exn.close()


if __name__ == "__main__":
    asyncio.run(main())
