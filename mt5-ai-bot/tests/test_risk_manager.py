from src.execution.risk_manager import RiskLimits, RiskManager


def make_manager(risk_pct=1.0):
    return RiskManager(
        limits=RiskLimits(
            risk_per_trade_pct=risk_pct,
            daily_loss_limit_pct=2.0,
            max_trades_per_day=3,
            max_concurrent_positions_per_symbol=1,
        )
    )


def size(rm, **changes):
    args = dict(
        balance=10000.0,
        sl_distance=0.0010,
        point=0.0001,
        tick_value=10.0,
        volume_step=0.01,
        volume_min=0.01,
        volume_max=1.0,
    )
    args.update(changes)
    return rm.position_size_lots(**args)


def test_position_size_stays_within_budget():
    lots = size(make_manager())
    assert 0 < lots <= 1.0


def test_does_not_force_minimum_lot_above_risk_budget():
    # Risk budget $1, but the minimum 0.01 lot loses $5 at the SL.
    assert size(make_manager(), balance=100.0, sl_distance=0.005) == 0.0


def test_lots_round_down_not_up():
    # Budget is $26, $10 loss per 0.01 lot -> 0.026 rounds DOWN to 0.02.
    assert size(make_manager(), balance=2600.0, sl_distance=0.01, tick_value=10.0) == 0.02


def test_tick_size_not_point_used_for_tick_value():
    assert size(
        make_manager(),
        balance=1000.0,
        sl_distance=0.5,
        point=0.01,
        tick_size=0.1,
        tick_value=1.0,
        volume_max=3.0,
    ) == 2.0


def test_invalid_lot_inputs_fail_closed():
    rm = make_manager()
    assert size(rm, volume_step=0) == 0.0
    assert size(rm, tick_value=0) == 0.0
    assert size(rm, balance=float("nan")) == 0.0


def test_daily_risk_and_trade_count():
    rm = make_manager()
    rm.reset_if_new_day(__import__("datetime").datetime(2026, 11, 4))
    rm.state.realized_pnl_today = -201.0
    assert rm.can_trade(10000.0) == (False, "daily_loss_limit")
    rm.state.realized_pnl_today = 0.0
    rm.state.trades_today = 3
    assert rm.can_trade(10000.0) == (False, "max_trades_per_day")
