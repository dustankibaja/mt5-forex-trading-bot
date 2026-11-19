from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import MetaTrader5 as mt5

from src.utils.logging import get_logger


logger = get_logger(__name__)


@dataclass
class OrderRequest:
    request: Dict[str, Any]
    filling_mode: int


def _constant(name: str) -> int:
    # MQL5 Symbol Properties bit masks omitted by some Python package versions.
    documented_flags = {"SYMBOL_ORDER_MARKET": 1, "SYMBOL_ORDER_LIMIT": 2,
                        "SYMBOL_ORDER_STOP": 4, "SYMBOL_ORDER_STOP_LIMIT": 8,
                        "SYMBOL_FILLING_FOK": 1, "SYMBOL_FILLING_IOC": 2}
    value = getattr(mt5, name, documented_flags.get(name))
    if type(value) is not int:
        raise ValueError(f"MetaTrader5 constant {name} is unavailable")
    return value


def allowed_fillings(symbol_info, *, operation: str = "market") -> List[int]:
    """Return policies valid for the execution and operation types."""
    if operation not in {"market", "pending"}:
        raise ValueError("Unsupported trade operation type")
    execution = symbol_info.trade_exemode
    if execution not in (mt5.SYMBOL_TRADE_EXECUTION_REQUEST, mt5.SYMBOL_TRADE_EXECUTION_INSTANT,
                         mt5.SYMBOL_TRADE_EXECUTION_MARKET, mt5.SYMBOL_TRADE_EXECUTION_EXCHANGE):
        return []
    order_mode = getattr(symbol_info, "order_mode", None)
    if operation == "pending":
        pending_flags = (_constant("SYMBOL_ORDER_LIMIT") |
                         _constant("SYMBOL_ORDER_STOP") |
                         _constant("SYMBOL_ORDER_STOP_LIMIT"))
        if type(order_mode) is not int or not order_mode & pending_flags:
            return []
        return [_constant("ORDER_FILLING_RETURN")]
    if type(order_mode) is not int or not order_mode & _constant("SYMBOL_ORDER_MARKET"):
        return []
    if execution in (
        _constant("SYMBOL_TRADE_EXECUTION_INSTANT"),
        _constant("SYMBOL_TRADE_EXECUTION_REQUEST"),
    ):
        return [
            _constant("ORDER_FILLING_FOK"),
            _constant("ORDER_FILLING_IOC"),
            _constant("ORDER_FILLING_RETURN"),
        ]

    flags = symbol_info.filling_mode
    if type(flags) is not int:
        return []
    modes: List[int] = []
    if flags & _constant("SYMBOL_FILLING_FOK"):
        modes.append(_constant("ORDER_FILLING_FOK"))
    if flags & _constant("SYMBOL_FILLING_IOC"):
        modes.append(_constant("ORDER_FILLING_IOC"))
    if execution != _constant("SYMBOL_TRADE_EXECUTION_MARKET"):
        modes.append(_constant("ORDER_FILLING_RETURN"))
    return modes


def build_market_order_request(
    symbol: str,
    action: int,
    volume: float,
    price: float,
    deviation: int,
    sl: float | None,
    tp: float | None,
    symbol_info,
    magic: int = 123456,
    comment: str = "ATRBreakout",
) -> OrderRequest:
    fillings = allowed_fillings(symbol_info, operation="market")
    if not fillings:
        raise ValueError(f"No supported market-order filling policy for {symbol}")
    filling_mode = fillings[0]

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": action,
        "price": price,
        "deviation": deviation,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }

    if sl is not None:
        request["sl"] = sl
    if tp is not None:
        request["tp"] = tp

    logger.info("Built order request", {"request": request})
    return OrderRequest(request=request, filling_mode=filling_mode)


def build_sl_tp_request(position_ticket: int, symbol: str, sl: float, tp: float) -> Dict[str, Any]:
    return {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": position_ticket,
        "symbol": symbol,
        "sl": sl,
        "tp": tp,
    }
