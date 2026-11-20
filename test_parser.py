from signal_parser import SignalParser


def run_tests():
    parser = SignalParser(
        lot_per_order=0.01,
        fixed_sl_distance=10.0,
        fixed_tp_distance=10.0,
        partial_profit_pips=1,
        partial_close_ratio=0.5,
    )

    samples = [
        """Sell vàng 3776-3778
Sl 3788
Tp 100 150pip""",
        """Buy vàng 3776-3778
Sl 3788
Tp 100 150pip""",
        """Buy vàng 3780""",
        """Vàng +40pip💰💰""",
    ]

    for idx, sample in enumerate(samples, 1):
        print(f"--- Mẫu #{idx} ---")
        print(sample)
        res = parser.parse_message(sample)
        print("-> Kết quả parse:")
        print(f"   Loại lệnh       : {res['type']}")
        if res["type"] == "OPEN":
            assert len(res["orders"]) == 2
            print(f"   Mốc dời SL (+40p): {res['be_sl_price']}")
            for i, o in enumerate(res["orders"], 1):
                print(f"   Lệnh #{i}         : {o}")
        print()


if __name__ == "__main__":
    run_tests()
