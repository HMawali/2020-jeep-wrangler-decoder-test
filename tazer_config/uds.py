#!/usr/bin/env python3
"""
uds.py - ISO-TP (ISO 15765-2) + UDS (ISO 14229) client over the slcan link.

Implements single-frame + multi-frame request/response with flow control.
READ-ONLY services are exposed as helpers; writing (0x2E) is intentionally NOT
provided here (see HANDOFF.md -> "Why writes are locked").
"""
import time
from canlink import CanFrame

NRC = {0x10:'generalReject',0x11:'serviceNotSupported',0x12:'subFunctionNotSupported',
       0x13:'incorrectMessageLength',0x22:'conditionsNotCorrect',0x31:'requestOutOfRange',
       0x33:'securityAccessDenied',0x35:'invalidKey',0x78:'responsePending',
       0x7E:'subFnNotSupportedInSession',0x7F:'serviceNotSupportedInSession'}

def nrc_name(n): return NRC.get(n, '0x%02X' % n)

class Response:
    def __init__(self, from_id, data):
        self.from_id = from_id; self.data = bytes(data)
    @property
    def is_negative(self): return len(self.data) >= 3 and self.data[0] == 0x7F
    @property
    def nrc(self): return self.data[2] if self.is_negative else None
    @property
    def service(self): return self.data[0] if self.data else None
    @property
    def hex(self): return self.data.hex().upper()

class UdsClient:
    def __init__(self, link, pad=0x00, p2=1.0, stmin=0x00):
        self.link = link; self.pad = pad; self.p2 = p2; self.stmin = stmin

    def request(self, payload, tx_id, rx_id=None, ignore=frozenset()):
        self.link.drain()
        self._send(payload, tx_id)
        return self._receive(tx_id, rx_id, ignore)

    # ---- ISO-TP send ----
    def _send(self, payload, tx_id):
        payload = bytes(payload)
        if len(payload) <= 7:
            d = bytes([len(payload)]) + payload
            d += bytes(self.pad for _ in range(8 - len(d)))
            self.link.transmit(CanFrame(tx_id, d))
        else:
            n = len(payload)
            ff = bytes([0x10 | ((n >> 8) & 0x0F), n & 0xFF]) + payload[:6]
            self.link.transmit(CanFrame(tx_id, ff))
            bs, st = self._wait_fc(tx_id)
            idx, sn, sent = 6, 1, 0
            while idx < n:
                take = min(7, n - idx)
                cf = bytes([0x20 | (sn & 0x0F)]) + payload[idx:idx+take]
                cf += bytes(self.pad for _ in range(8 - len(cf)))
                self.link.transmit(CanFrame(tx_id, cf))
                idx += take; sn = (sn + 1) & 0x0F; sent += 1
                self._st_delay(st)
                if bs and sent == bs:
                    sent = 0; self._wait_fc(tx_id)

    def _wait_fc(self, tx_id):
        end = time.time() + self.p2
        while time.time() < end:
            for f in self.link.collect(0.02):
                if f.id == tx_id or not f.data: continue
                if (f.data[0] & 0xF0) == 0x30:
                    return (f.data[1] if len(f.data) > 1 else 0,
                            f.data[2] if len(f.data) > 2 else 0)
        return (0, 0)   # no FC -> stream all

    # ---- ISO-TP receive ----
    def _receive(self, tx_id, rx_id, ignore):
        end = time.time() + self.p2
        assembling = False; expected = 0; buf = b''; src = None
        while time.time() < end:
            for f in self.link.collect(0.02):
                if f.id == tx_id or f.id in ignore: continue
                if rx_id is not None and f.id != rx_id: continue
                if not f.data: continue
                kind = f.data[0] & 0xF0
                if kind == 0x00:                                  # single frame
                    n = f.data[0] & 0x0F
                    if len(f.data) >= 1 + n:
                        return Response(f.id, f.data[1:1+n])
                elif kind == 0x10:                                # first frame
                    expected = ((f.data[0] & 0x0F) << 8) | f.data[1]
                    buf = f.data[2:]; src = f.id; assembling = True
                    fc = bytes([0x30, 0x00, self.stmin]) + bytes(self.pad for _ in range(5))
                    self.link.transmit(CanFrame(tx_id, fc))
                elif kind == 0x20:                                # consecutive frame
                    if assembling and f.id == src:
                        buf += f.data[1:]
                        if len(buf) >= expected:
                            return Response(src, buf[:expected])
                # 0x30 (FC) ignored here
        return None   # timeout

    def _st_delay(self, st):
        if st == 0: return
        if st <= 0x7F: time.sleep(st / 1000.0)
        elif 0xF1 <= st <= 0xF9: time.sleep((st - 0xF0) / 10000.0)

    # ---- read-only UDS helpers ----
    def diagnostic_session(self, subfn, tx_id, rx_id=None):
        return self.request([0x10, subfn], tx_id, rx_id)
    def tester_present(self, tx_id, suppress=True):
        try: self.request([0x3E, 0x80 if suppress else 0x00], tx_id)
        except Exception: pass
    def read_did(self, did, tx_id, rx_id=None, ignore=frozenset()):
        return self.request([0x22, (did >> 8) & 0xFF, did & 0xFF], tx_id, rx_id, ignore)
