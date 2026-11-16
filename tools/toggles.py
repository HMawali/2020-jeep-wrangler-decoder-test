"""List every bit that changes, with change count, per-second activity strip. usage: toggles.py capture.csv [max_trans=400]"""
import csv, sys
from collections import defaultdict
mx = int(sys.argv[2]) if len(sys.argv) > 2 else 400
frames = defaultdict(list)
for r in csv.DictReader(open(sys.argv[1], newline='')):
    d = r['data']
    if d and len(d) % 2 == 0:
        frames[r['id']].append((float(r['time_s']), bytes.fromhex(d)))
dur = int(max(t for v in frames.values() for t, _ in v)) + 1
out = []
for fid, lst in frames.items():
    n = min(len(b) for _, b in lst)
    hz = len(lst) / dur
    for byte in range(n):
        for bit in range(8):
            prev = None; changes = []
            for t, b in lst:
                v = (b[byte] >> bit) & 1
                if prev is not None and v != prev:
                    changes.append(t)
                prev = v
            if 1 <= len(changes) <= mx:
                strip = ['_'] * dur
                for t in changes:
                    strip[int(t)] = '|'
                out.append((fid, byte, bit, len(changes), hz, ''.join(strip)))
out.sort(key=lambda x: (x[0], x[1], x[2]))
for fid, byte, bit, c, hz, s in out:
    print(f'0x{fid} b{byte}.{bit} n={c:3d} ({hz:4.1f}Hz msg)  {s}')
