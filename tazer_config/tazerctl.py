#!/usr/bin/env python3
"""
tazerctl.py - read-only CAN/UDS tool for Jeep JL body configuration.

Runs on the Windows laptop (COM3) and on macOS/Linux. Zero dependencies.
Every command is non-destructive: listen, benign probe, or READ config DIDs.
No 2E writes, no SecurityAccess, no clears. (See HANDOFF.md for why.)

USAGE
  python -I tazerctl.py ports
  python -I tazerctl.py sniff    --port COM3 [--bus s4|s6] [--seconds 5]
  python -I tazerctl.py discover --port COM3 [--bus s4|s6] [--start 0x600] [--end 0x7FF]
  python -I tazerctl.py read     --port COM3 [--bus s4|s6] [--tx 0x620] [--rx 0xNNN] [--save out.json]
  python -I tazerctl.py diff     before.json after.json        # label-discovery helper

BUS: s4 = 125k CAN-IHS (pins 3/11, body) [default]   s6 = 500k CAN-C (pins 6/14)
Vehicle PARKED, key in RUN, SGW bypass installed.
"""
import argparse, json, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # work under `python -I`
from canlink import SlcanLink, CanFrame, S_125K, S_500K, BUS_LABEL, list_ports
from uds import UdsClient, nrc_name
import did_catalog

def bus_of(s):
    return S_500K if (s or '').lower() == 's6' else S_125K

def pick_port(p):
    if p: return p
    cands = list_ports()
    if len(cands) == 1: return cands[0]
    sys.exit('need --port. candidates: ' + (', '.join(cands) if cands else 'none found'))

def cmd_ports(a):
    c = list_ports()
    print('Candidate ports:\n  ' + '\n  '.join(c) if c else 'No serial ports found.')

def cmd_sniff(a):
    port = pick_port(a.port); bus = bus_of(a.bus)
    link = SlcanLink(port); link.open(bus, listen_only=True)      # silent: cannot disturb bus
    print(f'# listening {a.seconds}s on {BUS_LABEL[bus]} (silent mode)…')
    frames = link.collect(a.seconds); link.close()
    by = {}
    for f in frames: by[f.id] = by.get(f.id, 0) + 1
    print(f'# {len(frames)} frames, {len(by)} unique IDs')
    for cid in sorted(by): print('  0x%03X  x%d' % (cid, by[cid]))

def cmd_discover(a):
    port = pick_port(a.port); bus = bus_of(a.bus)
    start = int(a.start, 16) if isinstance(a.start, str) else a.start
    end = int(a.end, 16) if isinstance(a.end, str) else a.end
    link = SlcanLink(port); link.open(bus, listen_only=False)
    print(f'# discover on {BUS_LABEL[bus]}: req IDs 0x{start:03X}-0x{end:03X}')
    print('# learning broadcast IDs for 3s (stay quiet)…')
    baseline = {f.id for f in link.collect(3.0)}
    print(f'#   {len(baseline)} broadcast IDs ignored'); link.drain()
    found = 0
    for rid in range(start, end + 1):
        link.transmit(CanFrame(rid, bytes([0x02, 0x3E, 0x00, 0, 0, 0, 0, 0])))
        for f in link.collect(0.04):
            if f.id in baseline or not f.data: continue
            pci = f.data[0] >> 4
            looks = (pci == 0 and len(f.data) >= 2 and (f.data[1] == 0x7F or (f.data[1] & 0x40))) or pci == 1
            if looks:
                found += 1
                print('  req 0x%03X -> resp 0x%03X: %s' % (rid, f.id, f.hex))
    link.close()
    print(f'# done. {found} candidate responder frame(s).')
    if not found:
        print('# No UDS responders. If 0x600-0x7FF is silent too, BCM diag is gatewayed (SGW).')

def cmd_read(a):
    port = pick_port(a.port); bus = bus_of(a.bus)
    tx = int(a.tx, 16) if isinstance(a.tx, str) else a.tx
    rx = (int(a.rx, 16) if isinstance(a.rx, str) else a.rx) if a.rx is not None else None
    cat = did_catalog.load()
    if tx is None: tx = cat.bcm_request_id
    link = SlcanLink(port); link.open(bus, listen_only=False)
    uds = UdsClient(link)
    print(f'# reading config from module 0x{tx:03X} on {BUS_LABEL[bus]}')
    ignore = {f.id for f in link.collect(2.0)}; link.drain()
    try:
        s = uds.diagnostic_session(0x03, tx, rx)
        status = ('DENIED (%s)' % nrc_name(s.nrc)) if (s and s.is_negative) else (('OK ' + s.hex) if s else 'no response')
    except Exception as e:
        status = f'error: {e}'
    print(f'# session 0x10 03 -> {status}')
    uds.tester_present(tx)
    results = {}; ok = 0
    for did in cat.all_dids:
        try:
            r = uds.read_did(did, tx, rx, ignore=ignore)
        except Exception:
            r = None
        if r is None:
            print('  DID 0x%04X: — no response' % did); results['0x%04X' % did] = None; continue
        if r.is_negative:
            print('  DID 0x%04X: — NRC 0x%02X (%s)' % (did, r.nrc, nrc_name(r.nrc)))
            results['0x%04X' % did] = {'nrc': r.nrc}; continue
        if len(r.data) >= 3 and r.data[0] == 0x62:
            payload = r.data[3:]
            ok += 1
            print('  DID 0x%04X: %s' % (did, payload.hex(' ').upper() or '(empty)'))
            results['0x%04X' % did] = payload.hex().upper()
        else:
            print('  DID 0x%04X: ? %s' % (did, r.hex)); results['0x%04X' % did] = {'raw': r.hex}
    link.close()
    print(f'# {ok}/{len(cat.all_dids)} DIDs read.')
    if not ok:
        print('# Nothing answered. Try --bus s6, another --tx, or confirm SGW bypass + key RUN.')
    if a.save:
        json.dump({'module': '0x%03X' % tx, 'bus': bus, 'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                   'dids': results}, open(a.save, 'w'), indent=2)
        print(f'# saved -> {a.save}')

def cmd_diff(a):
    """Compare two saved reads; print which DID bytes/bits changed. This is how a
    setting gets labelled: read, change that one setting in the truck, read again, diff."""
    b = json.load(open(a.before)); c = json.load(open(a.after))
    bd, cd = b.get('dids', {}), c.get('dids', {})
    any_change = False
    for did in sorted(set(bd) | set(cd)):
        x, y = bd.get(did), cd.get(did)
        if isinstance(x, str) and isinstance(y, str) and x != y:
            any_change = True
            xb = bytes.fromhex(x); yb = bytes.fromhex(y)
            print(f'DID {did} changed:')
            for i in range(max(len(xb), len(yb))):
                ox = xb[i] if i < len(xb) else None
                oy = yb[i] if i < len(yb) else None
                if ox != oy:
                    bits = (ox or 0) ^ (oy or 0)
                    print('  byte %d: %02X -> %02X   (bits changed: 0x%02X)' %
                          (i, ox or 0, oy or 0, bits))
    if not any_change:
        print('No DID byte changes between the two reads.')

def main():
    ap = argparse.ArgumentParser(add_help=True, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    def common(p):
        p.add_argument('--port'); p.add_argument('--bus', default='s4')
    p = sub.add_parser('ports'); p.set_defaults(fn=cmd_ports)
    p = sub.add_parser('sniff'); common(p); p.add_argument('--seconds', type=float, default=5); p.set_defaults(fn=cmd_sniff)
    p = sub.add_parser('discover'); common(p); p.add_argument('--start', default='0x600'); p.add_argument('--end', default='0x7FF'); p.set_defaults(fn=cmd_discover)
    p = sub.add_parser('read'); common(p); p.add_argument('--tx', default=None); p.add_argument('--rx', default=None); p.add_argument('--save', default=None); p.set_defaults(fn=cmd_read)
    p = sub.add_parser('diff'); p.add_argument('before'); p.add_argument('after'); p.set_defaults(fn=cmd_diff)
    a = ap.parse_args()
    a.fn(a)

if __name__ == '__main__':
    main()
