"""Rank fields that are steady at idle (0-28s) but move a lot later, and are smooth (not counters/checksums).
usage: python -I active.py capture.csv [idle_end] [top_n]"""
import csv, sys, statistics as st
from collections import defaultdict
path = sys.argv[1]; idle_end = float(sys.argv[2]) if len(sys.argv) > 2 else 28; top = int(sys.argv[3]) if len(sys.argv) > 3 else 25
frames = defaultdict(list)
with open(path, newline='') as f:
    for r in csv.DictReader(f):
        if len(r['data']) % 2 == 0 and r['data']:
            frames[r['id']].append((float(r['time_s']), bytes.fromhex(r['data'])))
out = []
for fid, lst in frames.items():
    n = min(len(b) for _, b in lst)
    cands = [(f'BE{i}-{i+1}', lambda b, i=i: (b[i] << 8) | b[i+1]) for i in range(n-1)]
    cands += [(f'BE{i}lo4-{i+1}', lambda b, i=i: ((b[i] & 15) << 8) | b[i+1]) for i in range(n-1)]
    cands += [(f'b{i}', lambda b, i=i: b[i]) for i in range(n)]
    for name, fn in cands:
        vals = [(t, fn(b)) for t, b in lst]
        idle = [v for t, v in vals if t < idle_end]
        act = [v for t, v in vals if t >= idle_end]
        if len(idle) < 10 or len(act) < 10:
            continue
        si = st.pstdev(idle) + 1; rng = max(act) - min(act)
        if rng == 0:
            continue
        # smoothness: mean abs step between consecutive frames relative to range
        steps = [abs(vals[k+1][1] - vals[k][1]) for k in range(len(vals)-1)]
        jitter = st.mean(steps) / rng
        if jitter > 0.05:
            continue
        score = rng / si
        bins = defaultdict(list)
        for t, v in vals:
            bins[int(t)].append(v)
        series = [round(st.mean(bins[k])) if bins[k] else -1 for k in range(int(vals[-1][0]) + 1)]
        out.append((score, fid, name, st.mean(idle), min(act), max(act), jitter, series))
out.sort(key=lambda x: -x[0])
for s, fid, name, mi, lo, hi, j, ser in out[:top]:
    print(f'score={s:8.1f} 0x{fid} {name:10s} idle~{mi:.0f} active {lo}..{hi} jitter={j:.4f}')
    print('    ' + ' '.join(map(str, ser)))
