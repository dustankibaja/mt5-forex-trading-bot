from __future__ import annotations

from pathlib import Path

import MetaTrader5 as mt5
from typing import Tuple

from src.utils.logging import get_logger


logger = get_logger(__name__)


def kill_switch_active(path: str) -> bool:
    return Path(path).exists()


def is_symbol_tradable(symbol_info) -> bool:
    return bool(symbol_info and symbol_info.visible and symbol_info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL)


def spread_too_high(tick, max_spread_points: int, point: float) -> bool:
    if tick is None:
        return True
    spread = (tick.ask - tick.bid) / point
    return spread > max_spread_points


def stops_level_ok(symbol_info, sl: float, tp: float, price: float) -> Tuple[bool, float]:
    if symbol_info is None:
        return False, 0.0
    stops_level = symbol_info.trade_stops_level * symbol_info.point
    min_distance = stops_level * 1.2
    if sl is not None and abs(price - sl) < min_distance:
        return False, min_distance
    if tp is not None and abs(price - tp) < min_distance:
        return False, min_distance
    return True, min_distance
