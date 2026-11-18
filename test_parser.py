from signal_parser import SignalParser


def run_tests():
    parser = SignalParser(
        grid_count=10,
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
        """Vàng +40pip💰💰""",
    ]

    for idx, sample in enumerate(samples, 1):
        print(f"--- Mẫu #{idx} ---")
        print(sample)
        res = parser.parse_message(sample)
        print("-> Kết quả parse:")
        print(f"   Loại lệnh       : {res['type']}")
        if res["type"] == "OPEN":
            print(f"   Mốc dời SL (+40p): {res['be_sl_price']}")
            print(f"   Lệnh đầu #1     : {res['orders'][0]}")
            print(f"   Lệnh cuối #10   : {res['orders'][-1]}")
        print(f"   MT5 Command     : {res['mt5_command']}\n")


if __name__ == "__main__":
    run_tests()
