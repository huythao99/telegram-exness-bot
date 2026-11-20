import re
from typing import Any, Dict, List, Optional


class SignalParser:
    """
    Bộ phân tích tin nhắn tín hiệu Vàng (XAUUSD) từ Telegram Group/Channel.
    Quy ước:
      - Đặt 2 lệnh tại đúng 2 điểm giá trong tin nhắn (VD: "Sell vàng 3776-3778"
        -> 1 lệnh tại 3776, 1 lệnh tại 3778). Nếu tin chỉ có 1 giá -> 2 lệnh cùng giá đó.
      - SL cố định và TP cố định (mặc định 10 giá) tính từ giá Entry của từng lệnh.
      - Khi có tin báo "+40pip":
          + Chốt 50% số lệnh đang mở (2 lệnh -> chốt 1)
          + Dời SL lệnh còn lại về mép có lợi nhất của vùng Entry:
              * BUY  3776-3778 -> dời SL về 3778.00 (entry_max)
              * SELL 3776-3778 -> dời SL về 3776.00 (entry_min)
    """

    def __init__(
        self,
        lot_per_order: float = 0.01,
        fixed_sl_distance: float = 10.0,
        fixed_tp_distance: float = 10.0,
        partial_profit_pips: int = 1,
        partial_close_ratio: float = 0.5,
    ):
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

        be_sl_price = round(entry_max if side == "BUY" else entry_min, 2)

        # 2 lệnh tại đúng 2 điểm giá trong tin nhắn
        levels = [round(entry_min, 2), round(entry_max, 2)]

        orders: List[Dict[str, float]] = []
        for lv in levels:
            if side == "SELL":
                sl_price = round(lv + self.fixed_sl_distance, 2)
                tp_price = round(lv - self.fixed_tp_distance, 2)
            else:  # BUY
                sl_price = round(lv - self.fixed_sl_distance, 2)
                tp_price = round(lv + self.fixed_tp_distance, 2)
            orders.append({"entry": lv, "sl": sl_price, "tp": tp_price, "lot": self.lot_per_order})

        return {
            "type": "OPEN",
            "side": side,
            "entry_min": entry_min,
            "entry_max": entry_max,
            "be_sl_price": be_sl_price,
            "sl_distance": self.fixed_sl_distance,
            "tp_distance": self.fixed_tp_distance,
            "orders": orders,
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
                return {"type": "PARTIAL_BE", "pips": pips, "ratio": self.partial_close_ratio}

        if re.search(r"\b(chốt\s*(một\s*)?nửa|chốt\s*1/2|chốt\s*50%)", cleaned, re.IGNORECASE):
            return {
                "type": "PARTIAL_BE",
                "pips": self.partial_profit_pips,
                "ratio": self.partial_close_ratio,
            }

        return None
