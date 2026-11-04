from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RiskLimits:
    risk_per_trade_pct: float
    daily_loss_limit_pct: float
    max_trades_per_day: int
    max_concurrent_positions_per_symbol: int


@dataclass
class RiskState:
    day: str = ""
    trades_today: int = 0
    realized_pnl_today: float = 0.0


@dataclass
class RiskManager:
    limits: RiskLimits
    state: RiskState = field(default_factory=RiskState)

    def reset_if_new_day(self, now: datetime) -> None:
        day = now.strftime("%Y-%m-%d")
        if day != self.state.day:
            self.state.day = day
            self.state.trades_today = 0
            self.state.realized_pnl_today = 0.0

    def record_trade(self, pnl: float) -> None:
        self.state.trades_today += 1
        self.state.realized_pnl_today += pnl

    def can_trade(self, balance: float) -> tuple[bool, str]:
        if not math.isfinite(balance) or balance <= 0:
            return False, "invalid_account_balance"
        if self.state.trades_today >= self.limits.max_trades_per_day:
            return False, "max_trades_per_day"
        daily_loss_limit = -balance * (self.limits.daily_loss_limit_pct / 100)
        if self.state.realized_pnl_today <= daily_loss_limit:
            return False, "daily_loss_limit"
        return True, "ok"

    def position_size_lots(
        self,
        balance: float,
        sl_distance: float,
        point: float,
        tick_value: float,
        volume_step: float,
        volume_min: float,
        volume_max: float,
        tick_size: float | None = None,
    ) -> float:
        """Floor to a broker-valid size; never increase risk to meet minimum lots.

        MT5's trade_tick_value applies to trade_tick_size, not necessarily point.
        A broker-specific order_calc_profit check is still needed before live use.
        """
        tick = point if tick_size is None else tick_size
        values = (
            balance, self.limits.risk_per_trade_pct, sl_distance, tick,
            tick_value, volume_step, volume_min, volume_max,
        )
        if any(not math.isfinite(value) for value in values):
            return 0.0
        if (
            balance <= 0 or self.limits.risk_per_trade_pct <= 0
            or sl_distance <= 0 or tick <= 0 or tick_value <= 0
            or volume_step <= 0 or volume_min <= 0 or volume_max < volume_min
        ):
            return 0.0

        risk_amount = balance * (self.limits.risk_per_trade_pct / 100)
        risk_per_lot = (sl_distance / tick) * tick_value
        raw_lots = risk_amount / risk_per_lot
        if raw_lots < volume_min:
            return 0.0  # A minimum-lot order would exceed the risk budget.

        capped = min(raw_lots, volume_max)
        steps = max(0, math.floor((capped - volume_min) / volume_step + 1e-10))
        lots = round(volume_min + steps * volume_step, 8)
        # Floating-point rounding must never push the risk over budget.
        while lots >= volume_min and lots * risk_per_lot > risk_amount * (1 + 1e-10):
            lots = round(lots - volume_step, 8)
        return lots if volume_min <= lots <= volume_max else 0.0
