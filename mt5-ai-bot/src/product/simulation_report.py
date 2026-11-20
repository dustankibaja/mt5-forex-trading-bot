"""Portable, non-promotional reports for historical simulation results."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from .historical_backtest import _content_fingerprint


_TRADE_COLUMNS=("entry_time","exit_time","side","lots","entry","exit","stop","target","reason",
                "gross_pnl","commission","financing","net_pnl")
_REJECTION_EXPLANATIONS={
    "outside_session":"The completed-candle signal occurred outside the configured strategy session.",
    "maximum_open_positions":"A simulated position was already open when this signal became eligible.",
    "below_minimum_lot":"The risk-sized simulated volume was below the configured minimum lot.",
    "above_maximum_lot":"The risk-sized simulated volume exceeded the configured maximum lot.",
    "insufficient_margin":"The simulated margin requirement exceeded available simulated balance.",
}


def _available(value: Any) -> Any:
    return "unavailable" if value is None else value


def build(result: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic user-facing report; never describes performance as validation."""
    if not isinstance(result, dict) or result.get("execution_enabled") is not False:
        raise ValueError("only locked historical simulation results can be reported")
    manifest=result.get("manifest")
    if not isinstance(manifest,dict) or manifest.get("simulation_kind")!="HISTORICAL_SIMULATION":
        raise ValueError("historical simulation manifest is required")
    if _content_fingerprint(result)!=manifest.get("simulation_content_fingerprint"):
        raise ValueError("simulation content fingerprint does not match result")
    dataset=manifest.get("dataset",{})
    if not all(dataset.get(key) for key in ("identifier","source","content_hash","price_basis")):
        raise ValueError("dataset provenance is incomplete")
    metrics=result.get("metrics",{})
    rejected=[]
    for item in result.get("rejected_signals",[]):
        reason=item.get("reason")
        rejected.append({**item,"explanation":_REJECTION_EXPLANATIONS.get(reason,"Simulation rejected this signal for an unrecognised recorded reason.")})
    return {"report_version":"simulation-report-v1","label":"HISTORICAL SIMULATION — NOT BROKER EXECUTION",
      "reproducibility":{"simulation_content_fingerprint":manifest["simulation_content_fingerprint"],"run_id":manifest["run_id"],"execution_model":manifest["execution_model"],"cost_model":manifest["cost_model"]},
      "strategy":{"name":manifest["strategy_name"],"id":manifest["strategy_id"],"version":manifest["strategy_version"],"configuration_hash":manifest["strategy_hash"],"symbol":manifest["symbol"],"timeframe":manifest["timeframe"]},
      "dataset":{"identity":dataset["identifier"],"source":dataset["source"],"content_hash":dataset["content_hash"],"price_basis":dataset["price_basis"],"provenance":dataset},
      "period":{"historical_date_range":manifest["date_range"],"evaluation_range":manifest["evaluation_range"],"timestamp_convention":manifest["timestamp_convention"]},
      "simulation":{"initial_balance":metrics.get("realized_balance",0)-metrics.get("realized_pnl",0),"ending_simulated_equity":metrics.get("ending_equity"),"simulated_net_return_percent":metrics.get("return_percent"),"completed_trades":metrics.get("closed_trades"),"win_rate_percent":_available(metrics.get("win_rate_percent")),"profit_factor":_available(metrics.get("profit_factor")),"maximum_observed_simulation_drawdown_percent":metrics.get("maximum_drawdown_percent"),"realized_pnl":metrics.get("realized_pnl"),"unrealized_pnl":metrics.get("unrealized_pnl"),"open_simulated_position":result.get("open_position"),"trading_costs":metrics.get("trading_costs")},
      "equity_curve":result.get("equity_curve",[]),"historical_trade_ledger":result.get("trades",[]),"rejected_signals":rejected,"warnings":manifest.get("warnings",[]),"limitations":["Historical simulation is not broker execution.","Positive simulated return does not validate profitability or production readiness.","Undefined metrics are shown as unavailable."],"execution_enabled":False}


def json_export(result:dict[str,Any])->str:
    return json.dumps(build(result),sort_keys=True,separators=(",",":"),default=str)


def trade_ledger_csv(result:dict[str,Any])->str:
    report=build(result); output=io.StringIO(newline=""); writer=csv.DictWriter(output,fieldnames=_TRADE_COLUMNS,extrasaction="ignore")
    writer.writeheader();writer.writerows(report["historical_trade_ledger"]);return output.getvalue()
