import MetaTrader5 as mt5
import pytest

from src.execution.order_builder import allowed_fillings, build_market_order_request
from src.execution.safeguards import is_symbol_tradable


class MockSymbol:
    def __init__(
        self,
        flags=1,
        execution=mt5.SYMBOL_TRADE_EXECUTION_MARKET,
        trade_mode=mt5.SYMBOL_TRADE_MODE_FULL,
        visible=True,
    ):
        self.filling_mode = flags
        self.trade_exemode = execution
        self.trade_mode = trade_mode
        self.visible = visible
        self.name = "EURUSD"


def test_allowed_fillings_from_symbol_flags():
    modes = allowed_fillings(MockSymbol(flags=1 | 2))
    assert modes == [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]


def test_no_return_policy_for_market_execution():
    assert allowed_fillings(MockSymbol(flags=2)) == [mt5.ORDER_FILLING_IOC]
    assert allowed_fillings(MockSymbol(flags=0)) == []


def test_instant_execution_allows_fillings_independent_of_flags():
    modes = allowed_fillings(
        MockSymbol(flags=0, execution=mt5.SYMBOL_TRADE_EXECUTION_INSTANT)
    )
    assert mt5.ORDER_FILLING_FOK in modes
    assert mt5.ORDER_FILLING_IOC in modes
    assert mt5.ORDER_FILLING_RETURN in modes


def test_rejects_order_when_no_supported_policy():
    with pytest.raises(ValueError, match="No supported"):
        build_market_order_request(
            symbol="EURUSD",
            action=mt5.ORDER_TYPE_BUY,
            volume=0.1,
            price=1.2345,
            deviation=10,
            sl=1.2300,
            tp=1.2400,
            symbol_info=MockSymbol(flags=0),
        )


def test_build_order_request():
    req = build_market_order_request(
        symbol="EURUSD",
        action=mt5.ORDER_TYPE_BUY,
        volume=0.1,
        price=1.2345,
        deviation=10,
        sl=1.2300,
        tp=1.2400,
        symbol_info=MockSymbol(flags=1),
    )
    assert req.request["symbol"] == "EURUSD"
    assert req.request["type_filling"] == mt5.ORDER_FILLING_FOK
    assert req.request["sl"] == 1.2300
    assert req.request["tp"] == 1.2400


def test_disabled_symbols_are_not_tradable():
    assert is_symbol_tradable(MockSymbol(trade_mode=mt5.SYMBOL_TRADE_MODE_FULL))
    assert not is_symbol_tradable(MockSymbol(trade_mode=mt5.SYMBOL_TRADE_MODE_DISABLED))
    assert not is_symbol_tradable(MockSymbol(visible=False))
