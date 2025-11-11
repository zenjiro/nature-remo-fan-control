import os
import sys
import argparse
import requests
from typing import Optional, Dict, Any, List

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    def load_dotenv() -> None:
        return None

BASE = "https://api.nature.global/1"


def get_token() -> str:
    load_dotenv()
    token = os.getenv("NATURE_REMO_TOKEN")
    if not token:
        print("Error: environment variable NATURE_REMO_TOKEN is not set. Put your token into .env or export it.", file=sys.stderr)
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
    if resp.text:
        try:
            return resp.json()
        except Exception:
            return resp.text
    return {}


def list_signals(token: str) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    appliances = api_get("/appliances", token)
    for ap in appliances:
        ap_id = ap.get("id")
        try:
            sigs = api_get(f"/appliances/{ap_id}/signals", token)
        except requests.HTTPError as e:
            # Some appliance types may not support signals endpoint
            print(f"warn: failed to list signals for appliance {ap_id}: {e}", file=sys.stderr)
            continue
        if isinstance(sigs, list):
            for s in sigs:
                s["_appliance"] = {"id": ap_id, "nickname": ap.get("nickname"), "type": ap.get("type")}
            signals.extend(sigs)
    return signals


def find_signal_by_name(signals: List[Dict[str, Any]], name_query: str) -> Optional[Dict[str, Any]]:
    # First, exact match (case-sensitive), then case-insensitive, then substring contains
    for s in signals:
        if s.get("name") == name_query:
            return s
    low = name_query.lower()
    for s in signals:
        if str(s.get("name", "")).lower() == low:
            return s
    for s in signals:
        if low in str(s.get("name", "")).lower():
            return s
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a Nature Remo Cloud API signal by name or id.")
    g = parser.add_mutually_exclusive_group(required=False)
    g.add_argument("--name", help="Signal name to match (exact or partial)")
    g.add_argument("--id", help="Signal ID to send directly")
    parser.add_argument("--dry-run", action="store_true", help="Only print which signal would be sent")
    parser.add_argument("--prefer", nargs="*", default=["首振り左右", "首振り", "swing", "oscillate"], help="Preferred names to try in order when --name is omitted")

    args = parser.parse_args()
    token = get_token()

    if args.id:
        sig_id = args.id
        if args.dry_run:
            print(f"[dry-run] would send signal id={sig_id}")
            return
        api_post(f"/signals/{sig_id}/send", token)
        print(f"sent signal id={sig_id}")
        return

    # Resolve by name
    signals = list_signals(token)
    if not signals:
        print("No signals found in your account.")
        sys.exit(1)

    name_to_search: Optional[str] = args.name
    if not name_to_search:
        # Try preferred names in order
        for cand in args.prefer:
            hit = find_signal_by_name(signals, cand)
            if hit:
                name_to_search = cand
                signal = hit
                break
        else:
            print("No matching signal by preferred names. Use --name or --id.")
            # Print a quick list
            print("Available signals:")
            for s in signals:
                ap = s.get("_appliance", {})
                print(f"- {s.get('name')} (id={s.get('id')}) appliance={ap.get('nickname') or ap.get('type')}")
            sys.exit(2)
    else:
        signal = find_signal_by_name(signals, name_to_search)
        if not signal:
            print(f"Signal not found by name: {name_to_search}")
            print("Available signals:")
            for s in signals:
                ap = s.get("_appliance", {})
                print(f"- {s.get('name')} (id={s.get('id')}) appliance={ap.get('nickname') or ap.get('type')}")
            sys.exit(3)

    sig_id = signal.get("id")
    ap = signal.get("_appliance", {})
    print(f"Resolved signal: name={signal.get('name')} id={sig_id} appliance={ap.get('nickname') or ap.get('type')}")

    if args.dry_run:
        print("[dry-run] would send the signal (skipped)")
        return

    api_post(f"/signals/{sig_id}/send", token)
    print("sent.")


if __name__ == "__main__":
    main()
