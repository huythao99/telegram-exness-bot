import os
import sys
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

API_ID_RAW = os.getenv("TG_API_ID", "").strip()
API_HASH = os.getenv("TG_API_HASH", "").strip()
SESSION_NAME = os.getenv("TG_SESSION_NAME", "exness_copier_session").strip()


async def list_all_dialogs(client: TelegramClient):
    print("\n" + "=" * 70)
    print(f"{'CHAT ID':<20} | {'LOẠI':<12} | {'TÊN GROUP / CHANNEL'}")
    print("=" * 70)
    async for dialog in client.iter_dialogs():
        if dialog.is_channel or dialog.is_group:
            kind = "Channel" if dialog.is_channel else "Group"
            print(f"{dialog.id:<20} | {kind:<12} | {dialog.name}")
    print("=" * 70)
    print("💡 Copy cột CHAT ID (bao gồm cả dấu trừ `-`) dán vào TARGET_CHAT_IDS trong file .env\n")


def main():
    if not API_ID_RAW or not API_HASH or API_HASH == "your_api_hash_here":
        print("❌ Vui lòng tạo file .env và điền TG_API_ID, TG_API_HASH trước khi chạy.")
        sys.exit(1)

    client = TelegramClient(SESSION_NAME, int(API_ID_RAW), API_HASH)
    with client:
        client.loop.run_until_complete(list_all_dialogs(client))


if __name__ == "__main__":
    main()
