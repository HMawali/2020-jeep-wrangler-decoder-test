#!/usr/bin/env python3
"""
server.py - local HTTP bridge for the Tazer-JL cockpit UI.

Pure Python standard library (http.server) - no FastAPI, no npm, no build step, so it starts
instantly on a fresh Windows box. It imports and reuses the REAL backend (canlink.py, uds.py,
did_catalog.py) and the firmware-extracted catalogs (settings_map.json, actuations.json,
lamp_map.json, shows.json, did_map.json). There is ONE source of truth for the protocol: the
existing UdsClient runs on a live SlcanLink or, in Simulator mode, on sim.SimLink.

Safety is preserved from the CLI: config writes are read-modify-write, dry-run unless confirmed,
and save a revert snapshot; 0x2F outputs and light shows require ENGINE RUNNING (live) and always
release on stop/exit; nothing fabricates a DID/frame - everything comes from the catalogs.
"""
import os, sys, json, time, threading, webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

UI_DIR = os.path.dirname(os.path.abspath(__file__))
TC_DIR = os.path.dirname(UI_DIR)
STATIC = os.path.join(UI_DIR, 'static')
REVERT_DIR = os.path.join(TC_DIR, 'reverts')
sys.path.insert(0, TC_DIR)
sys.path.insert(0, UI_DIR)

from canlink import SlcanLink, CanFrame, S_125K, S_500K, BUS_LABEL, list_ports  # noqa: E402
from uds import UdsClient, nrc_name  # noqa: E402
import sim as simmod  # noqa: E402


def load_json(name):
    with open(os.path.join(TC_DIR, name)) as f:
        return json.load(f)


# ------------------------------------------------------------------ frame logging
def decode_frame(cid, data):
    if not data:
        return ''
    pci = data[0] >> 4
    body = data[1:] if pci in (0, 1) else data
    if pci == 1:
        body = data[2:]
    if not len(body):
        return ''
    s = body[0]
    names = {0x10: 'Session', 0x11: 'ECUReset', 0x14: 'ClearDTC', 0x19: 'ReadDTC',
             0x22: 'ReadDID', 0x2E: 'WriteDID', 0x2F: 'IOControl', 0x31: 'Routine',
             0x3E: 'TesterPresent', 0x50: 'Session+', 0x54: 'ClearDTC+', 0x59: 'ReadDTC+',
             0x62: 'ReadDID+', 0x6E: 'WriteDID+', 0x6F: 'IOControl+', 0x7F: 'NegResp'}
    label = names.get(s, '')
    if s == 0x7F and len(body) >= 3:
        label = 'NegResp %s' % nrc_name(body[2])
    if s in (0x22, 0x2E, 0x2F, 0x62, 0x6E, 0x6F) and len(body) >= 3:
        label += ' %02X%02X' % (body[1], body[2])
    return label


class LoggingLink:
    """Transparent wrapper that records every TX/RX frame for the UI inspector + lamp map."""

    def __init__(self, link, session):
        self._l = link
        self._s = session
        self.listen_only = getattr(link, 'listen_only', False)

    def open(self, *a, **k):
        r = self._l.open(*a, **k)
        self.listen_only = self._l.listen_only
        return r

    def close(self):
        return self._l.close()

    def drain(self):
        return self._l.drain()

    def transmit(self, frame):
        self._s.log('TX', frame.id, frame.data)
        self._s.tx += 1
        self._s.note_output(frame)
        return self._l.transmit(frame)

    def collect(self, dwell):
        fr = self._l.collect(dwell)
        for f in fr:
            self._s.log('RX', f.id, f.data)
            self._s.rx += 1
        return fr


# ------------------------------------------------------------------ session
class Session:
    def __init__(self):
        self.mode = None
        self.link = None
        self.rawlink = None
        self.sim = None
        self.uds = None
        self.bus = S_500K
        self.port = None
        self.connected = False
        self.engine_running = False
        self.profile = '2020 JL'
        self.tx = 0
        self.rx = 0
        self.frames = deque(maxlen=500)
        self.lamps = {}            # '0xD0A0' -> True/False (from observed 0x2F)
        self.lock = threading.RLock()
        self.show_thread = None
        self.show_stop = threading.Event()
        self.show_name = None

    def log(self, direction, cid, data):
        self.frames.append({'t': round(time.time(), 3), 'dir': direction,
                            'id': '0x%03X' % cid, 'hex': bytes(data).hex(' ').upper(),
                            'decode': decode_frame(cid, bytes(data))})

    def note_output(self, frame):
        d = frame.data
        if len(d) >= 4 and (d[0] >> 4) == 0 and d[1] == 0x2F:
            did = '0x%02X%02X' % (d[2], d[3])
            opt = d[4] if len(d) > 4 else 0
            self.lamps[did] = (opt != 0x00)

    def connect(self, mode, port, bus):
        self.disconnect()
        self.bus = S_500K if (bus or 's6').lower() == 's6' else S_125K
        self.mode = mode
        if mode == 'sim':
            self.sim = simmod.SimLink()
            self.rawlink = self.sim
            self.port = 'SIMULATOR'
        else:
            self.sim = None
            self.port = port
            self.rawlink = SlcanLink(port)
        self.rawlink.open(self.bus, listen_only=False)
        self.link = LoggingLink(self.rawlink, self)
        self.uds = UdsClient(self.link)
        self.connected = True
        self.tx = self.rx = 0
        self.lamps = {}

    def disconnect(self):
        self.stop_show()
        if self.rawlink:
            try:
                self.rawlink.close()
            except Exception:
                pass
        self.connected = False
        self.link = self.uds = self.rawlink = self.sim = None

    def require(self):
        if not self.connected:
            raise RuntimeError('not connected - pick a port (or Simulator) and Connect first')

    def interlock_output(self):
        """0x2F outputs / light shows need the BCM extended session held = engine running (live)."""
        if self.mode == 'live' and not self.engine_running:
            raise RuntimeError('ENGINE RUNNING required: the BCM drops the 10 03 session with the '
                               'engine off, so 0x2F outputs / light shows will not hold. Start the '
                               'engine (or flip Vehicle State) and retry.')

    # ---- session/tester helpers ----
    def ensure_session(self, tx, rx=None):
        s = self.uds.diagnostic_session(0x03, tx, rx)
        self.uds.tester_present(tx)
        return s

    def stop_show(self):
        if self.show_thread and self.show_thread.is_alive():
            self.show_stop.set()
            self.show_thread.join(timeout=3)
        self.show_thread = None
        self.show_name = None


SESSION = Session()
CATALOG = {'settings': load_json('settings_map.json'),
           'actuations': load_json('actuations.json'),
           'lamps': load_json('lamp_map.json'),
           'shows': load_json('shows.json'),
           'didmap': load_json('did_map.json')}


# ------------------------------------------------------------------ config read/modify/write
def _bcm(tx=None):
    return tx if tx is not None else 0x620


def cfg_read(name):
    S = CATALOG['settings']['settings']
    d = S[name]
    if d['module'] == 'TAZER':
        return {'name': name, 'module': 'TAZER', 'skip': True,
                'note': 'Tazer-internal flag (%s) - not a vehicle read' % d['read']['did']}
    did = int(d['read']['did'], 16)
    byte = d['read']['byte']
    mask = int(d['read']['mask'], 16)
    tx = _bcm()
    rx = 0x504
    with SESSION.lock:
        SESSION.ensure_session(tx, rx)
        r = SESSION.uds.read_did(did, tx, rx)
    if r is None or r.is_negative or not (len(r.data) >= 3 and r.data[0] == 0x62):
        return {'name': name, 'error': 'could not read %s (%s)' % (
            d['read']['did'], ('NRC %s' % nrc_name(r.nrc)) if (r and r.is_negative) else 'no response')}
    blk = bytes(r.data[3:])
    field = blk[byte] & mask if byte < len(blk) else 0
    val = None
    if d.get('values'):
        inv = {int(k, 0): v for k, v in d['values'].items()}
        val = inv.get(field, inv.get(blk[byte] if byte < len(blk) else 0, 'unmapped(0x%02X)' % field))
    else:
        val = 'ON' if field else 'OFF'
    return {'name': name, 'did': d['read']['did'], 'byte': byte, 'mask': d['read']['mask'],
            'block': blk.hex(' ').upper(), 'field': '0x%02X' % field, 'value': val}


def cfg_set(name, value, dry_run=True):
    S = CATALOG['settings']['settings']
    d = S[name]
    if d['module'] == 'TAZER':
        return {'name': name, 'error': 'Tazer-internal flag - not a vehicle write'}
    tx, rx = _bcm(), 0x504
    want = str(value).lower()
    by_did = {}
    for o in d['write_ops']:
        by_did.setdefault(int(o['did'], 16), []).append(o)
    frames = []
    revert = {}
    with SESSION.lock:
        SESSION.ensure_session(tx, rx)
        for did, ops in by_did.items():
            r = SESSION.uds.read_did(did, tx, rx)
            if r is None or r.is_negative or not (len(r.data) >= 3 and r.data[0] == 0x62):
                return {'name': name, 'error': 'ABORT: could not read 0x%04X first - nothing written' % did}
            old = bytes(r.data[3:])
            revert['0x%04X' % did] = old.hex().upper()
            nb = bytearray(old)
            for o in ops:
                b = o['byte']
                m = int(o['mask'], 16)
                if b >= len(nb):
                    return {'name': name, 'error': 'byte %d beyond block len %d for %s' % (b, len(nb), o['did'])}
                if d.get('values') and want not in ('on', 'off', 'yes', 'no'):
                    nb[b] = (old[b] & (~m & 0xFF)) | (int(str(value), 0) & m)
                else:
                    on = want in ('on', 'yes', '1', 'true')
                    nb[b] = (old[b] | m) if on else (old[b] & (~m & 0xFF))
            frames.append({'did': '0x%04X' % did, 'old': old.hex(' ').upper(),
                           'new': bytes(nb).hex(' ').upper(),
                           'diff': _diff_bytes(old, bytes(nb)),
                           'frame': '2E 01 %02X %s' % (did & 0xFF, bytes(nb).hex(' ').upper())})
        os.makedirs(REVERT_DIR, exist_ok=True)
        revfile = os.path.join(REVERT_DIR, 'revert_%s.json' % name.replace(' ', '_'))
        json.dump({'setting': name, 'blocks': revert, 'time': time.strftime('%Y-%m-%d %H:%M:%S')},
                  open(revfile, 'w'), indent=2)
        result = {'name': name, 'value': value, 'dry_run': dry_run, 'frames': frames,
                  'revert_file': os.path.relpath(revfile, TC_DIR),
                  'polarity_verified': d.get('value_polarity_verified', False)}
        if dry_run:
            result['status'] = 'DRY-RUN - nothing transmitted'
            return result
        sent = []
        for did, ops in by_did.items():
            fr = next(f for f in frames if f['did'] == '0x%04X' % did)
            new = bytes.fromhex(fr['new'].replace(' ', ''))
            old = bytes.fromhex(fr['old'].replace(' ', ''))
            if new == old:
                sent.append({'did': fr['did'], 'result': 'unchanged - skipped'})
                continue
            w = SESSION.uds.write_did(did, new, tx, rx)
            sent.append({'did': fr['did'], 'result': ('NRC %s' % nrc_name(w.nrc)) if (w and w.is_negative)
                         else ('POSITIVE' if w else 'no response')})
        result['status'] = 'TRANSMITTED'
        result['sent'] = sent
        return result


def cfg_revert(name):
    revfile = os.path.join(REVERT_DIR, 'revert_%s.json' % name.replace(' ', '_'))
    if not os.path.exists(revfile):
        return {'error': 'no revert snapshot for %s' % name}
    saved = json.load(open(revfile))
    tx, rx = _bcm(), 0x504
    out = []
    with SESSION.lock:
        SESSION.ensure_session(tx, rx)
        for did_s, hexs in saved['blocks'].items():
            did = int(did_s, 16)
            w = SESSION.uds.write_did(did, bytes.fromhex(hexs), tx, rx)
            out.append({'did': did_s, 'result': ('NRC %s' % nrc_name(w.nrc)) if (w and w.is_negative)
                        else ('POSITIVE' if w else 'no response')})
    return {'name': name, 'reverted': out}


def _diff_bytes(a, b):
    out = []
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else 0
        y = b[i] if i < len(b) else 0
        if x != y:
            out.append('byte %d: %02X->%02X (bits 0x%02X)' % (i, x, y, x ^ y))
    return out


# ------------------------------------------------------------------ actuations (confirmed only)
def actuation_send(key, state=None, dry_run=True):
    conf = CATALOG['actuations']['confirmed']
    if key not in conf:
        return {'error': 'actuation %r is not in the CONFIRMED set - awaiting bench capture' % key}
    SESSION.interlock_output()
    spec = conf[key]
    st = int(str(state), 0) if state is not None else 0x01
    builders = {
        'sway_disconnect': (0x74A, lambda: ('io', 0xF1A8, 0x03, bytes([st]))),
        'force_rwd':       (0x74B, lambda: ('io', 0xD073, 0x03, bytes([st]))),
        'cooldown':        (0x7E0, lambda: ('io', 0xD01B, 0x03, bytes([0x1C, 0xCD]))),
        'splash_write':    (0x747, lambda: ('routine', 0x3046, 0x02, bytes([st]))),
    }
    if key not in builders:
        return {'error': 'no sender wired for %r' % key}
    tx, build = builders[key]
    kind, ident, opt, extra = build()
    if kind == 'io':
        frame = '2F %02X %02X %02X %s' % ((ident >> 8) & 0xFF, ident & 0xFF, opt, extra.hex(' ').upper())
        payload = bytes([0x2F, (ident >> 8) & 0xFF, ident & 0xFF, opt]) + extra
    else:
        frame = '31 %02X %02X %02X %s' % (opt, (ident >> 8) & 0xFF, ident & 0xFF, extra.hex(' ').upper())
        payload = bytes([0x31, opt, (ident >> 8) & 0xFF, ident & 0xFF]) + extra
    res = {'key': key, 'feature': spec['feature'], 'module': '0x%03X' % tx,
           'frame': frame, 'dry_run': dry_run}
    if dry_run:
        res['status'] = 'DRY-RUN - nothing transmitted'
        return res
    with SESSION.lock:
        SESSION.ensure_session(tx)
        r = SESSION.uds.request(payload, tx)
    res['status'] = 'TRANSMITTED'
    res['response'] = (('NRC %s' % nrc_name(r.nrc)) if (r and r.is_negative) else (r.hex if r else 'no response'))
    return res


# ------------------------------------------------------------------ 0x2F lamp tester + light show
def io_force(did_s, module=None, state='01', hold=2.0, dry_run=True):
    SESSION.interlock_output()
    did = int(did_s, 16)
    tx = int(module, 16) if module else 0x620
    rx = 0x504 if tx == 0x620 else None
    st = bytes.fromhex(state.replace('0x', '').replace(' ', '') or '01')
    force = '2F %02X %02X 03 %s' % ((did >> 8) & 0xFF, did & 0xFF, st.hex(' ').upper())
    release = '2F %02X %02X 00' % ((did >> 8) & 0xFF, did & 0xFF)
    res = {'did': did_s, 'module': '0x%03X' % tx, 'force': force, 'release': release, 'dry_run': dry_run}
    if dry_run:
        res['status'] = 'DRY-RUN'
        return res

    def run():
        with SESSION.lock:
            SESSION.ensure_session(tx, rx)
            SESSION.uds.io_control(did, 0x03, st, tx, rx)
        time.sleep(max(0.2, float(hold)))
        with SESSION.lock:
            SESSION.uds.io_control(did, 0x00, b'', tx, rx)
    threading.Thread(target=run, daemon=True).start()
    res['status'] = 'FORCED %.1fs then auto-release' % float(hold)
    return res


def _all_lamp_dids():
    out = set()
    for k in CATALOG['lamps'].get('lamps', {}):
        try:
            out.add(int(k, 16))
        except Exception:
            pass
    return sorted(out)


def show_start(name, duration=30.0, tick_ms=None):
    SESSION.require()
    SESSION.interlock_output()
    SESSION.stop_show()
    doc = CATALOG['shows']
    sh = doc.get('shows', {}).get(name)
    if not sh:
        return {'error': 'no show %r (have: %s)' % (name, ', '.join(doc.get('shows', {})))}
    tick = (tick_ms if tick_ms is not None else doc.get('tick_ms', 20)) / 1000.0
    tx, rx = 0x620, 0x504
    SESSION.show_stop.clear()
    SESSION.show_name = name

    def didof(x):
        return int(x, 16) if isinstance(x, str) else x

    def force(d):
        SESSION.uds.io_control(d, 0x03, b'\x01', tx, rx)

    def release(d):
        SESSION.uds.io_control(d, 0x00, b'', tx, rx)

    def runner():
        with SESSION.lock:
            SESSION.ensure_session(tx, rx)
        end = time.time() + float(duration)
        alld = _all_lamp_dids()
        try:
            while time.time() < end and not SESSION.show_stop.is_set():
                for st in sh.get('steps', []):
                    if SESSION.show_stop.is_set() or time.time() >= end:
                        break
                    with SESSION.lock:
                        if 'blink' in st:
                            ds = [didof(x) for x in st['blink']]
                            for _ in range(max(1, st.get('times', 1))):
                                for d in ds:
                                    force(d)
                                time.sleep(tick * st.get('delay', 10))
                                for d in ds:
                                    release(d)
                                time.sleep(tick * st.get('delay', 10))
                        elif 'on' in st:
                            for x in st['on']:
                                force(didof(x))
                        elif 'off' in st:
                            for x in st['off']:
                                release(didof(x))
                        elif st.get('all_on'):
                            for d in alld:
                                force(d)
                        elif st.get('all_off'):
                            for d in alld:
                                release(d)
                        elif 'wait' in st:
                            time.sleep(tick * st['wait'])
        finally:
            with SESSION.lock:
                for d in alld:
                    try:
                        release(d)
                    except Exception:
                        pass
            SESSION.show_name = None

    SESSION.show_thread = threading.Thread(target=runner, daemon=True)
    SESSION.show_thread.start()
    return {'status': 'playing', 'show': name, 'duration': duration, 'tick_ms': int(tick * 1000)}


# ------------------------------------------------------------------ DTC + fullread
DTC_MODULES = {'BCM': (0x620, 0x504), 'PCM': (0x7E0, 0x7E8), 'IPC': (0x742, 0x4C2),
               'RFH': (0x740, 0x4C0), 'Airbag': (0x744, 0x4C4), '0x74B': (0x74B, 0x4CB),
               '0x74A': (0x74A, 0x4CA)}


def dtc_read(modname):
    tx, rx = DTC_MODULES[modname]
    with SESSION.lock:
        SESSION.ensure_session(tx, rx)
        r = SESSION.uds.request([0x19, 0x02, 0xFF], tx, rx)
    codes = []
    if r and not r.is_negative and len(r.data) >= 3 and r.data[0] == 0x59:
        body = r.data[3:]
        for i in range(0, len(body) - 2, 3):
            codes.append('%02X%02X status=%02X' % (body[i], body[i + 1], body[i + 2]))
    return {'module': modname, 'id': '0x%03X' % tx,
            'codes': codes, 'raw': r.hex if r else None,
            'result': ('NRC %s' % nrc_name(r.nrc)) if (r and r.is_negative) else ('OK' if r else 'no response')}


def dtc_clear(modname):
    tx, rx = DTC_MODULES[modname]
    with SESSION.lock:
        SESSION.ensure_session(tx, rx)
        r = SESSION.uds.request([0x14, 0xFF, 0xFF, 0xFF], tx, rx)
    return {'module': modname, 'result': ('NRC %s' % nrc_name(r.nrc)) if (r and r.is_negative)
            else ('POSITIVE' if r else 'no response')}


def fullread():
    tx, rx = 0x620, 0x504
    out = {}
    with SESSION.lock:
        SESSION.ensure_session(tx, rx)
        for did_s in CATALOG['didmap']['dids']:
            did = int(did_s, 16)
            r = SESSION.uds.read_did(did, tx, rx)
            if r and not r.is_negative and len(r.data) >= 3 and r.data[0] == 0x62:
                out[did_s] = bytes(r.data[3:]).hex().upper()
            else:
                out[did_s] = None
    ok = sum(1 for v in out.values() if v)
    return {'module': '0x620', 'ok': ok, 'total': len(out), 'dids': out}


# ------------------------------------------------------------------ HTTP routing
def jbytes(obj):
    return json.dumps(obj).encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode() or '{}')

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == '/' or path == '/index.html':
                return self._file('index.html', 'text/html')
            if path == '/app.js':
                return self._file('app.js', 'application/javascript')
            if path == '/style.css':
                return self._file('style.css', 'text/css')
            if path == '/api/state':
                return self._send(200, jbytes(self.state()))
            if path == '/api/ports':
                ports = list_ports() if SESSION.mode != 'sim' else []
                return self._send(200, jbytes({'ports': ports}))
            if path == '/api/catalog':
                return self._send(200, jbytes(CATALOG['settings']))
            if path == '/api/actuations':
                return self._send(200, jbytes(CATALOG['actuations']))
            if path == '/api/lamps':
                return self._send(200, jbytes(CATALOG['lamps']))
            if path == '/api/shows':
                return self._send(200, jbytes(CATALOG['shows']))
            if path == '/api/didmap':
                return self._send(200, jbytes(CATALOG['didmap']))
            if path == '/api/stream':
                return self._send(200, jbytes(self.stream()))
            return self._send(404, jbytes({'error': 'not found'}))
        except Exception as e:
            return self._send(500, jbytes({'error': str(e)}))

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            b = self._json_body()
            if path == '/api/connect':
                SESSION.connect(b.get('mode', 'sim'), b.get('port'), b.get('bus', 's6'))
                return self._send(200, jbytes(self.state()))
            if path == '/api/disconnect':
                SESSION.disconnect()
                return self._send(200, jbytes(self.state()))
            if path == '/api/vehicle':
                if 'engine_running' in b:
                    SESSION.engine_running = bool(b['engine_running'])
                if 'profile' in b:
                    SESSION.profile = b['profile']
                return self._send(200, jbytes(self.state()))
            SESSION.require()
            if path == '/api/cfg/get':
                return self._send(200, jbytes(cfg_read(b['name'])))
            if path == '/api/cfg/set':
                return self._send(200, jbytes(cfg_set(b['name'], b['value'], b.get('dry_run', True))))
            if path == '/api/cfg/revert':
                return self._send(200, jbytes(cfg_revert(b['name'])))
            if path == '/api/io':
                return self._send(200, jbytes(io_force(b['did'], b.get('module'), b.get('state', '01'),
                                                        b.get('hold', 2.0), b.get('dry_run', True))))
            if path == '/api/actuation':
                return self._send(200, jbytes(actuation_send(b['key'], b.get('state'), b.get('dry_run', True))))
            if path == '/api/show/start':
                return self._send(200, jbytes(show_start(b['name'], b.get('duration', 30.0), b.get('tick_ms'))))
            if path == '/api/show/stop':
                SESSION.stop_show()
                return self._send(200, jbytes({'status': 'stopped'}))
            if path == '/api/dtc/read':
                return self._send(200, jbytes(dtc_read(b['module'])))
            if path == '/api/dtc/clear':
                return self._send(200, jbytes(dtc_clear(b['module'])))
            if path == '/api/fullread':
                return self._send(200, jbytes(fullread()))
            return self._send(404, jbytes({'error': 'not found'}))
        except Exception as e:
            return self._send(400, jbytes({'error': str(e)}))

    def _file(self, name, ctype):
        p = os.path.join(STATIC, name)
        with open(p, 'rb') as f:
            self._send(200, f.read(), ctype)

    def state(self):
        return {'mode': SESSION.mode, 'connected': SESSION.connected, 'port': SESSION.port,
                'bus': 's6' if SESSION.bus == S_500K else 's4',
                'bus_label': BUS_LABEL.get(SESSION.bus, ''),
                'engine_running': SESSION.engine_running, 'profile': SESSION.profile,
                'tx': SESSION.tx, 'rx': SESSION.rx, 'show': SESSION.show_name}

    def stream(self):
        tele = SESSION.sim.telemetry() if (SESSION.sim) else {'boost_psi': 0, 'vac_inhg': 0, 'rpm': 0, 'speed_mph': 0}
        return {'frames': list(SESSION.frames)[-120:], 'lamps': SESSION.lamps,
                'telemetry': tele, 'tx': SESSION.tx, 'rx': SESSION.rx,
                'show': SESSION.show_name, 'connected': SESSION.connected,
                'engine_running': SESSION.engine_running, 'mode': SESSION.mode}


def main():
    port = int(os.environ.get('TAZER_UI_PORT', '8787'))
    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    url = 'http://127.0.0.1:%d/' % port
    print('=' * 60)
    print(' Tazer JL Cockpit  ->  %s' % url)
    print(' (Simulator mode works with no truck. Ctrl-C to quit.)')
    print('=' * 60)
    if not os.environ.get('TAZER_UI_NOBROWSER'):
        try:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nshutting down...')
        SESSION.disconnect()
        srv.shutdown()


if __name__ == '__main__':
    main()
