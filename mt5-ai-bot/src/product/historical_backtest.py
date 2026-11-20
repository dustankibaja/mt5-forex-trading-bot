"""Causal, deterministic and order-free bid/ask historical simulation."""
from __future__ import annotations
import hashlib,json,math,uuid
from dataclasses import dataclass,asdict
from typing import Any
from .strategy_spec import validate_strategy
from .strategy_evaluator import CandleValidationError,_evaluate_node,validate_candles

MODEL_VERSION="historical-bidask-v2"; PIP=.0001
@dataclass(frozen=True)
class CostModel:
    slippage_pips:float=.2; commission_per_lot_round_turn:float=7.; financing_per_lot_per_day:float=0.
    contract_size:float=100000.; leverage:float=30.; minimum_lot:float=.01; lot_step:float=.01; maximum_lot:float=100.

def _hash(v:Any)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def _content_fingerprint(result:dict[str,Any])->str:
    """Hash reproducible simulation content, deliberately excluding run identity."""
    copied=json.loads(json.dumps(result,sort_keys=True,default=str))
    manifest=copied.get("manifest",{})
    manifest.pop("run_id",None)
    manifest.pop("simulation_content_fingerprint",None)
    manifest.pop("simulation_result_hash",None)
    return _hash(copied)
def _finite(v:Any,name:str,*,positive=False,nonnegative=False)->float:
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(float(v)):raise ValueError(f"{name} must be finite")
    x=float(v)
    if positive and x<=0:raise ValueError(f"{name} must be positive")
    if nonnegative and x<0:raise ValueError(f"{name} cannot be negative")
    return x
def _validate_costs(c:CostModel)->None:
    for n in ("contract_size","leverage","minimum_lot","lot_step","maximum_lot"):_finite(getattr(c,n),n,positive=True)
    for n in ("slippage_pips","commission_per_lot_round_turn","financing_per_lot_per_day"):_finite(getattr(c,n),n,nonnegative=True)
    if c.minimum_lot>c.maximum_lot:raise ValueError("minimum_lot cannot exceed maximum_lot")
    q=c.minimum_lot/c.lot_step
    if not math.isclose(q,round(q),abs_tol=1e-9):raise ValueError("minimum_lot must align to lot_step")
def _session(stamp:str,s:dict[str,Any])->bool:
    hm=stamp[11:16]; start,end=s["start"],s["end"]
    return start<=hm<end if start<end else hm>=start or hm<end
def _signal(strategy:dict[str,Any],candles:list[dict[str,Any]],decision:int)->str|None:
    try:lp,_=_evaluate_node(strategy["long_entry"],candles[:decision+1],decision);sp,_=_evaluate_node(strategy["short_entry"],candles[:decision+1],decision)
    except CandleValidationError as error:
        if "warm-up" in str(error):return None
        raise
    return "long" if lp and not sp else "short" if sp and not lp else None
def _unrealized(p:dict[str,Any]|None,row:dict[str,Any],c:CostModel)->float:
    if not p:return 0.
    executable=row["bid_close"] if p["side"]=="long" else row["ask_close"]
    return (executable-p["entry"])*(1 if p["side"]=="long" else -1)*c.contract_size*p["lots"]
def _exit(position:dict[str,Any],price:float,stamp:str,reason:str,balance:float,c:CostModel,index:int)->tuple[float,dict[str,Any]]:
    sign=1 if position["side"]=="long" else -1;gross=(price-position["entry"])*sign*c.contract_size*position["lots"]
    commission=c.commission_per_lot_round_turn*position["lots"]
    financing=c.financing_per_lot_per_day*position["lots"]*max(0,index-position["index"])*position["hours_per_bar"]/24
    net=gross-commission-financing
    return balance+net,{**position,"exit_time":stamp,"exit":price,"reason":reason,"gross_pnl":gross,"commission":commission,"financing":financing,"net_pnl":net}

def run(strategy_raw:dict[str,Any],rows:list[dict[str,Any]],*,initial_balance:float,dataset:dict[str,Any],costs:CostModel=CostModel(),trade_start:str|None=None,trade_end:str|None=None)->dict[str,Any]:
    strategy=validate_strategy(strategy_raw);_validate_costs(costs);initial_balance=_finite(initial_balance,"initial balance",positive=True)
    if not strategy["confirmed_for_testing"]:raise ValueError("strategy must be confirmed for historical signal testing")
    required={"identifier","content_hash","source","price_basis"}
    if not isinstance(dataset,dict) or not required<=set(dataset):raise ValueError("dataset identity and provenance are incomplete")
    if dataset.get("eligible_for_backtest") is not True:raise ValueError("dataset is not eligible for performance backtesting")
    candles=[]
    for n,r in enumerate(rows):
        for k in ("bid_open","bid_high","bid_low","bid_close","ask_open","ask_high","ask_low","ask_close"):_finite(r.get(k),f"row {n}.{k}",positive=True)
        if r["bid_low"]>min(r["bid_open"],r["bid_close"]) or r["bid_high"]<max(r["bid_open"],r["bid_close"]) or r["ask_low"]>min(r["ask_open"],r["ask_close"]) or r["ask_high"]<max(r["ask_open"],r["ask_close"]):raise ValueError(f"row {n} has invalid OHLC geometry")
        if min(r["ask_open"]-r["bid_open"],r["ask_high"]-r["bid_high"],r["ask_low"]-r["bid_low"],r["ask_close"]-r["bid_close"])<0:raise ValueError(f"row {n} contains crossed quotes")
        candles.append({"timestamp":r["timestamp"],"open":(r["bid_open"]+r["ask_open"])/2,"high":(r["bid_high"]+r["ask_high"])/2,"low":(r["bid_low"]+r["ask_low"])/2,"close":(r["bid_close"]+r["ask_close"])/2,"complete":True,"source":dataset["identifier"],"price_basis":"mid_bid_ask"})
    validate_candles(candles,strategy["timeframe"])
    balance=initial_balance;position=None;trades=[];rejected=[];intents=[];equity=[];peak=initial_balance;max_dd=0.;hours={"M15":.25,"H1":1.,"H4":4.,"D1":24.}[strategy["timeframe"]]
    for i in range(2,len(rows)):
        row=rows[i];stamp=candles[i]["timestamp"];signal=_signal(strategy,candles,i-1);opened=False
        trading_enabled=(trade_start is None or stamp[:10]>=trade_start) and (trade_end is None or stamp[:10]<=trade_end)
        # OPEN EVENT: only prior completed-candle information is available here.
        if position and ((strategy["exits"]["opposite_signal"] and signal and signal!=position["side"]) or i-position["index"]>=strategy["exits"]["maximum_holding_candles"]):
            reason="opposite_signal" if signal and signal!=position["side"] else "maximum_holding"
            px=(row["bid_open"]-costs.slippage_pips*PIP) if position["side"]=="long" else (row["ask_open"]+costs.slippage_pips*PIP)
            balance,t=_exit(position,px,stamp,reason,balance,costs,i);trades.append(t);position=None
        if signal and trading_enabled:
            intent={"decision_candle":candles[i-1]["timestamp"],"eligible_quote":stamp,"side":signal};intents.append(intent)
            if not _session(stamp,strategy["session"]):rejected.append({**intent,"reason":"outside_session"})
            elif position:rejected.append({**intent,"reason":"maximum_open_positions"})
            else:
                entry=(row["ask_open"]+costs.slippage_pips*PIP) if signal=="long" else (row["bid_open"]-costs.slippage_pips*PIP)
                distance=strategy["exits"]["stop_loss_pips"]*PIP;risk_budget=balance*strategy["risk"]["risk_per_trade_percent"]/100
                # Reserve round-turn commission inside the risk budget.
                raw=risk_budget/(distance*costs.contract_size+costs.commission_per_lot_round_turn)
                lots=math.floor(raw/costs.lot_step+1e-12)*costs.lot_step;margin=entry*costs.contract_size*lots/costs.leverage
                if lots<costs.minimum_lot:rejected.append({**intent,"reason":"below_minimum_lot"})
                elif lots>costs.maximum_lot:rejected.append({**intent,"reason":"above_maximum_lot"})
                elif margin>balance:rejected.append({**intent,"reason":"insufficient_margin"})
                else:
                    position={"entry_time":stamp,"index":i,"side":signal,"entry":entry,"lots":lots,"stop":entry-distance if signal=="long" else entry+distance,"target":entry+strategy["exits"]["take_profit_pips"]*PIP if signal=="long" else entry-strategy["exits"]["take_profit_pips"]*PIP,"hours_per_bar":hours,"margin":margin};opened=True
        # INTRABAR EVENT: includes the entry candle. Stop wins ambiguous bars.
        if position:
            if position["side"]=="long":
                stop=row["bid_low"]<=position["stop"];target=row["bid_high"]>=position["target"]
                if stop:px=min(row["bid_open"],position["stop"])-costs.slippage_pips*PIP;reason="stop_conservative_ambiguous_bar" if target else ("entry_bar_stop" if opened else "stop")
                elif target:px=position["target"]-costs.slippage_pips*PIP;reason="entry_bar_target" if opened else "target"
                else:px=None
            else:
                stop=row["ask_high"]>=position["stop"];target=row["ask_low"]<=position["target"]
                if stop:px=max(row["ask_open"],position["stop"])+costs.slippage_pips*PIP;reason="stop_conservative_ambiguous_bar" if target else ("entry_bar_stop" if opened else "stop")
                elif target:px=position["target"]+costs.slippage_pips*PIP;reason="entry_bar_target" if opened else "target"
                else:px=None
            if px is not None:balance,t=_exit(position,px,stamp,reason,balance,costs,i);trades.append(t);position=None
        unrealized=_unrealized(position,row,costs);total=balance+unrealized;peak=max(peak,total);max_dd=max(max_dd,(peak-total)/peak if peak else 0)
        equity.append({"timestamp":stamp,"balance":balance,"unrealized_pnl":unrealized,"equity":total,"margin":position["margin"] if position else 0.,"open_exposure":position["lots"]*costs.contract_size if position else 0.})
    last=rows[-1];unrealized=_unrealized(position,last,costs);total=balance+unrealized
    wins=[t for t in trades if t["net_pnl"]>0];losses=[t for t in trades if t["net_pnl"]<0];gp=sum(t["net_pnl"] for t in wins);gl=-sum(t["net_pnl"] for t in losses)
    metrics={"realized_balance":balance,"realized_pnl":balance-initial_balance,"unrealized_pnl":unrealized,"ending_equity":total,"net_profit":total-initial_balance,"return_percent":(total/initial_balance-1)*100,"closed_trades":len(trades),"winning_trades":len(wins),"losing_trades":len(losses),"win_rate_percent":len(wins)/len(trades)*100 if trades else None,"profit_factor":gp/gl if gl else None,"maximum_drawdown_percent":max_dd*100,"average_trade":sum(t["net_pnl"] for t in trades)/len(trades) if trades else None,"trading_costs":sum(t["commission"]+t["financing"] for t in trades),"open_positions":1 if position else 0}
    warnings=(["Fewer than 30 completed trades; results are statistically weak."] if len(trades)<30 else [])+["Same-bar stop/target ambiguity is resolved adversely at the stop.","Contract, leverage, financing and commission assumptions are user supplied and not verified by the dataset."]
    manifest={"simulation_kind":"HISTORICAL_SIMULATION","strategy_id":strategy["strategy_id"],"strategy_name":strategy["name"],"strategy_version":strategy["version"],"strategy_hash":strategy["configuration_hash"],"symbol":strategy["symbol"],"timeframe":strategy["timeframe"],"dataset":dataset,"date_range":[candles[0]["timestamp"],candles[-1]["timestamp"]],"evaluation_range":[trade_start,trade_end],"warmup_policy":"pre-start candles initialize indicators; entries are prohibited before selected start","execution_model":MODEL_VERSION,"cost_model":asdict(costs),"timestamp_convention":"UTC completed-candle open timestamps; session start inclusive/end exclusive","run_id":str(uuid.uuid4()),"warnings":warnings}
    result={"simulation_label":"HISTORICAL SIMULATION — NOT BROKER EXECUTION","metrics":metrics,"trades":trades,"open_position":position,"rejected_signals":rejected,"order_intents":intents,"equity_curve":equity,"manifest":manifest,"execution_enabled":False};manifest["simulation_content_fingerprint"]=_content_fingerprint(result);manifest["simulation_result_hash"]=manifest["simulation_content_fingerprint"];return result
