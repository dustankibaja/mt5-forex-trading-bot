from datetime import datetime,timedelta,timezone
from src.product import historical_backtest
from src.product.historical_backtest import CostModel,run
from src.product import historical_backtest
from src.product.strategy_spec import validate_strategy

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

def test_replay_is_deterministic_except_run_identity():
    ds={"identifier":"independent-reference-fixture","content_hash":"fixed","source":"independent arithmetic fixture","price_basis":"bid_ask","eligible_for_backtest":True}
    a=run(strategy(),rows(),initial_balance=10000,dataset=ds,costs=CostModel())
    b=run(strategy(),rows(),initial_balance=10000,dataset=ds,costs=CostModel())
    assert a["metrics"]==b["metrics"] and a["trades"]==b["trades"]
    assert a["execution_enabled"] is False
    assert all(t["entry_time"]!=i["decision_candle"] for t,i in zip(a["trades"],a["order_intents"]))

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
