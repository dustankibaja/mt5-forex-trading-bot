from types import SimpleNamespace

import MetaTrader5 as mt5

from src.execution.mt5_adapter import MT5Adapter


def test_successful_pretrade_check_allows_order_send(monkeypatch):
    adapter = MT5Adapter(retry_attempts=1, retry_backoff_seconds=0)
    sent = []
    monkeypatch.setattr(
        adapter, "order_check",
        lambda request: SimpleNamespace(retcode=0, comment="Done"),
    )
    monkeypatch.setattr(
        adapter, "order_send",
        lambda request: sent.append(request)
        or SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, comment="Executed"),
    )

    request = {"symbol": "EURUSD", "sl": 1.0, "tp": 1.1}
    response = adapter.place_market_order(request)
    assert sent == [request]
    assert response.result.retcode == mt5.TRADE_RETCODE_DONE


def test_failed_pretrade_check_blocks_order_send(monkeypatch):
    adapter = MT5Adapter(retry_attempts=1, retry_backoff_seconds=0)
    monkeypatch.setattr(
        adapter, "order_check",
        lambda request: SimpleNamespace(retcode=mt5.TRADE_RETCODE_INVALID_STOPS, comment="Invalid stops"),
    )
    sent = []
    monkeypatch.setattr(adapter, "order_send", lambda request: sent.append(request))

    response = adapter.place_market_order({"symbol": "EURUSD"})
    assert sent == []
    assert response.result.retcode == mt5.TRADE_RETCODE_INVALID_STOPS
