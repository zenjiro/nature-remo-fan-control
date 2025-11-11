#!/usr/bin/env python3
import argparse
import json
import math
from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class IRMessage:
    index: int
    raw: Dict[str, Any]
    bits: str
    unit_us: float


def parse_json_from_line(line: str) -> Optional[Dict[str, Any]]:
    s = line.strip()
    if not s or s.startswith('#') or s.startswith('//'):
        return None
    # find first {
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


def estimate_unit_us(data: List[int]) -> float:
    # Marks are typically around 350-450us; spaces have 1T (~425) or 3T (~1275)
    # Use small absolute values to estimate base unit T.
    small = [abs(v) for v in data if abs(v) > 0 and abs(v) < 800]
    if not small:
        # fallback from all
        small = [abs(v) for v in data if abs(v) > 0]
    if not small:
        return 425.0
    return median(small)


def decode_bits_aeha(data: List[int], unit_us: float) -> str:
    # AEHA: Leader ~ 8T mark + 4T space. Then bits: 1T mark + (1T space=0, 3T space=1)
    # data is [mark, space, mark, space, ...] in us. We'll skip leader by pattern length.
    arr = [abs(x) for x in data if x != 0]
    if len(arr) < 4:
        return ''
    # Find leader by first two entries
    # Try to verify first mark ~8T and space ~4T, otherwise just start after first pair.
    def near(x, target, tol=0.5):
        return abs(x - target) <= tol * target

    start = 0
    if len(arr) >= 2:
        m0, s0 = arr[0], arr[1]
        if near(m0, 8*unit_us, 0.6) and near(s0, 4*unit_us, 0.6):
            start = 2
        else:
            # Some messages may start right away; still skip first pair as leader-ish
            start = 2
    bits: List[str] = []
    # Iterate over pairs mark, space
    i = start
    while i + 1 < len(arr):
        mark, space = arr[i], arr[i+1]
        i += 2
        # Expect mark ~1T; if not, try to map to multiples of T and continue
        # Determine bit by space length: near 1T -> 0, near 3T -> 1
        r_space = space / unit_us if unit_us > 0 else 0
        # choose nearest: 1 or 3
        bit = '1' if abs(r_space - 3.0) < abs(r_space - 1.0) else '0'
        bits.append(bit)
        # Optional: termination check could be based on trailing mark without space; ignore
    return ''.join(bits)


def bits_to_bytes_lsb_first(bits: str) -> List[int]:
    # AEHA sends LSB first per byte. We'll pack every 8 bits into a byte with first bit as LSB.
    bytes_out: List[int] = []
    for i in range(0, len(bits), 8):
        seg = bits[i:i+8]
        if len(seg) < 8:
            break
        val = 0
        for bit_index, b in enumerate(seg):
            if b == '1':
                val |= (1 << bit_index)
        bytes_out.append(val)
    return bytes_out


def load_messages(path: str) -> List[IRMessage]:
    messages: List[IRMessage] = []
    with open(path, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f):
            js = parse_json_from_line(line)
            if not js:
                continue
            data = js.get('data')
            if not isinstance(data, list) or len(data) < 2:
                continue
            unit = estimate_unit_us(data)
            bits = decode_bits_aeha(data, unit)
            messages.append(IRMessage(index=idx, raw=js, bits=bits, unit_us=unit))
    return messages


def hamming_distance(a: str, b: str) -> int:
    n = min(len(a), len(b))
    return sum(1 for i in range(n) if a[i] != b[i]) + abs(len(a) - len(b))


def main() -> int:
    ap = argparse.ArgumentParser(description='Analyze IR dump: decode AEHA-like bits and compare groups')
    ap.add_argument('file', help='dump-results.txt')
    ap.add_argument('--group1', default='2-5', help='Range (1-based inclusive) for group1, e.g., 2-5 (oscillate)')
    ap.add_argument('--group2', default='7-10', help='Range (1-based inclusive) for group2, e.g., 7-10 (off-timer)')
    args = ap.parse_args()

    msgs = load_messages(args.file)
    if not msgs:
        print('No messages parsed. Ensure the file has JSON lines.')
        return 1

    def parse_range(r: str) -> Tuple[int,int]:
        a,b = r.split('-')
        return int(a), int(b)

    g1s, g1e = parse_range(args.group1)
    g2s, g2e = parse_range(args.group2)

    # Build mapping from original 1-based line index to message
    by_line = {m.index+1: m for m in msgs}

    def collect(r: Tuple[int,int]) -> List[Tuple[int, IRMessage]]:
        s,e = r
        out = []
        for i in range(s, e+1):
            m = by_line.get(i)
            if m:
                out.append((i, m))
        return out

    g1 = collect((g1s, g1e))
    g2 = collect((g2s, g2e))

    def summarize(label: str, group: List[Tuple[int, IRMessage]]):
        print(f'=== {label} ({len(group)} lines) ===')
        for line_no, m in group:
            b = m.bits
            bytes_lsb = bits_to_bytes_lsb_first(b)
            print(f'- line {line_no}: unit~{m.unit_us:.0f}us, bits_len={len(b)}, bytes(L little)=', bytes_lsb[:8])
        # Choose first as representative and compute Hamming distances
        if group:
            rep = group[0][1].bits
            print('Hamming to first:')
            for line_no, m in group:
                print(f'  line {line_no}: {hamming_distance(rep, m.bits)}')

    summarize('Group1 (oscillate)', g1)
    summarize('Group2 (off-timer)', g2)

    # Cross-group distance
    if g1 and g2:
        b1 = g1[0][1].bits
        b2 = g2[0][1].bits
        print('=== Cross-group comparison ===')
        print('Hamming(group1.first, group2.first)=', hamming_distance(b1, b2))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
