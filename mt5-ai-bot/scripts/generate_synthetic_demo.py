"""Generate clearly labelled deterministic demo candles; never historical data."""
from __future__ import annotations
import csv,math,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path

def main()->int:
    path=Path(sys.argv[1]);path.parent.mkdir(parents=True,exist_ok=True)
    stamp=datetime(2025,1,6,tzinfo=timezone.utc);rows=[];i=0
    while len(rows)<360:
        if stamp.weekday()<5:
            mid=1.10+.004*math.sin(i/13)+.002*math.sin(i/4.7);close=mid+.0005*math.sin(i/2.9);spread=.00018+.00004*(1+math.sin(i/7))/2
            high=max(mid,close)+.0007;low=min(mid,close)-.0007
            rows.append([stamp.isoformat().replace('+00:00','Z'),mid-spread/2,high-spread/2,low-spread/2,close-spread/2,mid+spread/2,high+spread/2,low+spread/2,close+spread/2]);i+=1
        stamp+=timedelta(hours=1)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(('timestamp','bid_open','bid_high','bid_low','bid_close','ask_open','ask_high','ask_low','ask_close'));w.writerows(rows)
    return 0
if __name__=='__main__':raise SystemExit(main())
