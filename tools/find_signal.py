"""Rank CAN byte fields by how well they follow an expected step pattern.
usage: python -I find_signal.py <capture.csv> <template> [top_n]
template: comma list of start:end:level, e.g. "10:20:1,30:40:2" (everything else = 0)
"""
import csv, sys, math
from collections import defaultdict

path, tmpl = sys.argv[1], sys.argv[2]
top_n = int(sys.argv[3]) if len(sys.argv) > 3 else 15
segs = [tuple(float(x) for x in s.split(':')) for s in tmpl.split(',')]

def level(t):
    for a, b, l in segs:
        if a <= t < b:
            return l
    return 0.0

frames = defaultdict(list)  # id -> [(t, bytes)]
with open(path, newline='') as f:
    for row in csv.DictReader(f):
        d = row['data']
        if len(d) % 2:
            continue
        frames[row['id']].append((float(row['time_s']), bytes.fromhex(d)))

duration = max(t for v in frames.values() for t, _ in v)
nb = int(duration) + 1

def fields(n):
    for i in range(n):
        yield f'b{i}', lambda b, i=i: b[i]
    for i in range(n - 1):
        yield f'BE{i}-{i+1}', lambda b, i=i: (b[i] << 8) | b[i+1]
        yield f'LE{i}-{i+1}', lambda b, i=i: b[i] | (b[i+1] << 8)
    for i in range(n):  # 12-bit/13-bit style: low nibble/bits of b[i] + b[i+1]
        if i < n - 1:
            yield f'BE{i}lo4-{i+1}', lambda b, i=i: ((b[i] & 0x0F) << 8) | b[i+1]

def pearson(x, y):
    n = len(x); mx = sum(x)/n; my = sum(y)/n
    sx = math.sqrt(sum((a-mx)**2 for a in x)); sy = math.sqrt(sum((b-my)**2 for b in y))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((a-mx)*(b-my) for a, b in zip(x, y)) / (sx*sy)

results = []
for fid, lst in frames.items():
    n = min(len(b) for _, b in lst)
    if n == 0:
        continue
    for name, fn in fields(n):
        bins = defaultdict(list)
        for t, b in lst:
            bins[int(t)].append(fn(b))
        xs, ys = [], []
        for k in range(nb):
            if bins[k]:
                xs.append(sum(bins[k]) / len(bins[k])); ys.append(level(k + 0.5))
        if len(xs) < nb * 0.6 or max(xs) == min(xs):
            continue
        r = pearson(xs, ys)
        results.append((r, fid, name, xs))

results.sort(key=lambda r: -abs(r[0]))
seen = set()
shown = 0
for r, fid, name, xs in results:
    if (fid, name[:3]) in seen:
        continue
    seen.add((fid, name[:3]))
    print(f'r={r:+.3f}  0x{fid} {name:12s} min={min(xs):.0f} max={max(xs):.0f}')
    print('    1s means: ' + ' '.join(f'{v:.0f}' for v in xs))
    shown += 1
    if shown >= top_n:
        break
