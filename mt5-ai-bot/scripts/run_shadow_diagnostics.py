"""Poll the connected DEMO terminal and persist diagnostics for completed bars."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.monitoring.shadow_diagnostics import export, observe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--watch", action="store_true", help="Poll every 15 seconds until stopped")
    parser.add_argument("--export", action="store_true", help="Print the journal as JSON without MT5")
    args = parser.parse_args()
    if args.export:
        print(json.dumps(export(args.journal), indent=2))
        return
    if args.terminal is None:
        parser.error("--terminal is required for sampling")
    import MetaTrader5 as mt5

    if not mt5.initialize(str(args.terminal), timeout=5000):
        raise SystemExit("MT5 attachment failed")
    try:
        while True:
            print(json.dumps(observe(mt5, args.journal)), flush=True)
            if not args.watch:
                break
            time.sleep(15)
    except KeyboardInterrupt:
        pass
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
