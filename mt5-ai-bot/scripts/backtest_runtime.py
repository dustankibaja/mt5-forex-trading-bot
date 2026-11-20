"""Versioned JSON/CSV historical backtest helper. Contains no broker imports."""
from __future__ import annotations
import argparse,csv,hashlib,json,sys
from pathlib import Path
from src.product.historical_backtest import CostModel,run
from src.product.simulation_report import build as build_report
from src.product.strategy_spec import validate_strategy

CONTRACT_VERSION="1.0.0"
COLUMNS=("timestamp","bid_open","bid_high","bid_low","bid_close","ask_open","ask_high","ask_low","ask_close")

def load_csv(path:Path)->tuple[list[dict],str]:
    raw=path.read_bytes(); digest=hashlib.sha256(raw).hexdigest()
    with path.open("r",encoding="utf-8-sig",newline="") as stream:
        reader=csv.DictReader(stream)
        if tuple(reader.fieldnames or ())!=COLUMNS:raise ValueError("CSV columns must exactly match the documented EURUSD bid/ask template")
        rows=[]
        for n,value in enumerate(reader,2):
            try:rows.append({"timestamp":value["timestamp"],**{k:float(value[k]) for k in COLUMNS[1:]}})
            except Exception as error:raise ValueError(f"CSV row {n} contains an invalid number") from error
    if len(rows)<3:raise ValueError("dataset needs at least three completed candles")
    return rows,digest

def dataset(request:dict,path:Path,digest:str)->dict:
    meta=request.get("dataset")
    if not isinstance(meta,dict):raise ValueError("dataset metadata are required")
    if meta.get("symbol")!="EURUSD":raise ValueError("only EURUSD datasets are supported")
    if meta.get("intended_use")!="performance_backtest":raise ValueError("dataset is not intended for performance backtesting")
    if meta.get("permission") not in {"user_supplied_authorized","synthetic_demo"}:raise ValueError("dataset permission must be explicitly documented")
    return {"identifier":str(meta.get("identifier") or path.stem),"content_hash":digest,"source":str(meta.get("source") or "user supplied CSV"),"price_basis":"bid_ask","eligible_for_backtest":True,"permission":meta["permission"],"synthetic":meta["permission"]=="synthetic_demo","timeframe":meta.get("timeframe")}

def main()->int:
    p=argparse.ArgumentParser();p.add_argument("command",choices=("validate","run"));p.add_argument("request",type=Path);p.add_argument("csv",type=Path);a=p.parse_args()
    try:
        req=json.loads(a.request.read_text(encoding="utf-8"),parse_constant=lambda v:(_ for _ in()).throw(ValueError(f"invalid numeric constant {v}")))
        if req.get("contract_version")!=CONTRACT_VERSION:raise ValueError(f"contract_version must be {CONTRACT_VERSION}")
        rows,digest=load_csv(a.csv);ds=dataset(req,a.csv,digest)
        if a.command=="validate":
            result={"contract_version":CONTRACT_VERSION,"dataset":ds,"rows":len(rows),"first_utc":rows[0]["timestamp"],"last_utc":rows[-1]["timestamp"],"warnings":["Synthetic demonstration data must not be interpreted as historical forex performance."] if ds["synthetic"] else []}
        else:
            strategy=validate_strategy(req.get("strategy"));
            if ds.get("timeframe")!=strategy["timeframe"]:raise ValueError("dataset timeframe does not match the strategy")
            start,end=req.get("start_date"),req.get("end_date")
            selected=[r for r in rows if (not start or r["timestamp"][:10]>=start) and (not end or r["timestamp"][:10]<=end)]
            if len(selected)<3:raise ValueError("selected date range has insufficient completed candles")
            costs=CostModel(**(req.get("cost_model") or {}));result=run(strategy,rows,initial_balance=req.get("initial_balance"),dataset=ds,costs=costs,trade_start=start,trade_end=end);result["report"]=build_report(result);result["contract_version"]=CONTRACT_VERSION
        print(json.dumps(result,sort_keys=True,separators=(",",":"),allow_nan=False));return 0
    except Exception as error:
        print(json.dumps({"contract_version":CONTRACT_VERSION,"error":str(error),"execution_enabled":False}),file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
