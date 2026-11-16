import csv, sys, statistics as st
from collections import defaultdict
w = [defaultdict(list) for _ in range(4)]; v = defaultdict(list); g = {}; rpm = defaultdict(list)
GEAR = {0x11: '1', 0x22: '2', 0x33: '3', 0x44: '4', 0x55: '5', 0x66: '6', 0x77: '7', 0x88: '8', 0xDD: 'P'}
for r in csv.DictReader(open(sys.argv[1], newline='')):
    t = int(float(r['time_s'])); d = bytes.fromhex(r['data'])
    if r['id'] == '08B':
        for i in range(4):
            w[i][t].append(((d[2*i] << 8) | d[2*i+1]) & 0x0FFF)
    elif r['id'] == '085':
        v[t].append((d[3] << 8) | d[4]); g[t] = GEAR.get(d[1], f'{d[1]:02X}')
    elif r['id'] == '025':
        rpm[t].append((d[0] << 8) | d[1])
print('sec  FL?   FR?   RL?   RR?  (0x08B raw)   0x085 b3-4   gear  rpm')
for t in sorted(v):
    ws = ' '.join(f'{st.mean(w[i][t]):5.0f}' if w[i][t] else '    -' for i in range(4))
    print(f'{t:3d}  {ws}       {st.mean(v[t]):6.0f}       {g[t]:>3}  {st.mean(rpm[t]):5.0f}')
