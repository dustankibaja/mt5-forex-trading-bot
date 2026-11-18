"""Canonical crash-safe journal for future DEMO order intents.

This module never calls a broker. It records preparation and reconciliation
state so an uncertain outcome is blocked from automatic retry.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any


class IntentBlocked(RuntimeError):
    pass


UNRECONCILED={"RESERVED","CHECKED","SEND_STARTED","UNKNOWN","PARTIAL","ACCEPTED"}
FINAL={"REJECTED","CANCELLED","CLOSED_RECONCILED"}


def canonical_intent_id(intent:dict[str,Any])->str:
    allowed={key:intent.get(key) for key in ("binding_id","symbol","side","volume","sl","tp","strategy_hash","signal_id")}
    return hashlib.sha256(json.dumps(allowed,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


class DemoIntentJournal:
    def __init__(self,path:Path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=20,isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS intents(
          intent_id TEXT PRIMARY KEY,binding_id TEXT NOT NULL,created_utc TEXT NOT NULL,
          payload TEXT NOT NULL,status TEXT NOT NULL,broker_order INTEGER,broker_deal INTEGER,
          note TEXT NOT NULL DEFAULT '')""")
        self.db.execute("CREATE TABLE IF NOT EXISTS controls(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    def close(self):self.db.close()
    def set_emergency_stop(self,active:bool):
        self.db.execute("INSERT OR REPLACE INTO controls VALUES('emergency_stop',?)",("1" if active else "0",))
    def emergency_stop(self)->bool:
        row=self.db.execute("SELECT value FROM controls WHERE key='emergency_stop'").fetchone();return row is not None and row[0]=="1"
    def reserve(self,intent:dict[str,Any],*,created_utc:str,risk_pct:float,daily_loss_pct:float,drawdown_pct:float,open_positions:int,pending_orders:int,max_account_exposure:int=1)->str:
        if self.emergency_stop():raise IntentBlocked("Emergency stop is active")
        values=(risk_pct,daily_loss_pct,drawdown_pct)
        if any(isinstance(x,bool) or not math.isfinite(float(x)) for x in values):raise IntentBlocked("Risk state is invalid")
        if not 0<float(risk_pct)<=.25:raise IntentBlocked("Nominal risk exceeds 0.25%")
        if daily_loss_pct>=2 or drawdown_pct>=5:raise IntentBlocked("Daily loss or drawdown circuit breaker is active")
        if open_positions+pending_orders>=max_account_exposure:raise IntentBlocked("Account-wide exposure limit reached")
        if intent.get("side") not in {"buy","sell"} or intent.get("symbol")!="EURUSD":raise IntentBlocked("Unsupported intent")
        if not all(isinstance(intent.get(k),(int,float)) and math.isfinite(float(intent[k])) and float(intent[k])>0 for k in ("volume","sl","tp")):raise IntentBlocked("Protective stops and volume are required")
        intent_id=canonical_intent_id(intent);payload=json.dumps(intent,sort_keys=True,separators=(",",":"),allow_nan=False)
        try:self.db.execute("INSERT INTO intents(intent_id,binding_id,created_utc,payload,status) VALUES(?,?,?,?,?)",(intent_id,intent["binding_id"],created_utc,payload,"RESERVED"))
        except sqlite3.IntegrityError as error:raise IntentBlocked("Duplicate order intent") from error
        return intent_id
    def transition(self,intent_id:str,status:str,*,broker_order:int|None=None,broker_deal:int|None=None,note:str=""):
        if status not in UNRECONCILED|FINAL:raise ValueError("Unsupported journal state")
        row=self.db.execute("SELECT status FROM intents WHERE intent_id=?",(intent_id,)).fetchone()
        if row is None:raise IntentBlocked("Intent does not exist")
        if row[0] in FINAL:raise IntentBlocked("Final intent cannot transition")
        self.db.execute("UPDATE intents SET status=?,broker_order=?,broker_deal=?,note=? WHERE intent_id=?",(status,broker_order,broker_deal,note,intent_id))
    def unreconciled(self)->list[dict[str,Any]]:
        rows=self.db.execute("SELECT intent_id,binding_id,created_utc,status,broker_order,broker_deal,note FROM intents WHERE status NOT IN ('REJECTED','CANCELLED','CLOSED_RECONCILED') ORDER BY created_utc").fetchall()
        return [dict(zip(("intent_id","binding_id","created_utc","status","broker_order","broker_deal","note"),row)) for row in rows]
