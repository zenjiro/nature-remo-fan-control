#!/usr/bin/env python3
import argparse
import json
from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

# Reuse decoding logic (AEHA-like) similar to analyze_ir_dump.py

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


def estimate_unit_us(data: List[int]) -> float:
    small = [abs(v) for v in data if 0 < abs(v) < 800]
    if not small:
        small = [abs(v) for v in data if abs(v) > 0]
    return median(small) if small else 425.0


def decode_bits_aeha(data: List[int], unit_us: float) -> str:
    arr = [abs(x) for x in data if x != 0]
    if len(arr) < 4:
        return ''
    def near(x, target, tol=0.6):
        return abs(x - target) <= tol * target
    start = 0
    if len(arr) >= 2:
        m0, s0 = arr[0], arr[1]
        if near(m0, 8*unit_us) and near(s0, 4*unit_us):
            start = 2
        else:
            start = 2
    bits: List[str] = []
    i = start
    while i + 1 < len(arr):
        mark, space = arr[i], arr[i+1]
        i += 2
        r_space = space / unit_us if unit_us > 0 else 0
        bit = '1' if abs(r_space - 3.0) < abs(r_space - 1.0) else '0'
        bits.append(bit)
    return ''.join(bits)


def bits_to_bytes_lsb_first(bits: str) -> List[int]:
    out: List[int] = []
    for i in range(0, len(bits), 8):
        seg = bits[i:i+8]
        if len(seg) < 8:
            break
        val = 0
        for b_i, b in enumerate(seg):
            if b == '1':
                val |= (1 << b_i)
        out.append(val)
    return out


def load_bytes(path: str) -> List[Tuple[int, List[int]]]:
    res: List[Tuple[int, List[int]]] = []
    with open(path, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f, start=1):
            js = parse_json_from_line(line)
            if not js:
                continue
            data = js.get('data')
            if not isinstance(data, list) or len(data) < 2:
                continue
            unit = estimate_unit_us(data)
            bits = decode_bits_aeha(data, unit)
            by = bits_to_bytes_lsb_first(bits)
            if len(by) >= 8:
                res.append((idx, by[:8]))
    return res


def checksum_candidates(samples: List[List[int]]) -> List[str]:
    # samples are 8-byte arrays; last byte is checksum target
    # We try multiple families and collect formulas that satisfy all samples
    cands: List[str] = []

    def ok_all(fn) -> bool:
        for b in samples:
            want = b[7]
            try:
                got = fn(b)
            except Exception:
                return False
            if (got & 0xFF) != want:
                return False
        return True

    # Helper: iterate over subsets of indices 0..6
    idxs = list(range(7))
    subsets: List[List[int]] = []
    for mask in range(1, 1 << 7):  # non-empty subsets
        s = [i for i in idxs if (mask >> i) & 1]
        subsets.append(s)

    # 1) Simple sum-based
    for S in subsets:
        def make_sum_fn(S=S):
            return lambda b: sum(b[i] for i in S) & 0xFF
        def make_neg_sum_fn(S=S):
            return lambda b: (-sum(b[i] for i in S)) & 0xFF
        def make_ones_sum_fn(S=S):
            return lambda b: (~sum(b[i] for i in S)) & 0xFF
        fn1, fn2, fn3 = make_sum_fn(), make_neg_sum_fn(), make_ones_sum_fn()
        if ok_all(fn1): cands.append(f"sum(S={S}) mod 256")
        if ok_all(fn2): cands.append(f"(-sum(S={S})) mod 256 (two's complement)")
        if ok_all(fn3): cands.append(f"~sum(S={S}) & 0xFF")

    # 2) XOR-based
    for S in subsets:
        def make_xor_fn(S=S):
            return lambda b: _xor([b[i] for i in S])
        def make_nxor_fn(S=S):
            return lambda b: (~_xor([b[i] for i in S])) & 0xFF
        fn1, fn2 = make_xor_fn(), make_nxor_fn()
        if ok_all(fn1): cands.append(f"xor(S={S})")
        if ok_all(fn2): cands.append(f"~xor(S={S}) & 0xFF")

    # 3) Linear with command weight: cs = (sum(S) + k*cmd + c) mod 256
    # cmd is byte[6]
    for S in subsets:
        for k in range(0, 16):
            # Determine c from first sample, then verify all
            def make_lin_fn(S=S, k=k, c=None):
                return lambda b: (sum(b[i] for i in S) + k*b[6] + (0 if c is None else c)) & 0xFF
            # derive c from first sample
            b0 = samples[0]
            base0 = (sum(b0[i] for i in S) + k*b0[6]) & 0xFF
            c = (b0[7] - base0) & 0xFF
            fn = make_lin_fn(c=c)
            if ok_all(fn):
                cands.append(f"(sum(S={S}) + {k}*cmd + {c}) mod 256")

    return cands


def _xor(arr: List[int]) -> int:
    v = 0
    for x in arr:
        v ^= x
    return v & 0xFF


def main() -> int:
    ap = argparse.ArgumentParser(description='Search checksum rule candidates matching decoded 8-byte messages')
    ap.add_argument('file', help='dump-results.txt')
    ap.add_argument('--group1', default='2-5', help='lines for group1 (1-based inclusive), e.g., 2-5')
    ap.add_argument('--group2', default='7-10', help='lines for group2 (1-based inclusive), e.g., 7-10')
    args = ap.parse_args()

    pairs = load_bytes(args.file)
    if not pairs:
        print('No decodable 8-byte messages found.')
        return 1

    # Map by original line index
    by_line = {ln: by for ln, by in pairs}

    def parse_range(r: str) -> Tuple[int,int]:
        a,b = r.split('-')
        return int(a), int(b)

    def collect(rr: Tuple[int,int]) -> List[List[int]]:
        s,e = rr
        out: List[List[int]] = []
        for i in range(s, e+1):
            if i in by_line:
                out.append(by_line[i])
        return out

    g1 = collect(parse_range(args.group1))
    g2 = collect(parse_range(args.group2))

    # Print representatives
    if g1:
        print('Group1 rep bytes:', g1[0])
    if g2:
        print('Group2 rep bytes:', g2[0])

    # Aggregate all samples
    samples = g1 + g2 if g1 and g2 else (g1 or g2)
    if not samples:
        print('No samples in specified ranges.')
        return 1

    cands = checksum_candidates(samples)
    print(f'Found {len(cands)} candidate checksum rules that match all samples:')
    for s in cands[:50]:
        print(' -', s)
    if len(cands) > 50:
        print(f' ... and {len(cands)-50} more')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
