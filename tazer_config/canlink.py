#!/usr/bin/env python3
"""
canlink.py - serial + slcan layer for the WeAct USB2CANFD adapter.

Zero third-party dependencies. Native Windows backend (ctypes) + POSIX (termios),
so the same code runs on the Windows laptop (COM3) and on macOS/Linux
(/dev/tty.usbmodem*). slcan command set verified against the WeAct firmware
(see ../WRANGLER_CAN_REFERENCE.md section 1).
"""
import os, sys, time, glob

# ------------------------------- serial backends -------------------------------
class _WinSerial:
    def __init__(self, port):
        import ctypes
        from ctypes import wintypes
        self.ct = ctypes; self.wt = wintypes
        GENERIC_RW = 0xC0000000; OPEN_EXISTING = 3; MAXDWORD = 0xFFFFFFFF
        self.k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k32.CreateFileW.restype = wintypes.HANDLE
        # '\\.\COM10'+ form is required for COM ports >= 10
        name = port if port.startswith('\\\\') else '\\\\.\\' + port
        self.h = self.k32.CreateFileW(name, GENERIC_RW, 0, None, OPEN_EXISTING, 0, None)
        if self.h == wintypes.HANDLE(-1).value:
            raise OSError(f'cannot open {port} (err {ctypes.get_last_error()}). In use?')
        class CT(ctypes.Structure):
            _fields_ = [('ReadIntervalTimeout', wintypes.DWORD),
                        ('ReadTotalTimeoutMultiplier', wintypes.DWORD),
                        ('ReadTotalTimeoutConstant', wintypes.DWORD),
                        ('WriteTotalTimeoutMultiplier', wintypes.DWORD),
                        ('WriteTotalTimeoutConstant', wintypes.DWORD)]
        self.k32.SetCommTimeouts(self.h, ctypes.byref(CT(MAXDWORD, 0, 20, 0, 1000)))
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
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        a = termios.tcgetattr(self.fd)
        a[0] = a[1] = a[3] = 0                       # iflag/oflag/lflag raw
        a[2] |= (termios.CLOCAL | termios.CREAD)     # cflag
        try: a[4] = a[5] = termios.B115200
        except AttributeError: pass
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
    def write(self, b): os.write(self.fd, b)
    def read(self, n=4096):
        try: return os.read(self.fd, n)
        except (BlockingIOError, OSError): return b''
    def close(self):
        try: os.close(self.fd)
        except Exception: pass

def open_serial(port):
    return _WinSerial(port) if os.name == 'nt' else _PosixSerial(port)

def list_ports():
    if os.name == 'nt':
        # probe COM1..COM32 by trying to open them briefly
        found = []
        for i in range(1, 33):
            p = f'COM{i}'
            try:
                s = _WinSerial(p); s.close(); found.append(p)
            except OSError:
                pass
        return found
    return sorted(set(glob.glob('/dev/tty.usbmodem*') + glob.glob('/dev/cu.usbmodem*') +
                      glob.glob('/dev/tty.usbserial*') + glob.glob('/dev/ttyACM*') +
                      glob.glob('/dev/ttyUSB*')))

# ------------------------------- slcan link -------------------------------
# bitrate presets
S_125K = 'S4'   # CAN-IHS / body  (OBD pins 3/11)
S_500K = 'S6'   # CAN-C / powertrain (OBD pins 6/14)
BUS_LABEL = {S_125K: '125k CAN-IHS (pins 3/11)', S_500K: '500k CAN-C (pins 6/14)'}

class CanFrame:
    __slots__ = ('id', 'data', 'ext')
    def __init__(self, cid, data, ext=False):
        self.id = cid; self.data = bytes(data); self.ext = ext
    @property
    def hex(self): return self.data.hex().upper()
    def __repr__(self): return f'CanFrame(0x{self.id:X}, {self.hex})'

class SlcanLink:
    def __init__(self, port):
        self.s = open_serial(port); self._rx = b''; self.listen_only = False
    def _cmd(self, c):
        self.s.write(c + b'\r'); time.sleep(0.05)
    def open(self, bitrate=S_125K, listen_only=False):
        """listen_only=True -> M1 (silent, cannot ACK/transmit). Normal mode (M0) to diagnose."""
        self.listen_only = listen_only
        self._cmd(b'C')
        self._cmd(b'M1' if listen_only else b'M0')
        self._cmd(bitrate.encode())
        self._cmd(b'O')
        self.drain()
    def close(self):
        try: self.s.write(b'C\r'); time.sleep(0.05)
        finally: self.s.close()
    def drain(self):
        time.sleep(0.02); self.s.read(); self._rx = b''
    def transmit(self, frame):
        if self.listen_only:
            raise RuntimeError('refusing to transmit: link is in listen-only (M1) mode')
        line = 't%03X%d%s' % (frame.id & 0x7FF, len(frame.data), frame.data.hex().upper())
        self.s.write(line.encode() + b'\r')
    def collect(self, dwell):
        """Read for `dwell` seconds; return list of CanFrame."""
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
                cid = int(ln[1:4], 16); dl = int(ln[4], 16); hx = ln[5:5+dl*2]; ext = False
            else:
                cid = int(ln[1:9], 16); dl = int(ln[9], 16); hx = ln[10:10+dl*2]; ext = True
            return CanFrame(cid, bytes(int(hx[i:i+2], 16) for i in range(0, len(hx), 2)), ext)
        except (ValueError, IndexError):
            return None
