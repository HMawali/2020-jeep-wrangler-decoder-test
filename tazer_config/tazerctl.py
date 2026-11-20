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
  python -I tazerctl.py watch    --port COM3 [--bus s4|s6] [--ids 3B3,3B4,3C2] [--seconds N] [--save out.json]
  python -I tazerctl.py diff     before.json after.json        # label-discovery helper

  watch = LISTEN-ONLY live view of the config / Customer-Settings broadcast bitmaps
          (0x3B3/0x3B4/0x3C2 + 0x3E8-0x3EB...). Toggle a menu setting and see the bit move.

  python -I tazerctl.py write --port COM3 --bus s6 --tx 0x620 --rx 0x504 --did 0x0146 --verify
  python -I tazerctl.py write ... --did 0x0146 --byte 7 --mask 0x80 --value 0x80 [--yes]
  python -I tazerctl.py write ... --revert revert_0146.json --yes

  write = DANGEROUS read-modify-write of a config block. Dry-run (prints the exact 2E frame
          and stops) UNLESS you pass --yes. Always reads first and saves a revert file.
          --verify writes the block back UNCHANGED (proves the write path, changes nothing).

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
        lbl = cat.block_label(did)
        tag = '0x%04X %s' % (did, ('[%s]' % lbl) if lbl else '')
        try:
            r = uds.read_did(did, tx, rx, ignore=ignore)
        except Exception:
            r = None
        if r is None:
            print('  DID %s: — no response' % tag); results['0x%04X' % did] = None; continue
        if r.is_negative:
            print('  DID %s: — NRC 0x%02X (%s)' % (tag, r.nrc, nrc_name(r.nrc)))
            results['0x%04X' % did] = {'nrc': r.nrc}; continue
        if len(r.data) >= 3 and r.data[0] == 0x62:
            payload = r.data[3:]
            ok += 1
            print('  DID %s: %s' % (tag, payload.hex(' ').upper() or '(empty)'))
            results['0x%04X' % did] = payload.hex().upper()
        else:
            print('  DID %s: ? %s' % (tag, r.hex)); results['0x%04X' % did] = {'raw': r.hex}
    link.close()
    print(f'# {ok}/{len(cat.all_dids)} DIDs read.')
    if not ok:
        print('# Nothing answered. Try --bus s6, another --tx, or confirm SGW bypass + key RUN.')
    if a.save:
        json.dump({'module': '0x%03X' % tx, 'bus': bus, 'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                   'dids': results}, open(a.save, 'w'), indent=2)
        print(f'# saved -> {a.save}')

# Config/Customer-Settings broadcast bitmap IDs (free-running on the bus; same ID on
# CAN-C and CAN-IHS). Source: community jeep-jl-powernet "CAN IDs" sheet.
#   0x3B3/0x3B4/0x3C2 = Customer Settings Menu bitmap 1-3
#   0x3E8-0x3EB,0x44A,0x44C,0x381,0x38A = Vehicle Config bitmap ; 0x3F0,0x3F2 = ECU Config bitmap
WATCH_CSM = [0x3B3, 0x3B4, 0x3C2]
WATCH_VEHCFG = [0x3E8, 0x3E9, 0x3EA, 0x3EB, 0x44A, 0x44C, 0x381, 0x38A]
WATCH_ECUCFG = [0x3F0, 0x3F2]
DEFAULT_WATCH_IDS = WATCH_CSM + WATCH_VEHCFG + WATCH_ECUCFG

def _byte_bit_diff(xhex, yhex):
    """List of 'byte i: AA->BB (bits 0xNN)' for each differing byte."""
    xb = bytes.fromhex(xhex); yb = bytes.fromhex(yhex); out = []
    for i in range(max(len(xb), len(yb))):
        ox = xb[i] if i < len(xb) else 0
        oy = yb[i] if i < len(yb) else 0
        if ox != oy:
            out.append('byte %d: %02X -> %02X   (bits changed: 0x%02X)' % (i, ox, oy, ox ^ oy))
    return out

def _parse_ids(s):
    return sorted({int(x.strip().replace('0x', ''), 16) for x in s.split(',') if x.strip()})

def cmd_watch(a):
    """LISTEN-ONLY (safe) capture of the config / Customer-Settings broadcast bitmaps.
    Shows byte/bit changes live: start it, then toggle one setting in the truck and watch
    which bit moves. That bit maps back to the matching 0146/0147 (CSM) or 0122-0126 DID.
    No diagnostic session, no write — cannot disturb the bus."""
    port = pick_port(a.port); bus = bus_of(a.bus)
    ids = set(_parse_ids(a.ids)) if a.ids else set(DEFAULT_WATCH_IDS)
    link = SlcanLink(port); link.open(bus, listen_only=True)   # M1 silent
    print(f'# WATCH (listen-only, safe) on {BUS_LABEL[bus]}')
    print('# IDs: ' + ' '.join('0x%03X' % i for i in sorted(ids)))
    print('# Toggle ONE setting now — byte/bit changes print live. Ctrl-C to stop.')
    print('# (An ID that never prints a baseline may only broadcast at key-on; cycle the key.)')
    last = {}; changes = 0
    deadline = (time.time() + a.seconds) if a.seconds and a.seconds > 0 else None
    try:
        while deadline is None or time.time() < deadline:
            for f in link.collect(0.2):
                if f.id not in ids:
                    continue
                h = f.hex; prev = last.get(f.id)
                if prev is None:
                    last[f.id] = h
                    print('  baseline 0x%03X = %s' % (f.id, f.data.hex(' ').upper()))
                elif h != prev:
                    changes += 1
                    print('  CHANGE   0x%03X : %s -> %s' %
                          (f.id, bytes.fromhex(prev).hex(' ').upper(), f.data.hex(' ').upper()))
                    for d in _byte_bit_diff(prev, h):
                        print('           ' + d)
                    last[f.id] = h
    except KeyboardInterrupt:
        print('\n# stopped by user')
    link.close()
    print(f'# {len(last)} watched IDs seen, {changes} change event(s).')
    if a.save:
        json.dump({'bus': bus, 'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                   'frames': {'0x%03X' % k: v for k, v in last.items()}},
                  open(a.save, 'w'), indent=2)
        print(f'# saved last values -> {a.save}')

def cmd_write(a):
    """DANGEROUS: write one config block (UDS 2E) via read-modify-write.
    Dry-run by default — prints exactly what it WOULD send and stops. Only --yes transmits.
    Always: enters extended session, READs the block first, shows before/after, and saves the
    original to a revert file. A wrong write can brick a body module — read HANDOFF.md."""
    port = pick_port(a.port); bus = bus_of(a.bus)
    cat = did_catalog.load()
    tx = (int(a.tx, 16) if isinstance(a.tx, str) else a.tx) or cat.bcm_request_id
    rx = (int(a.rx, 16) if isinstance(a.rx, str) else a.rx) if a.rx is not None else None
    link = SlcanLink(port); link.open(bus, listen_only=False)
    uds = UdsClient(link)
    ignore = {f.id for f in link.collect(2.0)}; link.drain()
    try:
        s = uds.diagnostic_session(0x03, tx, rx)
        print('# session 0x10 03 -> ' + (('DENIED %s' % nrc_name(s.nrc)) if (s and s.is_negative)
              else (('OK ' + s.hex) if s else 'no response')))
    except Exception as e:
        print('# session error:', e)
    uds.tester_present(tx)

    # --- revert mode: restore a previously saved original block verbatim ---
    if a.revert:
        saved = json.load(open(a.revert))
        did = int(saved['did'], 16); new = bytes.fromhex(saved['original'])
        print('# REVERT DID 0x%04X <- %s' % (did, new.hex(' ').upper()))
        if not a.yes:
            print('# dry-run. add --yes to actually write the revert.'); link.close(); return
        w = uds.write_did(did, new, tx, rx, ignore=ignore)
        print('# write resp: ' + (('NRC 0x%02X %s' % (w.nrc, nrc_name(w.nrc))) if (w and w.is_negative)
              else (w.hex if w else 'no response')))
        link.close(); return

    did = int(a.did, 16)
    # read current block
    r = uds.read_did(did, tx, rx, ignore=ignore)
    if r is None or r.is_negative or not (len(r.data) >= 3 and r.data[0] == 0x62):
        print('# ABORT: could not read DID 0x%04X first (%s). Not writing.' %
              (did, (('NRC %s' % nrc_name(r.nrc)) if (r and r.is_negative) else 'no/bad response')))
        link.close(); return
    old = bytes(r.data[3:])

    if a.verify:
        new = old  # identical write: proves the write path end-to-end, changes nothing
        change = '(identical readback — no change)'
    else:
        if a.byte is None or a.mask is None or a.value is None:
            print('# need --byte N --mask 0xNN --value 0xNN  (or --verify). Aborting.'); link.close(); return
        b = int(a.byte); mask = int(a.mask, 16); val = int(a.value, 16)
        if b >= len(old):
            print('# ABORT: byte %d beyond block length %d' % (b, len(old))); link.close(); return
        nb = bytearray(old); nb[b] = ((old[b] & (~mask & 0xFF)) | (val & mask)) & 0xFF
        new = bytes(nb); change = 'byte %d: %02X -> %02X (mask 0x%02X)' % (b, old[b], new[b], mask)

    lbl = cat.block_label(did)
    print('\n# DID 0x%04X %s' % (did, ('[%s]' % lbl) if lbl else ''))
    print('#   current : ' + old.hex(' ').upper())
    print('#   new     : ' + new.hex(' ').upper() + '   ' + change)
    print('#   frame   : 2E %02X %02X %s' % ((did >> 8) & 0xFF, did & 0xFF, new.hex(' ').upper()))

    revfile = a.save or ('revert_%04X.json' % did)
    json.dump({'did': '0x%04X' % did, 'original': old.hex().upper(),
               'module': '0x%03X' % tx, 'bus': bus, 'time': time.strftime('%Y-%m-%d %H:%M:%S')},
              open(revfile, 'w'), indent=2)
    print('#   saved original -> %s  (undo with:  write --revert %s --yes)' % (revfile, revfile))

    if not a.yes:
        print('\n# DRY-RUN. Nothing was sent. Re-run with --yes to actually write.')
        link.close(); return

    w = uds.write_did(did, new, tx, rx, ignore=ignore)
    print('# write resp: ' + (('NRC 0x%02X (%s)' % (w.nrc, nrc_name(w.nrc))) if (w and w.is_negative)
          else (('POSITIVE ' + w.hex) if w else 'no response')))
    rb = uds.read_did(did, tx, rx, ignore=ignore)
    if rb and not rb.is_negative and len(rb.data) >= 3:
        back = bytes(rb.data[3:])
        print('# readback : ' + back.hex(' ').upper() + ('   == new (confirmed)' if back == new else '   != new (!)'))
    link.close()

def cmd_diff(a):
    """Compare two saved snapshots (read DIDs or watch frames); print which bytes/bits
    changed. This is how a setting gets labelled: snapshot, change ONE setting, snapshot, diff."""
    b = json.load(open(a.before)); c = json.load(open(a.after))
    any_change = False
    for key, noun in (('dids', 'DID'), ('frames', 'ID')):
        bd, cd = b.get(key, {}), c.get(key, {})
        for k in sorted(set(bd) | set(cd)):
            x, y = bd.get(k), cd.get(k)
            if isinstance(x, str) and isinstance(y, str) and x != y:
                any_change = True
                print(f'{noun} {k} changed:')
                for line in _byte_bit_diff(x, y):
                    print('  ' + line)
    if not any_change:
        print('No byte changes between the two snapshots.')

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
    p = sub.add_parser('watch'); common(p)
    p.add_argument('--seconds', type=float, default=0, help='0 = until Ctrl-C')
    p.add_argument('--ids', default=None, help='comma hex list; default = CSM + config bitmaps')
    p.add_argument('--save', default=None); p.set_defaults(fn=cmd_watch)
    p = sub.add_parser('write', help='DANGEROUS read-modify-write of a config block (dry-run unless --yes)')
    common(p)
    p.add_argument('--tx', default=None); p.add_argument('--rx', default=None)
    p.add_argument('--did', help='e.g. 0x0146'); p.add_argument('--byte', type=int)
    p.add_argument('--mask', default=None, help='e.g. 0x80'); p.add_argument('--value', default=None, help='e.g. 0x80')
    p.add_argument('--verify', action='store_true', help='write the block back UNCHANGED (proves write path, changes nothing)')
    p.add_argument('--save', default=None, help='revert file to save the original block to')
    p.add_argument('--revert', default=None, help='restore a saved original block file')
    p.add_argument('--yes', action='store_true', help='actually transmit (without this it is a dry-run)')
    p.set_defaults(fn=cmd_write)
    p = sub.add_parser('diff'); p.add_argument('before'); p.add_argument('after'); p.set_defaults(fn=cmd_diff)
    a = ap.parse_args()
    a.fn(a)

if __name__ == '__main__':
    main()
