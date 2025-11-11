#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from typing import Any, Dict

import requests
from dotenv import load_dotenv


def fetch_message(ip: str, timeout: float = 10.0, allow_empty: bool = False, verbose: bool = False) -> Dict[str, Any] | None:
    url = f"http://{ip}/messages"
    headers = {"Accept": "application/json", "X-Requested-With": "fetch"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if verbose:
            print(f"DEBUG http_status={resp.status_code}")
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        data = resp.json()
        if verbose:
            print(f"DEBUG body={data}")
        # Typical shape: {"freq": 38, "data": [...], "format": "us"}
        if not isinstance(data, dict):
            return None
        arr = data.get("data")
        if allow_empty:
            return data
        # Heuristic: data=[0] is often placeholder; require len>1 or sum>0
        if isinstance(arr, list) and (len(arr) > 1 or (len(arr) == 1 and arr[0] != 0)):
            return data
        return None
    except requests.exceptions.RequestException:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch newest received IR message from Nature Remo Local API (/messages)")
    parser.add_argument("--ip", help="Nature Remo local IP (e.g., 192.168.1.23). If omitted, REMO_IP env is used.")
    parser.add_argument("--wait", type=float, default=10.0, help="Max seconds to wait while polling for a message (default: 10s)")
    parser.add_argument("--interval", type=float, default=0.2, help="Polling interval seconds (default: 0.2s)")
    parser.add_argument("--save", help="Optional path to save JSON message")
    parser.add_argument("--watch", action="store_true", help="Watch mode: fetch every --interval seconds and print results continuously")
    parser.add_argument("--raw", action="store_true", help="Print raw /messages response even if it looks empty (data:[0])")
    args = parser.parse_args()
    verbose = bool(os.getenv("VERBOSE"))

    load_dotenv()
    ip = args.ip or os.getenv("REMO_IP") or os.getenv("NATURE_REMO_LOCAL_IP_ADDRESS")
    if not ip:
        print("Error: --ip or REMO_IP is required.", file=sys.stderr)
        return 2

    if args.watch:
        try:
            while True:
                msg = fetch_message(ip, timeout=max(1.0, args.interval), allow_empty=args.raw, verbose=verbose)
                if msg:
                    print(json.dumps({"ts": time.time(), "message": msg}, ensure_ascii=False))
                else:
                    print(json.dumps({"ts": time.time(), "message": None}))
                sys.stdout.flush()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0

    deadline = time.time() + args.wait
    msg = None
    while time.time() < deadline:
        msg = fetch_message(ip, allow_empty=args.raw, verbose=verbose)
        if msg:
            break
        time.sleep(args.interval)

    if not msg:
        print("No IR message received within the wait window. Try pressing the remote closer to the Remo and retry.")
        return 1

    print(json.dumps(msg, ensure_ascii=False, indent=2))

    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(msg, f, ensure_ascii=False, indent=2)
        print(f"Saved to {args.save}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
