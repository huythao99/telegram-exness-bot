import re
from typing import Any, Dict, List, Optional


class SignalParser:
    """
    Bộ phân tích tin nhắn tín hiệu Vàng (XAUUSD) từ Telegram Group/Channel.
    Quy ước:
      - Rải đều 10 lệnh (mỗi lệnh 0.01 lot) trong vùng Entry (VD: 3776 - 3778)
      - SL cố định 10 giá và TP cố định 10 giá cho tất cả các lệnh (tính từ giá Entry của từng lệnh)
      - Khi có tin báo "+40pip":
          + Chốt 50% số lệnh đang mở
          + Dời SL của 50% lệnh còn lại về mép có lợi nhất của vùng Entry:
              * Nếu BUY (3776-3778)  -> Dời SL tất cả về 3778.00 (entry_max)
              * Nếu SELL (3776-3778) -> Dời SL tất cả về 3776.00 (entry_min)
    """

    def __init__(
        self,
        grid_count: int = 10,
        lot_per_order: float = 0.01,
        fixed_sl_distance: float = 10.0,
        fixed_tp_distance: float = 10.0,
        partial_profit_pips: int = 1,
        partial_close_ratio: float = 0.5,
    ):
        self.grid_count = grid_count
        self.lot_per_order = lot_per_order
        self.fixed_sl_distance = fixed_sl_distance
        self.fixed_tp_distance = fixed_tp_distance
        self.partial_profit_pips = partial_profit_pips
        self.partial_close_ratio = partial_close_ratio

    def parse_message(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Thử phân tích tin nhắn theo thứ tự ưu tiên:
        1. Tin nhắn báo vào lệnh mới (BUY / SELL)
        2. Tin nhắn báo lãi (+40pip...) để chốt 50% & dời SL
        """
        if not text or not text.strip():
            return None

        entry_sig = self.parse_entry_signal(text)
        if entry_sig:
            return entry_sig

        profit_sig = self.parse_profit_update(text)
        if profit_sig:
            return profit_sig

        return None

    def parse_entry_signal(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Mẫu tin nhắn hỗ trợ:
            Sell vàng 3776-3778
            Sl 3788
            Tp 100 150pip
        """
        cleaned = text.strip()

        # 1. Tìm hướng lệnh (Buy/Sell) + tên tài sản + vùng giá Entry
        entry_pattern = re.compile(
            r"\b(buy|sell)\s+(?:vàng|vang|gold|xauusd|xau)\s*[:=@]?\s*"
            r"(\d{3,5}(?:\.\d+)?)(?:\s*[-_/~–—]\s*(\d{3,5}(?:\.\d+)?))?",
            re.IGNORECASE,
        )
        entry_match = entry_pattern.search(cleaned)
        if not entry_match:
            return None

        side = entry_match.group(1).upper()
        p1 = float(entry_match.group(2))
        p2 = float(entry_match.group(3)) if entry_match.group(3) else p1
        entry_min, entry_max = min(p1, p2), max(p1, p2)

        # Mốc giá dời SL khi đạt +40pip:
        # BUY  3776-3778 -> dời SL về 3778 (entry_max)
        # SELL 3776-3778 -> dời SL về 3776 (entry_min)
        be_sl_price = round(entry_max if side == "BUY" else entry_min, 2)

        # 2. Chia đều `grid_count` mức giá trong vùng [entry_min, entry_max]
        if self.grid_count > 1 and entry_max > entry_min:
            step = (entry_max - entry_min) / (self.grid_count - 1)
            levels = [round(entry_min + i * step, 2) for i in range(self.grid_count)]
        else:
            levels = [round(entry_min, 2)] * self.grid_count

        # 3. Tính SL (10 giá) và TP (10 giá) riêng cho từng mức lệnh
        orders: List[Dict[str, float]] = []
        grid_items_str: List[str] = []

        for lv in levels:
            if side == "SELL":
                sl_price = round(lv + self.fixed_sl_distance, 2)
                tp_price = round(lv - self.fixed_tp_distance, 2)
            else:  # BUY
                sl_price = round(lv - self.fixed_sl_distance, 2)
                tp_price = round(lv + self.fixed_tp_distance, 2)

            orders.append(
                {
                    "entry": lv,
                    "sl": sl_price,
                    "tp": tp_price,
                    "lot": self.lot_per_order,
                }
            )
            grid_items_str.append(f"{lv:.2f}:{sl_price:.2f}:{tp_price:.2f}")

        # Format gửi sang EA:
        # OPEN|<SIDE>|<LOT>|<SL_DIST>|<TP_DIST>|<BE_SL_PRICE>|<ENTRY:SL:TP,...>
        mt5_command = (
            f"OPEN|{side}|{self.lot_per_order:.2f}|"
            f"{self.fixed_sl_distance:.2f}|{self.fixed_tp_distance:.2f}|"
            f"{be_sl_price:.2f}|"
            + ",".join(grid_items_str)
        )

        return {
            "type": "OPEN",
            "side": side,
            "entry_min": entry_min,
            "entry_max": entry_max,
            "be_sl_price": be_sl_price,
            "sl_distance": self.fixed_sl_distance,
            "tp_distance": self.fixed_tp_distance,
            "orders": orders,
            "mt5_command": mt5_command,
        }

    def parse_profit_update(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Phân tích tin nhắn báo lãi (+40pip) để chốt 50% số lệnh & dời SL:
          VD: "Vàng +40pip💰💰"
        """
        cleaned = text.strip()

        profit_pattern = re.compile(
            r"(?:vàng|vang|gold|xauusd|xau)?[^\n\r]*?\+\s*(\d+)\s*pip",
            re.IGNORECASE,
        )
        match = profit_pattern.search(cleaned)
        if match:
            pips = int(match.group(1))
            if pips >= self.partial_profit_pips:
                return {
                    "type": "PARTIAL_BE",
                    "pips": pips,
                    "ratio": self.partial_close_ratio,
                    "mt5_command": f"PARTIAL_BE|{self.partial_close_ratio:.2f}",
                }

        if re.search(r"\b(chốt\s*(một\s*)?nửa|chốt\s*1/2|chốt\s*50%)", cleaned, re.IGNORECASE):
            return {
                "type": "PARTIAL_BE",
                "pips": self.partial_profit_pips,
                "ratio": self.partial_close_ratio,
                "mt5_command": f"PARTIAL_BE|{self.partial_close_ratio:.2f}",
            }

        return None
