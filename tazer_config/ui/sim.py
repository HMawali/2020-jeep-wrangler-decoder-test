#!/usr/bin/env python3
"""
sim.py - offline Simulator backend for the Tazer-JL cockpit UI.

SimLink mimics the SlcanLink interface (open/close/drain/transmit/collect) but instead of
talking to real hardware it implements a tiny ISO-TP "ECU" in memory. Because it exposes the
exact same link surface, the REAL `UdsClient` from uds.py runs unmodified on top of it - so the
whole UI (sessions, 0x22 reads, 0x2E read-modify-write, 0x2F lamp forces, 0x19/0x14 DTCs,
multi-frame ISO-TP with flow control) is exercised end to end on a laptop with no truck.

Nothing here is a vehicle write - it only mutates in-memory blocks, so it is 100% safe and is
the right place to polish menus, diffs and light-show previews.
"""
import os, sys, time, random, threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from canlink import CanFrame  # noqa: E402

# request-id -> response-id (from firmware 0xf738 table / bench)
RESP_ID = {0x620: 0x504, 0x7E0: 0x7E8, 0x740: 0x4C0, 0x742: 0x4C2, 0x744: 0x4C4,
           0x74A: 0x4CA, 0x74B: 0x4CB, 0x747: 0x74F, 0x7E1: 0x7E9}


def resp_id_for(req):
    return RESP_ID.get(req, (req | 0x08) if 0x700 <= req <= 0x7FF else req - 0x11C)


class SimLink:
    """In-memory ISO-TP ECU that looks like an SlcanLink."""

    def __init__(self, seed_blocks=None):
        self.listen_only = False
        self._q = []                 # frames waiting to be collect()'d
        self.blocks = {}             # did -> bytearray (config block storage)
        self.forced = {}             # did -> (option, state bytes)  (0x2F outputs)
        self._rxpart = {}            # req_id -> partial multiframe payload
        self._rxexp = {}
        self._t0 = time.time()
        self._last_bcast = 0.0
        self._lock = threading.Lock()
        self.dtc = {                 # module -> list of sample DTC records (status 0x08=confirmed)
            0x620: ['C210E-08', 'B1D15-08'], 0x7E0: ['P0456-08'], 0x742: [],
            0x740: [], 0x744: [], 0x74A: [], 0x74B: [],
        }
        if seed_blocks:
            for k, v in seed_blocks.items():
                self.blocks[int(k, 16) if isinstance(k, str) else k] = bytearray(v)

    # ---- SlcanLink surface ----
    def open(self, bitrate=None, listen_only=False):
        self.listen_only = listen_only

    def close(self):
        pass

    def drain(self):
        with self._lock:
            self._q = []

    def transmit(self, frame):
        if self.listen_only:
            raise RuntimeError('refusing to transmit: link is in listen-only (M1) mode')
        self._handle(frame)

    def collect(self, dwell):
        time.sleep(min(dwell, 0.01))
        self._emit_broadcast()
        with self._lock:
            out = self._q
            self._q = []
        return out

    # ---- helpers ----
    def _push(self, cid, data):
        d = bytes(data)
        d = d + bytes(8 - len(d)) if len(d) < 8 else d[:8]
        with self._lock:
            self._q.append(CanFrame(cid, d))

    def _send_isotp(self, cid, payload):
        payload = bytes(payload)
        if len(payload) <= 7:
            self._push(cid, bytes([len(payload)]) + payload)
            return
        n = len(payload)
        self._push(cid, bytes([0x10 | ((n >> 8) & 0x0F), n & 0xFF]) + payload[:6])
        idx, sn = 6, 1
        while idx < n:
            take = min(7, n - idx)
            self._push(cid, bytes([0x20 | (sn & 0x0F)]) + payload[idx:idx + take])
            idx += take
            sn = (sn + 1) & 0x0F

    def _handle(self, frame):
        req = frame.id
        kind = frame.data[0] & 0xF0
        if kind == 0x30:
            return  # flow control from client during our multiframe response - ignore
        if kind == 0x00:
            n = frame.data[0] & 0x0F
            self._service(req, bytes(frame.data[1:1 + n]))
        elif kind == 0x10:
            total = ((frame.data[0] & 0x0F) << 8) | frame.data[1]
            self._rxpart[req] = bytearray(frame.data[2:])
            self._rxexp[req] = total
            # flow control: clear-to-send
            self._push(resp_id_for(req), bytes([0x30, 0x00, 0x00]))
        elif kind == 0x20:
            if req in self._rxpart:
                self._rxpart[req] += frame.data[1:]
                if len(self._rxpart[req]) >= self._rxexp[req]:
                    payload = bytes(self._rxpart.pop(req)[:self._rxexp.pop(req)])
                    self._service(req, payload)

    def _block(self, did):
        if did not in self.blocks:
            self.blocks[did] = bytearray(8)
        return self.blocks[did]

    def _service(self, req, payload):
        rid = resp_id_for(req)
        if not payload:
            return
        svc = payload[0]
        if svc == 0x3E:
            self._send_isotp(rid, bytes([0x7E, 0x00]))
        elif svc == 0x10:
            sub = payload[1] if len(payload) > 1 else 0x03
            self._send_isotp(rid, bytes([0x50, sub, 0x00, 0x32, 0x01, 0xF4]))
        elif svc == 0x11:
            self._send_isotp(rid, bytes([0x51, payload[1] if len(payload) > 1 else 1]))
        elif svc == 0x22:
            did = (payload[1] << 8) | payload[2]
            self._send_isotp(rid, bytes([0x62, payload[1], payload[2]]) + bytes(self._block(did)))
        elif svc == 0x2E:
            did = (payload[1] << 8) | payload[2]
            self.blocks[did] = bytearray(payload[3:])
            self._send_isotp(rid, bytes([0x6E, payload[1], payload[2]]))
        elif svc == 0x2F:
            did = (payload[1] << 8) | payload[2]
            opt = payload[3] if len(payload) > 3 else 0
            state = bytes(payload[4:])
            if opt == 0x00:
                self.forced.pop(did, None)
            else:
                self.forced[did] = (opt, state)
            self._send_isotp(rid, bytes([0x6F, payload[1], payload[2], opt]) + state)
        elif svc == 0x19:
            recs = []
            for d in self.dtc.get(req, []):
                code = d.split('-')[0]
                b = int(code[1:], 16) if len(code) == 5 else 0
                recs += [(b >> 8) & 0xFF, b & 0xFF, 0x08]
            self._send_isotp(rid, bytes([0x59, 0x02, 0xFF]) + bytes(recs))
        elif svc == 0x14:
            self.dtc[req] = []
            self._send_isotp(rid, bytes([0x54]))
        elif svc == 0x01:
            # OBD mode 01 (live data) - minimal positive
            self._send_isotp(rid, bytes([0x41, payload[1] if len(payload) > 1 else 0, 0x00, 0x00]))
        else:
            self._send_isotp(rid, bytes([0x7F, svc, 0x11]))  # serviceNotSupported

    # ---- broadcast + telemetry (for the UI's live console / gauges) ----
    def _emit_broadcast(self):
        now = time.time()
        if now - self._last_bcast < 0.25:
            return
        self._last_bcast = now
        # Customer-Settings / vehicle-config bitmaps (static-ish)
        for cid in (0x3B3, 0x3B4, 0x3C2, 0x3E8):
            self._push(cid, bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))

    def telemetry(self):
        """Fake but plausible live cluster data for the UI gauges."""
        t = time.time() - self._t0
        boost = max(0.0, 6.5 * abs((t % 6) / 3 - 1))        # 0..6.5 psi sweep
        vac = max(0.0, 20.0 - boost * 3)
        rpm = int(800 + 2800 * abs((t % 8) / 4 - 1))
        return {'boost_psi': round(boost, 1), 'vac_inhg': round(vac, 1), 'rpm': rpm,
                'speed_mph': round(max(0, 30 * ((t % 10) / 10)), 1)}

    def lamp_states(self):
        return {('0x%04X' % did): True for did in self.forced}
