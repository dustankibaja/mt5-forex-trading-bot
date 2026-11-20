from datetime import datetime,timedelta,timezone
from src.product.historical_backtest import CostModel,run
from src.product import historical_backtest
from src.product.strategy_spec import validate_strategy
from src.product.simulation_report import build,json_export,trade_ledger_csv

def strategy():
    ind=lambda p:{"type":"indicator","indicator":"EMA","period":p}
    comp=lambda op:{"type":"group","operator":"AND","conditions":[{"type":"comparison","left":ind(2),"operator":op,"right":ind(3)}]}
    return validate_strategy({"schema_version":"1.0.0","strategy_id":"historical-fixture","version":1,"name":"fixture","description":"","symbol":"EURUSD","timeframe":"H1","evaluation":"completed_candle","long_entry":comp("crosses_above"),"short_entry":comp("crosses_below"),"session":{"timezone":"UTC","start":"00:00","end":"23:59"},"risk":{"risk_per_trade_percent":.25,"maximum_simultaneous_positions":1},"exits":{"stop_loss_pips":10,"take_profit_pips":20,"opposite_signal":True,"maximum_holding_candles":3},"confirmed_for_testing":True})

def rows():
    values=[1.1000,1.0990,1.0980,1.1010,1.1030,1.1040,1.1000,1.0970,1.0950,1.0940]
    start=datetime(2025,1,6,tzinfo=timezone.utc); out=[]
    for i,v in enumerate(values):
        out.append({"timestamp":(start+timedelta(hours=i)).isoformat(),"bid_open":v,"bid_high":v+.001,"bid_low":v-.001,"bid_close":v,"ask_open":v+.0002,"ask_high":v+.0012,"ask_low":v-.0008,"ask_close":v+.0002})
    return out

def flat_rows():
    return [{**row,"bid_open":1.1,"bid_high":1.101,"bid_low":1.099,"bid_close":1.1,"ask_open":1.1002,"ask_high":1.1012,"ask_low":1.0992,"ask_close":1.1002} for row in rows()]

def test_replay_is_deterministic_except_run_identity():
    ds={"identifier":"independent-reference-fixture","content_hash":"fixed","source":"independent arithmetic fixture","price_basis":"bid_ask","eligible_for_backtest":True}
    a=run(strategy(),rows(),initial_balance=10000,dataset=ds,costs=CostModel())
    b=run(strategy(),rows(),initial_balance=10000,dataset=ds,costs=CostModel())
    assert a["metrics"]==b["metrics"] and a["trades"]==b["trades"]
    assert a["execution_enabled"] is False
    assert all(t["entry_time"]!=i["decision_candle"] for t,i in zip(a["trades"],a["order_intents"]))
    assert a["manifest"]["run_id"] != b["manifest"]["run_id"]
    assert a["manifest"]["simulation_content_fingerprint"] == b["manifest"]["simulation_content_fingerprint"]

def test_portable_report_preserves_provenance_and_unavailable_metrics():
    ds={"identifier":"fixture","content_hash":"fixed","source":"identified fixture","price_basis":"bid_ask","eligible_for_backtest":True}
    result=run(strategy(),flat_rows(),initial_balance=10000,dataset=ds)
    report=build(result)
    assert report["label"].startswith("HISTORICAL SIMULATION") and report["execution_enabled"] is False
    assert report["dataset"]["content_hash"]=="fixed"
    assert report["simulation"]["profit_factor"]=="unavailable"
    assert json_export(result)==json_export(result)
    assert trade_ledger_csv(result).splitlines()[0].startswith("entry_time,exit_time")

def test_report_rejects_tampered_or_execution_enabled_results():
    ds={"identifier":"fixture","content_hash":"fixed","source":"identified fixture","price_basis":"bid_ask","eligible_for_backtest":True}
    result=run(strategy(),rows(),initial_balance=10000,dataset=ds)
    result["execution_enabled"]=True
    import pytest
    with pytest.raises(ValueError,match="locked"):
        build(result)

def test_report_rejects_content_tampering_and_keeps_cost_assumptions():
    import pytest
    ds={"identifier":"fixture","content_hash":"fixed","source":"identified fixture","price_basis":"bid_ask","eligible_for_backtest":True}
    result=run(strategy(),rows(),initial_balance=10000,dataset=ds,costs=CostModel(slippage_pips=.6,commission_per_lot_round_turn=9))
    report=build(result)
    assert report["reproducibility"]["cost_model"]["slippage_pips"] == .6
    result["metrics"]["ending_equity"] += 1
    with pytest.raises(ValueError,match="fingerprint"):
        build(result)

def test_cost_stress_cannot_improve_results():
    ds={"identifier":"fixture","content_hash":"fixed","source":"fixture","price_basis":"bid_ask","eligible_for_backtest":True}
    base=run(strategy(),rows(),initial_balance=10000,dataset=ds,costs=CostModel(slippage_pips=0,commission_per_lot_round_turn=0))
    stress=run(strategy(),rows(),initial_balance=10000,dataset=ds,costs=CostModel(slippage_pips=1,commission_per_lot_round_turn=12))
    assert stress["metrics"]["net_profit"] <= base["metrics"]["net_profit"]

def test_pre_start_candles_warm_indicators_but_cannot_trade():
    ds={"identifier":"fixture","content_hash":"fixed","source":"fixture","price_basis":"bid_ask","eligible_for_backtest":True}
    result=run(strategy(),rows(),initial_balance=10000,dataset=ds,trade_start="2025-01-06",trade_end="2025-01-06")
    assert all(intent["eligible_quote"][:10] >= "2025-01-06" for intent in result["order_intents"])
    assert result["manifest"]["warmup_policy"].startswith("pre-start candles")

def test_unexpected_signal_error_is_not_silently_neutral(monkeypatch):
    ds={"identifier":"fixture","content_hash":"fixed","source":"fixture","price_basis":"bid_ask","eligible_for_backtest":True}
    monkeypatch.setattr(historical_backtest,"_evaluate_node",lambda *a,**k:(_ for _ in ()).throw(RuntimeError("broken evaluator")))
    import pytest
    with pytest.raises(RuntimeError,match="broken evaluator"):
        run(strategy(),rows(),initial_balance=10000,dataset=ds)
