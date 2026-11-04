from __future__ import annotations


import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT_DIR))


import argparse
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5
import pandas as pd
from dotenv import load_dotenv

from src.config import load_config
from src.execution.mt5_adapter import MT5Adapter
from src.execution.order_builder import build_market_order_request, build_sl_tp_request
from src.execution.order_manager import OrderManager
from src.execution.risk_manager import RiskLimits, RiskManager
from src.execution.safeguards import kill_switch_active, is_symbol_tradable, spread_too_high, stops_level_ok
from src.monitoring.alerts import load_telegram_alert
from src.monitoring.journal import TradeJournal
from src.strategy.atr_breakout import compute_signal
from src.utils.logging import configure_logging, get_logger
from src.utils.timeutils import is_in_session, parse_sessions


logger = get_logger(__name__)

# Must match the magic used in order_builder.build_market_order_request.
BOT_MAGIC = 123456


def refresh_account_risk(now: datetime, risk_manager: RiskManager) -> bool:
    """Rebuild daily controls from broker state, including after bot restarts.

    Loss tracking is deliberately account-wide: unrelated manual trades can also
    trigger a stop. Deposits/withdrawals are excluded. Fail closed on API errors.
    """
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(day_start, now)
    positions = mt5.positions_get()
    if deals is None or positions is None:
        logger.error("Cannot verify broker deal history or positions; trading disabled")
        return False

    market_types = {mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL}
    trade_deals = [deal for deal in deals if deal.type in market_types]
    opening_entries = {mt5.DEAL_ENTRY_IN, mt5.DEAL_ENTRY_INOUT}
    opened_positions = {
        deal.position_id
        for deal in trade_deals
        if deal.magic == BOT_MAGIC and deal.entry in opening_entries
    }
    realized = sum(
        float(getattr(deal, "profit", 0) or 0)
        + float(getattr(deal, "commission", 0) or 0)
        + float(getattr(deal, "swap", 0) or 0)
        + float(getattr(deal, "fee", 0) or 0)
        for deal in trade_deals
    )
    floating = sum(
        float(getattr(position, "profit", 0) or 0)
        + float(getattr(position, "swap", 0) or 0)
        for position in positions
    )
    risk_manager.state.trades_today = max(
        risk_manager.state.trades_today, len(opened_positions)
    )
    risk_manager.state.realized_pnl_today = realized + floating
    return True


TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


def fetch_rates(symbol: str, timeframe: int, bars: int) -> pd.DataFrame:
    # Position zero is the still-forming candle; only use closed candles.
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 1, bars)
    if rates is None:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")
    df = df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close", "tick_volume": "volume"})
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configure_logging()
    load_dotenv()
    config = load_config(args.config)

    adapter = MT5Adapter(
        retry_attempts=config.execution.retry_attempts,
        retry_backoff_seconds=config.execution.retry_backoff_seconds,
    )
    if not adapter.initialize():
        return

    alert = load_telegram_alert()
    journal = TradeJournal(path="trades/trade_journal.csv")
    risk_manager = RiskManager(
        limits=RiskLimits(
            risk_per_trade_pct=config.risk.risk_per_trade_pct,
            daily_loss_limit_pct=config.risk.daily_loss_limit_pct,
            max_trades_per_day=config.risk.max_trades_per_day,
            max_concurrent_positions_per_symbol=config.risk.max_concurrent_positions_per_symbol,
        )
    )

    tz, windows = parse_sessions(config.sessions.timezone, config.sessions.windows)
    timeframe = TIMEFRAME_MAP[config.timeframe]

    last_bar_time = {}

    try:
        while True:
            now = datetime.now(timezone.utc)
            risk_manager.reset_if_new_day(now)

            if kill_switch_active(config.execution.kill_switch_file):
                logger.warning("Kill switch active. No new trades.")
                time.sleep(5)
                continue

            for symbol in config.symbols:
                info = adapter.get_symbol_info(symbol)
                if not is_symbol_tradable(info):
                    logger.warning("Symbol not tradable", {"symbol": symbol})
                    continue

                tick = adapter.get_tick(symbol)
                if tick is None:
                    continue

                if spread_too_high(tick, config.execution.max_spread_points, info.point):
                    logger.warning("Spread too high", {"symbol": symbol})
                    continue

                if not is_in_session(now, tz, windows):
                    continue

                rates = fetch_rates(symbol, timeframe, max(config.strategy.breakout_N, config.strategy.atr_period, config.strategy.ema_period) + 5)
                if rates.empty:
                    continue

                bar_time = rates.index[-1]
                if last_bar_time.get(symbol) == bar_time:
                    continue
                last_bar_time[symbol] = bar_time

                signal = compute_signal(
                    rates,
                    breakout_N=config.strategy.breakout_N,
                    atr_period=config.strategy.atr_period,
                    atr_min=config.strategy.atr_min,
                    ema_period=config.strategy.ema_period,
                    use_trend_filter=config.strategy.use_trend_filter,
                )

                if signal.direction == 0:
                    continue

                account = mt5.account_info()
                if account is None or not refresh_account_risk(now, risk_manager):
                    logger.error("Account state unavailable; trading disabled")
                    continue

                positions = mt5.positions_get(symbol=symbol)
                if positions is None:
                    logger.error("Cannot verify existing positions; trading disabled", {"symbol": symbol})
                    continue
                if len(positions) >= config.risk.max_concurrent_positions_per_symbol:
                    logger.info("Maximum symbol positions reached", {"symbol": symbol})
                    continue

                can_trade, reason = risk_manager.can_trade(balance=account.balance)
                if not can_trade:
                    logger.warning("Risk limits block trade", {"reason": reason})
                    continue

                sl_distance = config.strategy.sl_atr_mult * signal.atr_value
                if sl_distance <= 0:
                    continue

                entry = tick.ask if signal.direction == 1 else tick.bid
                sl = entry - sl_distance if signal.direction == 1 else entry + sl_distance
                tp = entry + config.strategy.rr_ratio * sl_distance if signal.direction == 1 else entry - config.strategy.rr_ratio * sl_distance

                ok, min_dist = stops_level_ok(info, sl, tp, entry)
                if not ok:
                    logger.warning("Stops too close", {"symbol": symbol, "min_distance": min_dist})
                    continue

                volume = risk_manager.position_size_lots(
                    balance=account.balance,
                    sl_distance=sl_distance,
                    point=info.point,
                    tick_value=info.trade_tick_value,
                    volume_step=info.volume_step,
                    volume_min=info.volume_min,
                    volume_max=info.volume_max,
                    tick_size=info.trade_tick_size,
                )
                if volume <= 0:
                    continue

                action = mt5.ORDER_TYPE_BUY if signal.direction == 1 else mt5.ORDER_TYPE_SELL
                # Check actual broker-currency loss at the stop, not just tick-value math.
                stop_pnl = mt5.order_calc_profit(action, symbol, volume, entry, sl)
                risk_budget = account.balance * config.risk.risk_per_trade_pct / 100
                if stop_pnl is None or stop_pnl >= 0 or abs(stop_pnl) > risk_budget * (1 + 1e-8):
                    logger.error("Broker stop-loss risk exceeds budget; skipped", {"symbol": symbol})
                    continue

                order_req = build_market_order_request(
                    symbol=symbol,
                    action=action,
                    volume=volume,
                    price=entry,
                    deviation=config.execution.deviation,
                    sl=sl,
                    tp=tp,
                    symbol_info=info,
                )

                if args.dry_run or config.execution.dry_run:
                    logger.info("DRY_RUN order", {"symbol": symbol, "direction": signal.direction, "volume": volume, "entry": entry, "sl": sl, "tp": tp})
                    continue

                manager = OrderManager(adapter)
                response = manager.send_order_with_fillings(order_req, info)
                result = response.result

                if result is None:
                    continue

                # Never open without server-side SL/TP. No unsafe fallback on invalid stops.
                if result.retcode == mt5.TRADE_RETCODE_INVALID_STOPS:
                    logger.error("Broker rejected protective stops; order not retried", {"symbol": symbol})
                    continue

                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    risk_manager.record_trade(0.0)
                    journal.append(
                        {
                            "time": datetime.now(timezone.utc).isoformat(),
                            "symbol": symbol,
                            "direction": "BUY" if signal.direction == 1 else "SELL",
                            "volume": volume,
                            "price": entry,
                            "sl": sl,
                            "tp": tp,
                            "ticket": result.order,
                            "comment": result.comment,
                        }
                    )
                    alert.send(f"Trade executed {symbol} {signal.direction} @ {entry}")

            time.sleep(10)
    finally:
        adapter.shutdown()


if __name__ == "__main__":
    main()
