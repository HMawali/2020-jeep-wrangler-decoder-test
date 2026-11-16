"""Print every change of selected bits. usage: bit_timeline.py capture.csv ID:byte:bit [...]"""
import csv, sys
specs = [(s.split(':')[0], int(s.split(':')[1]), int(s.split(':')[2])) for s in sys.argv[2:]]
last = {}
for r in csv.DictReader(open(sys.argv[1], newline='')):
    for fid, byte, bit in specs:
        if r['id'] != fid or len(r['data']) < 2 * (byte + 1):
            continue
        v = (int(r['data'][2*byte:2*byte+2], 16) >> bit) & 1
        k = (fid, byte, bit)
        if last.get(k) != v:
            print(f"{float(r['time_s']):7.2f}s  0x{fid} b{byte}.{bit} -> {v}   data={r['data']}")
            last[k] = v
