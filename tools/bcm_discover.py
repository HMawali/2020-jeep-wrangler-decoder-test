#!/usr/bin/env python3
"""
bcm_discover.py - exhaustive 11-bit UDS responder discovery for the WeAct USB2CANFD (slcan).

Why this exists (vs tools/disco.ps1 + tools/uds.ps1):
  * disco.ps1 default range was 0x700-0x7FF -> it never probed 0x600-0x6FF,
    which is where FCA body modules (BCM / radio / HVAC) usually answer.
  * uds.ps1 only accepted responses at 0x7E8-0x7EF -> a body module replying
    at any other ID was dropped. This script accepts ANY response ID.
  * Per-ID timing here is conservative (default 40 ms) so slow modules reply.

What it does:
  For every request ID in the range, sends a benign UDS request as an ISO-TP
  single frame and records every frame that appears on the bus right after
  (minus the known free-running broadcast IDs it learned during a quiet
  baseline). Benign services only: 3E 00 (TesterPresent) or 10 03 (enter
  extended session). It never writes, never does SecurityAccess, never clears.

SAFETY:
  * A scan MUST transmit (normal mode), so it is NOT listen-only. Vehicle PARKED.
  * Default bus is the 125k IHS (comfort) bus. Do NOT scan the 500k CAN-C bus
    casually: fuzzing/soft traffic there disturbed PCM<->TCM torque arbitration
    and set DTCs (see CAN_CONTROL_FINDINGS.md section 7). Reading is fine; this
    tool only sends tiny well-formed single frames, but keep powertrain scans short.

Cross-platform serial: native Windows (ctypes) + POSIX termios (macOS/Linux),
no third-party packages. On macOS the adapter is /dev/tty.usbmodemXXXX.

Usage:
  # IHS body bus (125k) - the interesting one, scans 0x600-0x7FF:
  python3 -I bcm_discover.py --port /dev/tty.usbmodem1234 --rate S4
  # Windows:
  python  -I bcm_discover.py --port COM3 --rate S4
  # narrow/one range, different service, list serial ports:
  python3 -I bcm_discover.py --list
  python3 -I bcm_discover.py --port COM3 --rate S4 --start 0x600 --end 0x6FF --service 1003
"""
import argparse, os, sys, time

# ----------------------------- serial backends -----------------------------
class _WinSerial:
    def __init__(self, port):
        import ctypes
        from ctypes import wintypes
        self.ct = ctypes; self.wt = wintypes
        GENERIC_RW = 0xC0000000; OPEN_EXISTING = 3; MAXDWORD = 0xFFFFFFFF
        self.k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k32.CreateFileW.restype = wintypes.HANDLE
        self.h = self.k32.CreateFileW('\\\\.\\' + port, GENERIC_RW, 0, None,
                                      OPEN_EXISTING, 0, None)
        if self.h == wintypes.HANDLE(-1).value:
            raise OSError(f'Cannot open {port} (err {ctypes.get_last_error()}). In use?')
        class CT(ctypes.Structure):
            _fields_ = [('ReadIntervalTimeout', wintypes.DWORD),
                        ('ReadTotalTimeoutMultiplier', wintypes.DWORD),
                        ('ReadTotalTimeoutConstant', wintypes.DWORD),
                        ('WriteTotalTimeoutMultiplier', wintypes.DWORD),
                        ('WriteTotalTimeoutConstant', wintypes.DWORD)]
        to = CT(MAXDWORD, 0, 30, 0, 1000)  # return as data arrives / after 30 ms
        self.k32.SetCommTimeouts(self.h, ctypes.byref(to))
    def write(self, b):
        n = self.wt.DWORD(0)
        self.k32.WriteFile(self.h, b, len(b), self.ct.byref(n), None)
    def read(self, n=4096):
        buf = (self.ct.c_char * n)(); got = self.wt.DWORD(0)
        self.k32.ReadFile(self.h, buf, n, self.ct.byref(got), None)
        return bytes(buf[:got.value])
    def close(self):
        try: self.k32.CloseHandle(self.h)
        except Exception: pass

class _PosixSerial:
    def __init__(self, port):
        import termios
        self.termios = termios
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        # raw mode; 115200 is nominal for USB CDC (baud is ignored by CDC-ACM)
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attrs
        iflag = oflag = lflag = 0
        cflag |= (termios.CLOCAL | termios.CREAD)
        try:
            ispeed = ospeed = termios.B115200
        except AttributeError:
            pass
        termios.tcsetattr(self.fd, termios.TCSANOW,
                          [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
    def write(self, b): os.write(self.fd, b)
    def read(self, n=4096):
        try: return os.read(self.fd, n)
        except BlockingIOError: return b''
        except OSError: return b''
    def close(self):
        try: os.close(self.fd)
        except Exception: pass

def open_serial(port):
    return _WinSerial(port) if os.name == 'nt' else _PosixSerial(port)

def list_ports():
    if os.name == 'nt':
        print('Windows: check Device Manager -> Ports (COM & LPT) for the STM32 Virtual COM (usually COMx).')
        return
    import glob
    cands = sorted(set(glob.glob('/dev/tty.usbmodem*') + glob.glob('/dev/tty.usbserial*')
                       + glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')))
    print('Candidate serial ports:' if cands else 'No usb serial ports found.')
    for c in cands: print('  ', c)

# ----------------------------- slcan helpers -----------------------------
class Slcan:
    def __init__(self, port, rate):
        self.s = open_serial(port); self.rate = rate; self._rx = b''
        self.cmd(b'C'); time.sleep(0.05)
    def cmd(self, c):
        self.s.write(c + b'\r'); time.sleep(0.05)
    def open_normal(self):
        # normal mode (M0) required: a scan must ACK/transmit
        self.cmd(b'C'); self.cmd(b'M0'); self.cmd(self.rate.encode()); self.cmd(b'O')
        self.drain()
    def close(self):
        try: self.s.write(b'C\r'); time.sleep(0.05)
        finally: self.s.close()
    def drain(self):
        time.sleep(0.02); self.s.read(); self._rx = b''
    def tx(self, can_id, data):
        frame = 't%03X%d%s' % (can_id, len(data), ''.join('%02X' % b for b in data))
        self.s.write(frame.encode() + b'\r')
    def collect(self, dwell):
        """Read for `dwell` seconds, return list of (id, bytes) data frames."""
        out = []; end = time.time() + dwell
        while time.time() < end:
            self._rx += self.s.read()
            while b'\r' in self._rx:
                line, self._rx = self._rx.split(b'\r', 1)
                f = self._parse(line.decode('ascii', 'ignore').strip())
                if f: out.append(f)
            time.sleep(0.002)
        return out
    @staticmethod
    def _parse(ln):
        if not ln or ln[0] not in 'tT': return None
        try:
            if ln[0] == 't':
                cid = int(ln[1:4], 16); dl = int(ln[4], 16); hx = ln[5:5+dl*2]
            else:
                cid = int(ln[1:9], 16); dl = int(ln[9], 16); hx = ln[10:10+dl*2]
            data = bytes(int(hx[i:i+2], 16) for i in range(0, len(hx), 2))
            return (cid, data)
        except (ValueError, IndexError):
            return None

NRC = {0x10:'generalReject',0x11:'serviceNotSupported',0x12:'subFunctionNotSupported',
       0x13:'incorrectLength',0x22:'conditionsNotCorrect',0x31:'requestOutOfRange',
       0x33:'securityAccessDenied',0x35:'invalidKey',0x7E:'subFnNotSupportedInSession',
       0x7F:'serviceNotSupportedInSession'}

def describe(data):
    if not data: return ''
    pci = data[0] >> 4
    if pci == 0 and len(data) >= 2:
        svc = data[1]
        if svc == 0x7F and len(data) >= 4:
            return 'NRC svc=%02X %s(%02X)' % (data[2], NRC.get(data[3], '?'), data[3])
        if svc & 0x40:  # positive response
            return 'POSITIVE resp to svc %02X' % (svc & 0xBF)
        return 'single svc=%02X' % svc
    if pci == 1:
        return 'ISO-TP first-frame (multiframe follows)'
    return 'pci=%d' % pci

# ----------------------------- discovery -----------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port'); ap.add_argument('--rate', default='S4', help='S4=125k IHS (default), S6=500k CAN-C')
    ap.add_argument('--start', default='0x600'); ap.add_argument('--end', default='0x7FF')
    ap.add_argument('--service', default='3E00', help='benign UDS req hex: 3E00 (TesterPresent) or 1003 (extended session)')
    ap.add_argument('--dwell', type=float, default=0.04, help='seconds to listen after each request (default 0.04)')
    ap.add_argument('--baseline', type=float, default=3.0, help='seconds of quiet capture to learn free-running IDs')
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    if a.list: list_ports(); return
    if not a.port: ap.error('need --port (or use --list)')

    start, end = int(a.start, 16), int(a.end, 16)
    req = bytes(int(a.service[i:i+2], 16) for i in range(0, len(a.service), 2))
    sf = bytes([len(req)]) + req; sf += bytes(8 - len(sf))  # ISO-TP single frame, padded to 8

    bus = {'S4': 'IHS 125k (pins 3/11)', 'S6': 'CAN-C 500k (pins 6/14)'}.get(a.rate, a.rate)
    print(f'# bcm_discover  port={a.port}  bus={bus}  ids=0x{start:03X}-0x{end:03X}  req={a.service}')
    if a.rate == 'S6':
        print('# WARNING: scanning the 500k powertrain bus. Keep it short; it carries live torque arbitration.')
    print('# Vehicle must be PARKED, key in RUN. This transmits (not listen-only).')

    link = Slcan(a.port, a.rate)
    try:
        link.open_normal()
        print(f'# learning free-running broadcast IDs for {a.baseline:.0f}s (stay quiet)...')
        baseline = {cid for cid, _ in link.collect(a.baseline)}
        print(f'#   {len(baseline)} broadcast IDs will be ignored.')
        link.drain()
        found = []
        for rid in range(start, end + 1):
            link.tx(rid, sf)
            for cid, data in link.collect(a.dwell):
                if cid in baseline:  # free-running traffic, not a reply
                    continue
                # a plausible diagnostic reply: single/first frame carrying a UDS svc or NRC
                pci = data[0] >> 4 if data else -1
                looks = (pci == 0 and len(data) >= 2 and (data[1] == 0x7F or (data[1] & 0x40))) or pci == 1
                if looks:
                    tag = describe(data)
                    found.append((rid, cid, data.hex().upper(), tag))
                    print(f'  req 0x{rid:03X} -> resp 0x{cid:03X}: {data.hex().upper()}   {tag}')
            if (rid - start) % 64 == 0:
                print(f'#   ...0x{rid:03X}', file=sys.stderr)
        print(f'\n# done. {len(found)} candidate responder frame(s).')
        if not found:
            print('# No UDS responders in this range/bus. If IHS 0x600-0x7FF is also silent, the')
            print('# BCM diagnostics are almost certainly bound to the SGW router (not directly')
            print('# bus-addressable) -> same wall noted in WRANGLER_CAN_REFERENCE.md section 7.')
        else:
            print('# Next: for each responder ID, try ReadDataByIdentifier (22 xx xx) to pull config,')
            print('# e.g. common FCA DIDs. Writes/SecurityAccess need the per-module seed->key (not available here).')
    finally:
        link.close()

if __name__ == '__main__':
    main()
