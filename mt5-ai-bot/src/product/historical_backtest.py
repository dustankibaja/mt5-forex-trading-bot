"""Deterministic, order-free bid/ask historical simulation for product tests."""
from __future__ import annotations
import hashlib, json, math, uuid
from dataclasses import dataclass, asdict
from typing import Any
from .strategy_spec import validate_strategy
from .strategy_evaluator import _evaluate_node, validate_candles

MODEL_VERSION = "historical-bidask-v1"

@dataclass(frozen=True)
class CostModel:
    slippage_pips: float = 0.2
    commission_per_lot_round_turn: float = 7.0
    financing_per_lot_per_day: float = 0.0
    contract_size: float = 100000.0
    leverage: float = 30.0
    minimum_lot: float = 0.01
    lot_step: float = 0.01
    maximum_lot: float = 100.0

def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def run(strategy_raw: dict[str,Any], rows: list[dict[str,Any]], *, initial_balance: float,
        dataset: dict[str,Any], costs: CostModel = CostModel()) -> dict[str,Any]:
    strategy=validate_strategy(strategy_raw)
    if not strategy["confirmed_for_testing"]: raise ValueError("strategy must be confirmed for historical signal testing")
    if initial_balance <= 0 or not math.isfinite(initial_balance): raise ValueError("initial balance must be positive and finite")
    candles=[]
    for r in rows:
        candles.append({"timestamp":r["timestamp"],"open":(r["bid_open"]+r["ask_open"])/2,"high":(r["bid_high"]+r["ask_high"])/2,"low":(r["bid_low"]+r["ask_low"])/2,"close":(r["bid_close"]+r["ask_close"])/2,"complete":True,"source":dataset["identifier"],"price_basis":"mid_bid_ask"})
    validate_candles(candles,strategy["timeframe"])
    balance=float(initial_balance); peak=balance; max_dd=0.0; position=None; trades=[]; rejected=[]; equity=[]; intents=[]
    pip=.0001
    for i in range(2,len(rows)):
        row=rows[i]; candle=candles[i]; exit_reason=None; exit_price=None
        if position:
            if position["side"]=="long":
                stop_hit=row["bid_low"]<=position["stop"]; target_hit=row["bid_high"]>=position["target"]
                if stop_hit: exit_price=position["stop"]-costs.slippage_pips*pip; exit_reason="stop" if not target_hit else "stop_conservative_ambiguous_bar"
                elif target_hit: exit_price=position["target"]-costs.slippage_pips*pip; exit_reason="target"
            else:
                stop_hit=row["ask_high"]>=position["stop"]; target_hit=row["ask_low"]<=position["target"]
                if stop_hit: exit_price=position["stop"]+costs.slippage_pips*pip; exit_reason="stop" if not target_hit else "stop_conservative_ambiguous_bar"
                elif target_hit: exit_price=position["target"]+costs.slippage_pips*pip; exit_reason="target"
            held=i-position["index"]
            if exit_price is None and held>=strategy["exits"]["maximum_holding_candles"]:
                exit_price=row["bid_open"] if position["side"]=="long" else row["ask_open"]; exit_reason="maximum_holding"
            if exit_price is not None:
                sign=1 if position["side"]=="long" else -1
                gross=(exit_price-position["entry"])*sign*costs.contract_size*position["lots"]
                commission=costs.commission_per_lot_round_turn*position["lots"]
                days=max(0,(i-position["index"])*({"M15":.25,"H1":1,"H4":4,"D1":24}[strategy["timeframe"]])/24)
                financing=costs.financing_per_lot_per_day*position["lots"]*days
                net=gross-commission-financing; balance+=net
                trades.append({**position,"exit_time":candle["timestamp"],"exit":exit_price,"reason":exit_reason,"gross_pnl":gross,"commission":commission,"financing":financing,"net_pnl":net})
                position=None
        try:
            lp,_=_evaluate_node(strategy["long_entry"],candles[:i],i-1); sp,_=_evaluate_node(strategy["short_entry"],candles[:i],i-1)
        except Exception:
            lp=sp=False
        signal="long" if lp and not sp else "short" if sp and not lp else None
        if signal:
            intent={"decision_candle":candles[i-1]["timestamp"],"eligible_quote":candle["timestamp"],"side":signal}; intents.append(intent)
            if position is not None: rejected.append({**intent,"reason":"maximum_open_positions"})
            else:
                entry=(row["ask_open"] if signal=="long" else row["bid_open"])+(costs.slippage_pips*pip*(1 if signal=="long" else -1))
                stop_dist=strategy["exits"]["stop_loss_pips"]*pip; risk=balance*strategy["risk"]["risk_per_trade_percent"]/100
                lots=math.floor((risk/(stop_dist*costs.contract_size))/costs.lot_step)*costs.lot_step
                margin=entry*costs.contract_size*lots/costs.leverage
                if lots<costs.minimum_lot: rejected.append({**intent,"reason":"below_minimum_lot"})
                elif lots>costs.maximum_lot or margin>balance: rejected.append({**intent,"reason":"margin_or_maximum_lot"})
                else: position={"entry_time":candle["timestamp"],"index":i,"side":signal,"entry":entry,"lots":lots,"stop":entry-stop_dist if signal=="long" else entry+stop_dist,"target":entry+strategy["exits"]["take_profit_pips"]*pip if signal=="long" else entry-strategy["exits"]["take_profit_pips"]*pip}
        peak=max(peak,balance); max_dd=max(max_dd,(peak-balance)/peak if peak else 0); equity.append({"timestamp":candle["timestamp"],"equity":balance})
    wins=[t for t in trades if t["net_pnl"]>0]; losses=[t for t in trades if t["net_pnl"]<0]; gp=sum(t["net_pnl"] for t in wins); gl=-sum(t["net_pnl"] for t in losses)
    metrics={"net_profit":balance-initial_balance,"return_percent":(balance/initial_balance-1)*100,"trades":len(trades),"winning_trades":len(wins),"losing_trades":len(losses),"win_rate_percent":len(wins)/len(trades)*100 if trades else 0,"profit_factor":gp/gl if gl else None,"maximum_drawdown_percent":max_dd*100,"average_trade":sum(t["net_pnl"] for t in trades)/len(trades) if trades else 0,"trading_costs":sum(t["commission"]+t["financing"] for t in trades)}
    manifest={"strategy_id":strategy["strategy_id"],"strategy_version":strategy["version"],"strategy_hash":strategy["configuration_hash"],"dataset":dataset,"date_range":[candles[0]["timestamp"],candles[-1]["timestamp"]],"warmup_policy":"signals suppressed until every indicator operand is finite","execution_model":MODEL_VERSION,"cost_model":asdict(costs),"timestamp_convention":"UTC completed-candle open timestamps","run_id":str(uuid.uuid4()),"warnings":(["Fewer than 30 completed trades; results are statistically weak."] if len(trades)<30 else [])+["If stop and target occur in one bar, the stop is applied conservatively."]}
    result={"metrics":metrics,"trades":trades,"rejected_signals":rejected,"order_intents":intents,"equity_curve":equity,"manifest":manifest,"execution_enabled":False}; manifest["simulation_result_hash"]=_hash(result); return result
