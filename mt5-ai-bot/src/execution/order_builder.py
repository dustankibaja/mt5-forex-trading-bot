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


def allowed_fillings(symbol_info) -> List[int]:
    """Convert SYMBOL_FILLING_MODE flags into valid ORDER_FILLING_* policies.

    SYMBOL_FILLING_FOK/IOC use 1/2 as flags; ORDER_FILLING_FOK/IOC
    use 0/1 as enum values. They are not interchangeable.
    """
    flags = symbol_info.filling_mode
    execution = symbol_info.trade_exemode
    if execution in (
        mt5.SYMBOL_TRADE_EXECUTION_INSTANT,
        mt5.SYMBOL_TRADE_EXECUTION_REQUEST,
    ):
        return [
            mt5.ORDER_FILLING_FOK,
            mt5.ORDER_FILLING_IOC,
            mt5.ORDER_FILLING_RETURN,
        ]

    modes: List[int] = []
    if flags & 1:  # SYMBOL_FILLING_FOK flag
        modes.append(mt5.ORDER_FILLING_FOK)
    if flags & 2:  # SYMBOL_FILLING_IOC flag
        modes.append(mt5.ORDER_FILLING_IOC)
    if execution != mt5.SYMBOL_TRADE_EXECUTION_MARKET:
        modes.append(mt5.ORDER_FILLING_RETURN)
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
    fillings = allowed_fillings(symbol_info)
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
