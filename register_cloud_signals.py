#!/usr/bin/env python3
import argparse
import json
import os
import sys
from statistics import median
from typing import Any, Dict, List, Optional

import requests

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    def load_dotenv() -> None:
        return None

BASE = "https://api.nature.global/1"


def get_token() -> str:
    load_dotenv()
    token = os.getenv("NATURE_REMO_TOKEN") or os.getenv("NATURE_REMO_API_TOKEN")
    if not token:
        print("Error: NATURE_REMO_TOKEN (or NATURE_REMO_API_TOKEN) is required.", file=sys.stderr)
        sys.exit(1)
    return token


def api_get(path: str, token: str) -> Any:
    resp = requests.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def api_post(path: str, token: str, json_body: Optional[Dict[str, Any]] = None) -> Any:
    resp = requests.post(
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=json_body,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json() if resp.text else {}


def parse_json_from_line(line: str) -> Optional[Dict[str, Any]]:
    s = line.strip()
    if not s or s.startswith("#") or s.startswith("//"):
        return None
    i = s.find("{")
    if i == -1:
        return None
    js = s[i:]
    try:
        return json.loads(js)
    except json.JSONDecodeError:
        j = js.rfind("}")
        if j != -1:
            try:
                return json.loads(js[: j + 1])
            except Exception:
                return None
        return None


def estimate_unit_us_from_sample(sample_path: str) -> float:
    try:
        with open(sample_path, "r", encoding="utf-8") as f:
            for line in f:
                js = parse_json_from_line(line)
                if not js:
                    continue
                arr = js.get("data")
                if isinstance(arr, list) and arr:
                    small = [abs(v) for v in arr if 0 < abs(v) < 800]
                    if not small:
                        small = [abs(v) for v in arr if abs(v) > 0]
                    if small:
                        return float(median(small))
    except FileNotFoundError:
        pass
    return 355.0


def encode_aeha_bytes_to_us(data_bytes: List[int], unit_us: float) -> List[int]:
    # AEHA-like encoding: Leader 8T mark + 4T space. Then for each bit (LSB-first per byte):
    # mark 1T, then space 1T for 0 or 3T for 1. End with a final mark 1T.
    T = max(50.0, unit_us)
    seq: List[int] = []
    seq.append(int(round(8 * T)))
    seq.append(int(round(4 * T)))
    for b in data_bytes:
        for i in range(8):
            bit = (b >> i) & 1
            seq.append(int(round(1 * T)))
            space = 3 * T if bit == 1 else 1 * T
            seq.append(int(round(space)))
    seq.append(int(round(1 * T)))
    return seq


def find_device(devices: List[Dict[str, Any]], name_query: Optional[str]) -> Optional[Dict[str, Any]]:
    if not devices:
        return None
    if not name_query:
        return devices[0]
    for d in devices:
        if d.get("name") == name_query:
            return d
    low = name_query.lower()
    for d in devices:
        if str(d.get("name", "")).lower() == low:
            return d
    for d in devices:
        if low in str(d.get("name", "")).lower():
            return d
    return None


def find_appliance(appliances: List[Dict[str, Any]], nickname: str) -> Optional[Dict[str, Any]]:
    for a in appliances:
        if a.get("nickname") == nickname:
            return a
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Register IR signals for a new fan appliance via Nature Remo Cloud API.")
    parser.add_argument("--appliance-name", default="黒い扇風機", help="Appliance nickname to create/use.")
    parser.add_argument("--device-name", help="Optional device name to select from /devices.")
    parser.add_argument("--file", default="dump-results.txt", help="Sample file to estimate unit_us from.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without POSTing.")
    args = parser.parse_args()

    token = get_token()
    devices = api_get("/devices", token)
    device = find_device(devices, args.device_name)
    if not device:
        print("Error: device not found.", file=sys.stderr)
        return 2
    device_id = device.get("id")
    device_name = device.get("name")

    appliances = api_get("/appliances", token)
    ap = find_appliance(appliances, args.appliance_name)
    if ap:
        ap_id = ap.get("id")
        print(f"Using existing appliance: {args.appliance_name} (id={ap_id})")
    else:
        payload = {"device": device_id, "model": "IR", "nickname": args.appliance_name}
        if args.dry_run:
            print(f"[dry-run] would create appliance: {payload}")
            ap = {"id": "<dry-run-appliance-id>"}
        else:
            ap = api_post("/appliances", token, payload)
        ap_id = ap.get("id")
        print(f"Created appliance: {args.appliance_name} (id={ap_id}) on device={device_name}")

    existing = []
    if ap_id and ap_id != "<dry-run-appliance-id>":
        try:
            existing = api_get(f"/appliances/{ap_id}/signals", token)
        except requests.HTTPError as e:
            print(f"warn: failed to list signals for appliance {ap_id}: {e}", file=sys.stderr)

    existing_names = {str(s.get("name")) for s in existing if isinstance(s, dict)}

    unit = estimate_unit_us_from_sample(args.file)
    header = [0x23, 0xCB, 0x16, 0x44, 0x80, 0x89]
    table = [
        (0x01, 0x90, "電源"),
        (0x02, 0xA0, "風量"),
        (0x03, 0xB0, "首振り"),
        (0x04, 0xC0, "オフタイマー"),
        (0x0A, 0x20, "オンタイマー"),
    ]

    for cmd, xx, name in table:
        if name in existing_names:
            print(f"skip: signal already exists: {name}")
            continue
        data_bytes = header + [cmd, xx]
        payload = {
            "name": name,
            "message": json.dumps(
                {"format": "us", "freq": 38, "data": encode_aeha_bytes_to_us(data_bytes, unit)},
                separators=(",", ":"),
            ),
        }
        if args.dry_run:
            print(f"[dry-run] would register signal: {name} cmd=0x{cmd:02X} xx=0x{xx:02X}")
            continue
        created = api_post(f"/appliances/{ap_id}/signals", token, payload)
        print(f"created signal: {created.get('name')} id={created.get('id')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
