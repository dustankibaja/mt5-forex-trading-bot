import csv

from src.monitoring.journal import TradeJournal


def test_trade_journal_accepts_string_path(tmp_path):
    location = tmp_path / "nested" / "trades.csv"
    journal = TradeJournal(path=str(location))
    row = {
        "time": "2026-11-04T00:00:00Z",
        "symbol": "EURUSD",
        "direction": "BUY",
        "volume": 0.01,
        "price": 1.1,
        "sl": 1.09,
        "tp": 1.12,
        "ticket": 1,
        "comment": "test",
    }
    journal.append(row)

    with location.open(newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "EURUSD"
