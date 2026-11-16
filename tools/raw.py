import csv, sys
path, ids, step = sys.argv[1], sys.argv[2].split(','), int(sys.argv[3])
seen = {}
for r in csv.DictReader(open(path, newline='')):
    t = int(float(r['time_s']))
    if r['id'] in ids and t % step == 0 and (r['id'], t) not in seen:
        seen[(r['id'], t)] = r['data']
end = max(t for _, t in seen)
for t in range(0, end + 1, step):
    print(f'{t:3d}s  ' + '  '.join(f"{i}={seen.get((i, t), ''):16s}" for i in ids))
