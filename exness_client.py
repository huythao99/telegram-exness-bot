"""
Client tối giản cho Exness Trader API (REST, ký Ed25519 - sign version 1).
Tài liệu: https://www.exness-api.com

Luồng:
  1. Gọi Gateway `/v1/trading/access-point?account_id=...` để lấy Access Point của tài khoản.
  2. Mọi request theo tài khoản gửi tới Access Point, có header EXN-* đã ký.
  3. Lệnh ghi (đặt/đóng/sửa) trả về 202 + operation_id -> poll `/operations/{id}` lấy kết quả.

LƯU Ý: Đường dẫn (path) và cơ chế ký đã khớp tài liệu công khai. Một số TÊN TRƯỜNG JSON
trong body (đánh dấu VERIFY) cần đối chiếu với OpenAPI spec:
  https://www.exness-api.com/openapi/trading.public.yaml
Nếu khác, ghi đè trong file `exness_schema.json` (cùng thư mục) mà không cần sửa code.
Chạy `python3 exness_probe.py` để xem dữ liệu thô trả về từ tài khoản của bạn.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

EMPTY_BODY_HASH = "47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU"  # SHA-256 của body rỗng

SCHEMA: Dict[str, Any] = {
    # ---- Paths (theo tài liệu) ----
    "path_discovery": "/v1/trading/access-point",
    "path_account": "/v1/configuration/accounts/{acc}/account",
    "path_conditions": "/v1/configuration/accounts/{acc}/instruments/{instrument}/conditions",
    "path_candles": "/v1/market-data/accounts/{acc}/candles",
    "path_snapshot": "/v1/trading/accounts/{acc}/snapshot",
    "path_positions": "/v1/trading/accounts/{acc}/positions",        # POST = mở lệnh market
    "path_position": "/v1/trading/accounts/{acc}/positions/{pid}",   # DELETE = đóng lệnh
    "path_orders": "/v1/trading/accounts/{acc}/orders",              # POST = lệnh chờ / SLTP
    "path_order": "/v1/trading/accounts/{acc}/orders/{oid}",         # DELETE = hủy lệnh chờ
    "path_operation": "/v1/trading/accounts/{acc}/operations/{op}",

    # ---- Body đặt lệnh ----
    "b_instrument": "instrument",        # VERIFY (có thể là "symbol")
    "b_side": "side",                    # VERIFY
    "side_buy": "buy",                   # VERIFY
    "side_sell": "sell",                 # VERIFY
    "b_volume": "volume",
    "b_sl": "stop_loss_price",
    "b_tp": "take_profit_price",
    "b_comment": "comment",
    "b_deviation": "deviation",          # độ trượt giá tối đa (points)
    "b_order_type": "type",              # VERIFY
    "order_type_limit": "limit",         # VERIFY
    "order_type_stop": "stop",           # VERIFY
    "order_type_sltp": "sltp",           # VERIFY
    "b_price": "price",                  # VERIFY (giá đặt lệnh chờ)
    "b_position_id": "position_id",      # VERIFY

    # Cách dời SL cho position đang mở: "sltp_order" (POST /orders type=sltp) | "patch_position"
    "modify_strategy": "sltp_order",

    # ---- Query nến (để lấy giá bid/ask hiện tại) ----
    "q_instrument": "instrument",
    "q_timeframe": "timeframe",
    "q_price_type": "price_type",
    "candles_root": ["candles", "data", "items", "result"],
    "candle_close": ["close", "c"],
    "candle_time": ["time", "open_time", "t", "timestamp"],

    # ---- Đọc snapshot (thử lần lượt các tên) ----
    "snap_positions": ["positions", "open_positions"],
    "snap_orders": ["orders", "open_orders", "pending_orders"],
    "obj_id": ["id", "position_id", "order_id", "ticket"],
    "obj_instrument": ["instrument", "symbol"],
    "obj_side": ["side", "type", "direction"],
    "obj_volume": ["volume", "lots"],
    "obj_open_price": ["open_price", "price", "entry_price"],
    "obj_sl": ["stop_loss_price", "sl", "stop_loss"],
    "obj_tp": ["take_profit_price", "tp", "take_profit"],
    "obj_comment": ["comment", "client_comment"],
    "cond_digits": ["point_digits", "digits"],

    # ---- Operation ACK ----
    "op_id": ["operation_id", "id"],
    "op_status": ["status", "state"],
}

PENDING_STATES = {"", "pending", "in_progress", "processing", "accepted", "new", "queued"}
FAILED_STATES = {"rejected", "failed", "error", "cancelled", "canceled"}


def _load_schema() -> Dict[str, Any]:
    s = dict(SCHEMA)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exness_schema.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            s.update(json.load(f))
    return s


def pick(d: Any, names, default=None):
    if not isinstance(d, dict):
        return default
    for n in ([names] if isinstance(names, str) else names):
        if n in d and d[n] is not None:
            return d[n]
    return default


def find_list(d: Any, names) -> list:
    if isinstance(d, list):
        return d
    v = pick(d, names)
    if isinstance(v, list):
        return v
    if isinstance(d, dict):
        for sub in d.values():
            if isinstance(sub, dict):
                v = pick(sub, names)
                if isinstance(v, list):
                    return v
    return []


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def load_private_key(text: str) -> Ed25519PrivateKey:
    """Hỗ trợ key PEM (PKCS#8) hoặc chuỗi hex 128 ký tự do Exness tạo."""
    t = text.strip()
    if "BEGIN" in t:
        key = serialization.load_pem_private_key(t.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Private key không phải Ed25519")
        return key
    h = re.sub(r"\s+", "", t)
    if re.fullmatch(r"[0-9a-fA-F]{128}", h) or re.fullmatch(r"[0-9a-fA-F]{64}", h):
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(h)[:32])
    raise ValueError("Private key phải là PEM (PKCS#8) hoặc hex 128 ký tự của Exness")


def safe_idem(key: str) -> str:
    """Idempotency key: 5–128 ký tự trong tập A-Za-z0-9._-~"""
    key = re.sub(r"[^A-Za-z0-9._\-~]", "-", key)[:128]
    return key if len(key) >= 5 else (key + "-----")[:5]


class ExnessError(RuntimeError):
    def __init__(self, status: int, body: Any, path: str):
        txt = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        super().__init__(f"HTTP {status} {path}: {txt[:400]}")
        self.status, self.body, self.path = status, body, path


class ExnessClient:
    def __init__(
        self,
        api_key: str,
        private_key_text: str,
        account_id: str,
        gateway_url: str,
        access_point: str = "",
        dry_run: bool = True,
        deviation_points: int = 50,
    ):
        self.api_key = api_key.strip()
        self.key = load_private_key(private_key_text)
        self.account_id = str(account_id).strip()
        self.gateway = gateway_url.strip().rstrip("/")
        self.access_point = access_point.strip().rstrip("/")
        self.dry_run = dry_run
        self.deviation_points = deviation_points
        self.S = _load_schema()
        self._http = httpx.AsyncClient(timeout=20)
        self._digits: Dict[str, int] = {}

    # ------------------------------------------------------------ signing / http
    def _headers(self, method: str, path_q: str, body: Optional[bytes], idem: str) -> Dict[str, str]:
        ts = int(time.time() * 1000)
        payload = {
            "api_key": self.api_key,
            "idempotency_key": idem,
            "timestamp": ts,
            "sign_version": 1,
            "method": method,
            "path": path_q,
            "body_hash": b64url(hashlib.sha256(body).digest()) if body else EMPTY_BODY_HASH,
        }
        data = json.dumps(payload, separators=(",", ":")).encode()
        return {
            "EXN-API-KEY": self.api_key,
            "EXN-IDEMPOTENCY-KEY": idem,
            "EXN-TIMESTAMP": str(ts),
            "EXN-SIGN-VERSION": "1",
            "EXN-DATA": b64url(data),
            "EXN-SIGN": b64url(self.key.sign(data)),
        }

    async def _req(self, method: str, path: str, query: Optional[dict] = None,
                   body: Optional[dict] = None, idem: str = "", base: str = "") -> Any:
        method = method.upper()
        base = base or self.access_point
        path_q = path + ("?" + urlencode(query) if query else "")
        raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        if method != "GET":
            idem = safe_idem(idem or f"tg-{int(time.time() * 1000)}")
            if self.dry_run:
                print(f"   [DRY_RUN] {method} {path_q} {raw.decode() if raw else ''}")
                return {"dry_run": True}
        else:
            idem = ""
        if not base:
            raise ExnessError(0, "Chưa có Access Point - hãy gọi connect()", path_q)
        headers = self._headers(method, path_q, raw, idem)
        if raw is not None:
            headers["Content-Type"] = "application/json"
        r = await self._http.request(method, base + path_q, headers=headers, content=raw)
        try:
            data = r.json() if r.content else {}
        except ValueError:
            data = r.text
        if r.status_code >= 400:
            raise ExnessError(r.status_code, data, path_q)
        return data

    def _p(self, key: str, **kw) -> str:
        return self.S[key].format(acc=self.account_id, **kw)

    async def _wait_op(self, ack: Any, timeout: float = 10.0) -> Any:
        """Poll trạng thái operation cho tới khi xong."""
        if isinstance(ack, dict) and ack.get("dry_run"):
            return ack
        op = pick(ack, self.S["op_id"])
        if not op:
            return ack
        deadline = time.monotonic() + timeout
        last: Any = ack
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            try:
                last = await self._req("GET", self._p("path_operation", op=op))
            except ExnessError as e:
                if e.status == 404:
                    continue
                raise
            st = str(pick(last, self.S["op_status"], "")).lower()
            if st in FAILED_STATES:
                raise ExnessError(0, last, f"operation {op} {st}")
            if st not in PENDING_STATES:
                return last
        print(f"   ⚠️ Hết thời gian chờ operation {op}, trạng thái cuối: {last}")
        return last

    # ------------------------------------------------------------------- read
    async def connect(self) -> None:
        if not self.access_point:
            data = await self._req("GET", self.S["path_discovery"], base=self.gateway,
                                   query={"account_id": self.account_id})
            self.access_point = str(pick(data, ["access_point"], "")).rstrip("/")
            if not self.access_point:
                raise ExnessError(0, data, "discovery không trả về access_point")
        await self._req("GET", self._p("path_account"))
        print(f"✅ Đã kết nối Exness API: tài khoản {self.account_id} qua {self.access_point}")

    async def close(self) -> None:
        await self._http.aclose()

    async def account(self) -> Any:
        return await self._req("GET", self._p("path_account"))

    async def conditions(self, symbol: str) -> Any:
        return await self._req("GET", self._p("path_conditions", instrument=symbol))

    async def digits(self, symbol: str) -> int:
        if symbol not in self._digits:
            try:
                c = await self.conditions(symbol)
                self._digits[symbol] = int(pick(c, self.S["cond_digits"], 2))
            except Exception as e:  # noqa: BLE001
                print(f"   ⚠️ Không đọc được số chữ số giá của {symbol} ({e}), dùng 2.")
                self._digits[symbol] = 2
        return self._digits[symbol]

    async def snapshot(self) -> Any:
        return await self._req("GET", self._p("path_snapshot"))

    async def _last_close(self, symbol: str, price_type: str) -> Optional[float]:
        S = self.S
        q = {S["q_instrument"]: symbol, S["q_timeframe"]: "M1",
             "from": int(time.time() * 1000), "count": -1, S["q_price_type"]: price_type}
        data = await self._req("GET", self._p("path_candles"), query=q)
        rows = find_list(data, S["candles_root"])
        if not rows:
            return None
        c = rows[-1]
        if isinstance(c, list):
            return float(c[4]) if len(c) >= 5 else None
        v = pick(c, S["candle_close"])
        return float(v) if v is not None else None

    async def quote(self, symbol: str) -> Tuple[float, float]:
        """Giá bid/ask gần nhất (lấy từ nến M1 vì REST không có endpoint tick)."""
        bid = await self._last_close(symbol, "bid")
        ask = await self._last_close(symbol, "ask")
        if not bid:
            raise ExnessError(0, "không có dữ liệu nến", f"quote {symbol}")
        return bid, max(ask or bid, bid)

    def _norm(self, rows: list) -> List[Dict[str, Any]]:
        S = self.S
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.append({
                "id": str(pick(r, S["obj_id"], "")),
                "instrument": str(pick(r, S["obj_instrument"], "")),
                "side": str(pick(r, S["obj_side"], "")).lower(),
                "volume": float(pick(r, S["obj_volume"], 0) or 0),
                "open_price": float(pick(r, S["obj_open_price"], 0) or 0),
                "sl": pick(r, S["obj_sl"]),
                "tp": pick(r, S["obj_tp"]),
                "comment": str(pick(r, S["obj_comment"], "") or ""),
                "raw": r,
            })
        return out

    async def bot_items(self, symbol: str, tag: str) -> Tuple[List[dict], List[dict]]:
        """(positions, pending_orders) của bot: cùng mã và comment chứa `tag`."""
        snap = await self.snapshot()
        mine = lambda x: x["instrument"] == symbol and tag in x["comment"]
        positions = [p for p in self._norm(find_list(snap, self.S["snap_positions"])) if mine(p)]
        orders = [o for o in self._norm(find_list(snap, self.S["snap_orders"])) if mine(o)]
        # Bỏ các lệnh SLTP gắn vào position, chỉ giữ lệnh chờ thật
        orders = [o for o in orders if self.S["order_type_sltp"] not in o["side"]]
        return positions, orders

    # ------------------------------------------------------------------ write
    def _side(self, side: str) -> str:
        return self.S["side_buy"] if side.upper() == "BUY" else self.S["side_sell"]

    async def open_market(self, symbol: str, side: str, volume: float, sl: float, tp: float,
                          comment: str, idem: str) -> Any:
        S, d = self.S, await self.digits(symbol)
        body = {
            S["b_instrument"]: symbol,
            S["b_side"]: self._side(side),
            S["b_volume"]: f"{volume:.2f}",
            S["b_sl"]: f"{sl:.{d}f}",
            S["b_tp"]: f"{tp:.{d}f}",
            S["b_comment"]: comment[:31],
        }
        if self.deviation_points:
            body[S["b_deviation"]] = int(self.deviation_points)
        ack = await self._req("POST", self._p("path_positions"), body=body, idem=idem)
        return await self._wait_op(ack)

    async def place_pending(self, symbol: str, side: str, kind: str, volume: float, price: float,
                            sl: float, tp: float, comment: str, idem: str) -> Any:
        """kind: 'limit' hoặc 'stop'"""
        S, d = self.S, await self.digits(symbol)
        body = {
            S["b_instrument"]: symbol,
            S["b_side"]: self._side(side),
            S["b_order_type"]: S["order_type_limit"] if kind == "limit" else S["order_type_stop"],
            S["b_volume"]: f"{volume:.2f}",
            S["b_price"]: f"{price:.{d}f}",
            S["b_sl"]: f"{sl:.{d}f}",
            S["b_tp"]: f"{tp:.{d}f}",
            S["b_comment"]: comment[:31],
        }
        ack = await self._req("POST", self._p("path_orders"), body=body, idem=idem)
        return await self._wait_op(ack)

    async def cancel_order(self, order_id: str, idem: str) -> Any:
        ack = await self._req("DELETE", self._p("path_order", oid=order_id), idem=idem)
        return await self._wait_op(ack)

    async def close_position(self, position_id: str, idem: str) -> Any:
        ack = await self._req("DELETE", self._p("path_position", pid=position_id), idem=idem)
        return await self._wait_op(ack)

    async def modify_sl(self, position_id: str, symbol: str, sl: float, tp: Optional[float],
                        idem: str) -> Any:
        S, d = self.S, await self.digits(symbol)
        fields = {S["b_sl"]: f"{sl:.{d}f}"}
        if tp not in (None, "", 0, "0"):
            fields[S["b_tp"]] = f"{float(tp):.{d}f}"
        if S["modify_strategy"] == "patch_position":
            ack = await self._req("PATCH", self._p("path_position", pid=position_id),
                                  body=fields, idem=idem)
        else:
            body = {S["b_order_type"]: S["order_type_sltp"], S["b_position_id"]: position_id,
                    S["b_instrument"]: symbol, **fields}
            ack = await self._req("POST", self._p("path_orders"), body=body, idem=idem)
        return await self._wait_op(ack)
