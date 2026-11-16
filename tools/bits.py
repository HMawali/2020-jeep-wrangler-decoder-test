"""Find individual bits whose activity follows an on/off template.
usage: python -I bits.py capture.csv "10:20,30:40" [baseline_end=8] [top=25]
activity per second = fraction of frames where the bit differs from its baseline (first seconds) value.
"""
import csv, sys, math
from collections import defaultdict
path, tmpl = sys.argv[1], sys.argv[2]
base_end = float(sys.argv[3]) if len(sys.argv) > 3 else 8
top = int(sys.argv[4]) if len(sys.argv) > 4 else 25
wins = [tuple(map(float, w.split(':'))) for w in tmpl.split(',')]
on = lambda t: any(a <= t < b for a, b in wins)

frames = defaultdict(list)
for r in csv.DictReader(open(path, newline='')):
    d = r['data']
    if d and len(d) % 2 == 0:
        frames[r['id']].append((float(r['time_s']), bytes.fromhex(d)))
dur = int(max(t for v in frames.values() for t, _ in v)) + 1

def pearson(x, y):
    n = len(x); mx = sum(x)/n; my = sum(y)/n
    sx = math.sqrt(sum((a-mx)**2 for a in x)); sy = math.sqrt(sum((b-my)**2 for b in y))
    return 0.0 if sx == 0 or sy == 0 else sum((a-mx)*(b-my) for a, b in zip(x, y)) / (sx*sy)

res = []
for fid, lst in frames.items():
    nbytes = min(len(b) for _, b in lst)
    for byte in range(nbytes):
        for bit in range(8):
            vals = [(t, (b[byte] >> bit) & 1) for t, b in lst]
            base = [v for t, v in vals if t < base_end]
            if not base or len(set(base)) > 1:   # must be steady during baseline
                continue
            b0 = base[0]
            trans = sum(1 for k in range(1, len(vals)) if vals[k][1] != vals[k-1][1])
            if trans == 0:
                continue
            act = defaultdict(list)
            for t, v in vals:
                act[int(t)].append(v != b0)
            xs = [sum(act[k]) / len(act[k]) if act[k] else 0 for k in range(dur)]
            ys = [1.0 if on(k + 0.5) else 0.0 for k in range(dur)]
            r = pearson(xs, ys)
            res.append((r, fid, byte, bit, b0, trans, xs))
res.sort(key=lambda x: -x[0])
for r, fid, byte, bit, b0, trans, xs in res[:top]:
    kind = 'FLASHING' if trans > 6 else 'steady'
    print(f'r={r:+.2f} 0x{fid} byte{byte} bit{bit} (mask 0x{1<<bit:02X}) idle={b0} transitions={trans:4d} {kind}')
    print('    ' + ''.join('#' if x > 0.66 else ('+' if x > 0.2 else ('.' if x > 0 else '_')) for x in xs))
