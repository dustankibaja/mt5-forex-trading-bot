"""Poll the connected DEMO terminal and persist diagnostics for completed bars."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.monitoring.shadow_diagnostics import ProspectiveJournal, export_forward
from src.monitoring.forward_audit import audit_forward


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--watch", action="store_true", help="Poll every 15 seconds until stopped")
    read = parser.add_mutually_exclusive_group()
    read.add_argument("--export", action="store_true", help="Print the journal without MT5")
    read.add_argument("--audit", action="store_true", help="Check journal integrity and rollover decisions")
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    args = parser.parse_args()
    if args.audit:
        result = audit_forward(args.journal)
        print(json.dumps(result, indent=2))
        return 0 if result["integrity_ok"] and result["source_bound"] and not result["issues"] else 1
    if args.export:
        data = export_forward(args.journal)
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            rows = data["forward"]
            fields = sorted({key for row in rows for key in row})
            if fields:
                writer = csv.DictWriter(sys.stdout, fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows({key: json.dumps(value) if isinstance(value, dict) else value
                                  for key, value in row.items()} for row in rows)
        return
    if args.terminal is None:
        parser.error("--terminal is required for sampling")
    import MetaTrader5 as mt5

    if not mt5.initialize(str(args.terminal), timeout=5000):
        raise SystemExit("MT5 attachment failed")
    journal = ProspectiveJournal(args.journal)
    try:
        while True:
            print(json.dumps(journal.poll(mt5)), flush=True)
            if not args.watch:
                break
            time.sleep(15)
    except KeyboardInterrupt:
        pass
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
