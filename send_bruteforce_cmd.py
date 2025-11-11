#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

# Utilities reused from analysis

def parse_json_from_line(line: str) -> Optional[Dict[str, Any]]:
    s = line.strip()
    if not s or s.startswith('#') or s.startswith('//'):
        return None
    i = s.find('{')
    if i == -1:
        return None
    js = s[i:]
    try:
        return json.loads(js)
    except json.JSONDecodeError:
        j = js.rfind('}')
        if j != -1:
            try:
                return json.loads(js[:j+1])
            except Exception:
                return None
        return None


def estimate_unit_us_from_sample(sample_path: str) -> float:
    try:
        with open(sample_path, 'r', encoding='utf-8') as f:
            for line in f:
                js = parse_json_from_line(line)
                if not js:
                    continue
                arr = js.get('data')
                if isinstance(arr, list) and arr:
                    small = [abs(v) for v in arr if 0 < abs(v) < 800]
                    if not small:
                        small = [abs(v) for v in arr if abs(v) > 0]
                    if small:
                        return float(median(small))
    except FileNotFoundError:
        pass
    return 355.0  # reasonable default from earlier observations


def encode_aeha_bytes_to_us(data_bytes: List[int], unit_us: float) -> List[int]:
    # AEHA-like encoding: Leader 8T mark + 4T space. Then for each bit (LSB-first per byte):
    # mark 1T, then space 1T for 0 or 3T for 1. End with a final mark 1T.
    T = max(50.0, unit_us)
    seq: List[int] = []
    # Leader
    seq.append(int(round(8 * T)))
    seq.append(int(round(4 * T)))
    # Data bits
    for b in data_bytes:
        for i in range(8):
            bit = (b >> i) & 1
            seq.append(int(round(1 * T)))  # mark
            space = 3 * T if bit == 1 else 1 * T
            seq.append(int(round(space)))
    # Trailer mark (common in AEHA)
    seq.append(int(round(1 * T)))
    return seq


def post_local_message(ip: str, payload: Dict[str, Any], timeout: float = 5.0) -> Tuple[int, str]:
    url = f"http://{ip}/messages"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Requested-With": "fetch",
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    text = resp.text if resp.content else ''
    return resp.status_code, text


def main() -> int:
    ap = argparse.ArgumentParser(description="Bruteforce last byte XX with fixed cmd=0x02: send 8-byte AEHA-like frames via Local API /messages")
    ap.add_argument("--file", default="dump-results.txt", help="Sample file to estimate unit_us from (default: dump-results.txt)")
    ap.add_argument("--ip", help="Nature Remo local IP; fallback to env NATURE_REMO_LOCAL_IP_ADDRESS or REMO_IP")
    ap.add_argument("--sleep", type=float, default=2.0, help="Seconds to sleep between sends (default: 2.0)")
    ap.add_argument("--start", type=int, default=0, help="Start value of XX (0-255)")
    ap.add_argument("--end", type=int, default=255, help="End value of XX (0-255)")
    ap.add_argument("--freq", type=int, default=38, help="Carrier freq kHz (default: 38)")
    ap.add_argument("--verbose", action="store_true", help="Verbose output")
    args = ap.parse_args()

    load_dotenv()
    ip = args.ip or os.getenv("NATURE_REMO_LOCAL_IP_ADDRESS") or os.getenv("REMO_IP")
    if not ip:
        print("Error: --ip or NATURE_REMO_LOCAL_IP_ADDRESS/REMO_IP is required", file=sys.stderr)
        return 2

    unit = estimate_unit_us_from_sample(args.file)
    if args.verbose:
        print(f"Using unit_us ≈ {unit:.1f} from {args.file}")

    # Fixed header bytes from observed frames (LSB-first decoded)
    header = [0x23, 0xCB, 0x16, 0x44, 0x80, 0x89]
    cmd = 0x02  # as requested

    # Iterate XX in range
    for xx in range(max(0, args.start), min(255, args.end) + 1):
        bytes8 = header + [cmd, xx]
        us = encode_aeha_bytes_to_us(bytes8, unit)
        payload = {"format": "us", "freq": args.freq, "data": us}
        try:
            status, text = post_local_message(ip, payload)
        except requests.exceptions.RequestException as e:
            print(f"XX=0x{xx:02X}: request failed: {e}")
            time.sleep(args.sleep)
            continue
        print(f"XX=0x{xx:02X}: status={status}")
        if args.verbose and text:
            print(text)
        # Sleep between sends
        time.sleep(args.sleep)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
