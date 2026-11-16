"""Live CAN dashboard for the 2020 Jeep Wrangler via WeAct USB2CANFD (slcan) on COM3.

The adapter is opened in SILENT mode (M1): it only listens, never transmits or ACKs.
Run:  python -I server.py [--port COM3] [--http 8765]
Then open http://localhost:8765
No third-party packages needed (uses the Windows serial API through ctypes).
"""
import argparse, ctypes, json, os, sys, threading, time
from ctypes import wintypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# ---------------- Windows serial port (no pyserial) ----------------
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
GENERIC_RW = 0x80000000 | 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value
MAXDWORD = 0xFFFFFFFF

class COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [('ReadIntervalTimeout', wintypes.DWORD), ('ReadTotalTimeoutMultiplier', wintypes.DWORD),
                ('ReadTotalTimeoutConstant', wintypes.DWORD), ('WriteTotalTimeoutMultiplier', wintypes.DWORD),
                ('WriteTotalTimeoutConstant', wintypes.DWORD)]

k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
k32.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
k32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
k32.SetCommTimeouts.argtypes = [wintypes.HANDLE, ctypes.POINTER(COMMTIMEOUTS)]
k32.EscapeCommFunction.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.CloseHandle.argtypes = [wintypes.HANDLE]


class Serial:
    def __init__(self, port):
        self.h = k32.CreateFileW('\\\\.\\' + port, GENERIC_RW, 0, None, OPEN_EXISTING, 0, None)
        if self.h == INVALID_HANDLE or self.h is None:
            raise OSError(f'Cannot open {port} (error {ctypes.get_last_error()}). Is another program using it?')
        to = COMMTIMEOUTS(MAXDWORD, MAXDWORD, 100, 0, 1000)  # return as soon as data arrives, or after 100 ms
        k32.SetCommTimeouts(self.h, ctypes.byref(to))
        k32.EscapeCommFunction(self.h, 5)  # SETDTR - CDC firmware may wait for DTR
        self.buf = ctypes.create_string_buffer(4096)

    def read(self):
        n = wintypes.DWORD(0)
        if not k32.ReadFile(self.h, self.buf, 4096, ctypes.byref(n), None):
            raise OSError(f'Read failed (error {ctypes.get_last_error()})')
        return self.buf.raw[:n.value]

    def write(self, data: bytes):
        n = wintypes.DWORD(0)
        k32.WriteFile(self.h, data, len(data), ctypes.byref(n), None)

    def close(self):
        k32.CloseHandle(self.h)


# ---------------- Decoding (found from captures on this vehicle) ----------------
# 0xD = Park (confirmed), 0xB seen briefly while stopped - probably Reverse or Neutral (unconfirmed)
GEARS = {0xD: 'P', 0xB: 'R?', 1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8'}

state = {
    'rpm': None, 'speed_kmh': None, 'wheels_kmh': [None] * 4, 'pedal': None,
    'gear': None, 'gear_raw': None, 'shifting': False,
    'fps': 0, 'ids': 0, 'connected': False, 'error': None, 'updated': 0.0,
}
lock = threading.Lock()


def decode(fid, d):
    if fid == 0x025 and len(d) >= 2:            # engine RPM, 1 rpm/bit
        state['rpm'] = (d[0] << 8) | d[1]
    elif fid == 0x08B and len(d) >= 8:          # 4 wheel speeds, low 12 bits, 0.1 km/h/bit
        w = [(((d[2*i] << 8) | d[2*i+1]) & 0x0FFF) / 10.0 for i in range(4)]
        state['wheels_kmh'] = w
        state['speed_kmh'] = round(sum(w) / 4, 1)
    elif fid == 0x09D and len(d) >= 1:          # accelerator pedal (raw, ~0-100, scale not confirmed)
        state['pedal'] = d[0]
    elif fid == 0x085 and len(d) >= 2:          # gear: same nibble twice = engaged, different = shifting
        g = d[1]; hi, lo = g >> 4, g & 0xF
        state['gear_raw'] = f'{g:02X}'
        state['shifting'] = hi != lo
        if hi == lo:
            state['gear'] = GEARS.get(lo, f'{g:02X}')
        else:  # low nibble = current gear, high nibble = target (e.g. 0x21 while shifting 1->2)
            state['gear'] = f'{GEARS.get(lo, "?")}→{GEARS.get(hi, "?")}'


def reader(port, rate_cmd):
    seen = set(); count = 0; t0 = time.time()
    while True:
        ser = None
        try:
            ser = Serial(port)
            for c in (b'C\r', b'M1\r', rate_cmd + b'\r', b'O\r'):   # close, SILENT mode, bitrate, open
                ser.write(c); time.sleep(0.15); ser.read()
            with lock:
                state['connected'] = True; state['error'] = None
            pending = b''
            while True:
                pending += ser.read()
                *lines, pending = pending.split(b'\r')
                for ln in lines:
                    if not ln:
                        continue
                    k = ln[:1]
                    try:
                        if k in (b't', b'r', b'd', b'b'):
                            fid = int(ln[1:4], 16); payload = bytes.fromhex(ln[5:].decode())
                        elif k in (b'T', b'R', b'D', b'B'):
                            fid = int(ln[1:9], 16); payload = bytes.fromhex(ln[10:].decode())
                        else:
                            continue
                    except ValueError:
                        continue
                    count += 1; seen.add(fid)
                    with lock:
                        decode(fid, payload)
                now = time.time()
                if now - t0 >= 1.0:
                    with lock:
                        state['fps'] = round(count / (now - t0)); state['ids'] = len(seen)
                    count = 0; seen = set(); t0 = now
                with lock:
                    state['updated'] = now
        except Exception as e:  # noqa: BLE001 - keep retrying, report on the page
            with lock:
                state['connected'] = False; state['error'] = str(e); state['fps'] = 0
            time.sleep(2)
        finally:
            if ser:
                try:
                    ser.write(b'C\r'); ser.close()
                except Exception:
                    pass


HERE = os.path.dirname(os.path.abspath(__file__))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            body = open(os.path.join(HERE, 'dashboard.html'), 'rb').read()
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        elif self.path == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream'); self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            try:
                while True:
                    with lock:
                        msg = json.dumps(state)
                    self.wfile.write(f'data: {msg}\n\n'.encode()); self.wfile.flush()
                    time.sleep(0.05)   # 20 updates/s
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
        else:
            self.send_error(404)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='COM3')
    ap.add_argument('--http', type=int, default=8765)
    ap.add_argument('--bitrate', default='S6', help='slcan bitrate command, S6 = 500 kbit/s')
    a = ap.parse_args()
    threading.Thread(target=reader, args=(a.port, a.bitrate.encode()), daemon=True).start()
    print(f'Dashboard on http://localhost:{a.http}  (CAN {a.port}, {a.bitrate}, silent mode)', flush=True)
    ThreadingHTTPServer(('127.0.0.1', a.http), Handler).serve_forever()
