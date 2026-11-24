#!/usr/bin/env python3
"""lightshow.py - sequence confirmed BCM lamp outputs into a light show (UDS 0x2F).

Forces lamps via InputOutputControl on BCM 0x620 in choreographed patterns, keeping one
diagnostic session alive, and RELEASES everything at the end (and on Ctrl-C / error).
Vehicle PARKED, ENGINE RUNNING (engine-off drops the BCM session). Confirmed lamp DIDs are
bench-mapped (see lamp_map.json).

  python -I tazer_config/lightshow.py --port COM8 [--bus s6] [--mode police|classic] [--duration 60]
"""
import argparse, json, sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canlink import SlcanLink, CanFrame, S_500K, S_125K
from uds import UdsClient

TX, RX = 0x620, 0x504
_HERE = os.path.dirname(os.path.abspath(__file__))

# bench-confirmed friendly names on this truck (2026-11-24)
LAMPS = {"MARK_L": 0xD1A4, "MARK_R": 0xD1A5, "BRAKE": 0xD1A6, "REV": 0xD1A8}


def _load_json(name):
    try:
        return json.load(open(os.path.join(_HERE, name)))
    except Exception:
        return {}


def all_lamp_dids():
    """Every lamp DID we might drive, from lamp_map.json (so we release them all)."""
    m = _load_json("lamp_map.json")
    dids = set(LAMPS.values())
    for k in m.get("lamps", {}):
        try: dids.add(int(k, 16))
        except Exception: pass
    return sorted(dids)


def did_of(x):
    """Accept a friendly name, a '0xD1A6' string, or an int."""
    if isinstance(x, int): return x
    if x in LAMPS: return LAMPS[x]
    return int(x, 16)


def sf(payload):
    d = bytes([len(payload)]) + bytes(payload); d += bytes(8 - len(d))
    return CanFrame(TX, d)


class Show:
    def __init__(self, link):
        self.link = link
        self.c = UdsClient(link)

    def session(self):
        for _ in range(8):
            r = self.c.diagnostic_session(0x03, TX, RX)
            if r and not r.is_negative:
                return True
            time.sleep(0.2)
        return False

    def _tx2(self, payload):
        # send twice for reliability on the busy bus (duplicate 2F is harmless)
        f = sf(payload); self.link.transmit(f); self.link.transmit(f)

    def force(self, did):
        self._tx2([0x2F, (did >> 8) & 0xFF, did & 0xFF, 0x03, 0x01])

    def release(self, did):
        self._tx2([0x2F, (did >> 8) & 0xFF, did & 0xFF, 0x00])

    def on(self, names):
        for n in names:
            self.force(LAMPS[n])

    def off(self, names):
        for n in names:
            self.release(LAMPS[n])

    def blink(self, names, on_s, off_s=None):
        """On for on_s, off for off_s (default = on_s)."""
        self.on(names); time.sleep(on_s)
        self.off(names); time.sleep(off_s if off_s is not None else on_s)

    def all_off(self):
        for d in all_lamp_dids():
            self.release(d); time.sleep(0.01)

    # ---- DID-level ops for the JSON (firmware) player ----
    def on_dids(self, dids):
        for d in dids: self.force(did_of(d))

    def off_dids(self, dids):
        for d in dids: self.release(did_of(d))

    def blink_dids(self, dids, times, on_s, off_s):
        for _ in range(max(1, times)):
            self.on_dids(dids); time.sleep(on_s)
            self.off_dids(dids); time.sleep(off_s)


def play_json(show, show_name, duration):
    """Replay a shows.json choreography (e.g. the firmware-extracted 'firmware' sequence)."""
    doc = _load_json("shows.json")
    tick = doc.get("tick_ms", 50) / 1000.0
    sh = doc.get("shows", {}).get(show_name)
    if not sh:
        print("# no show '%s' in shows.json (have: %s)" % (show_name, ", ".join(doc.get("shows", {}))))
        return
    alld = all_lamp_dids()
    print("# playing '%s' (%s)" % (show_name, sh.get("source", "")), flush=True)
    end = time.time() + duration
    while time.time() < end:
        for st in sh.get("steps", []):
            if time.time() >= end: break
            if "blink" in st:
                d = tick * st.get("delay", 10)
                show.blink_dids(st["blink"], st.get("times", 1), d, d)
            elif "on" in st:  show.on_dids(st["on"])
            elif "off" in st: show.off_dids(st["off"])
            elif st.get("all_on"):  show.on_dids(alld)
            elif st.get("all_off"): show.off_dids(alld)
            elif "wait" in st: time.sleep(tick * st["wait"])


L = ["MARK_L"]; R = ["MARK_R"]; ALL = ["MARK_L", "MARK_R", "BRAKE", "REV"]
REAR = ["BRAKE", "REV"]


def police(show, duration):
    end = time.time() + duration
    while time.time() < end:
        # 1) fast wig-wag
        for _ in range(26):
            show.blink(L, 0.05); show.blink(R, 0.05)
        # 2) very fast wig-wag
        for _ in range(40):
            show.blink(L, 0.03); show.blink(R, 0.03)
        # 3) double-tap each side (rapid)
        for _ in range(8):
            show.blink(L, 0.03, 0.03); show.blink(L, 0.03, 0.1)
            show.blink(R, 0.03, 0.03); show.blink(R, 0.03, 0.1)
        # 4) cross pattern: left+brake / right+reverse (fast)
        for _ in range(20):
            show.blink(["MARK_L", "BRAKE"], 0.05); show.blink(["MARK_R", "REV"], 0.05)
        # 5) all-strobe burst (machine-gun)
        for _ in range(30):
            show.blink(ALL, 0.025)
        # 6) rear flash while fronts strobe alternate
        for _ in range(16):
            show.on(REAR); show.blink(L, 0.035); show.blink(R, 0.035); show.off(REAR)
        if time.time() >= end:
            break


def classic(show, duration):
    end = time.time() + duration
    while time.time() < end:
        for _ in range(6):
            show.blink(L, 0.22); show.blink(R, 0.22)
        for _ in range(4):
            show.blink(["MARK_L", "MARK_R", "BRAKE"], 0.18)
        for _ in range(3):
            for n in ("MARK_L", "MARK_R", "BRAKE", "REV"):
                show.blink([n], 0.16, 0.0)
        for _ in range(8):
            show.blink(ALL, 0.09)
        show.blink(ALL, 1.0, 0.0)
        if time.time() >= end:
            break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--bus", default="s6")
    json_shows = list(_load_json("shows.json").get("shows", {}).keys())
    ap.add_argument("--mode", default="firmware", choices=["police", "classic"] + json_shows,
                    help="firmware = the Tazer's own extracted sequence; others are built patterns")
    ap.add_argument("--duration", type=float, default=60.0)
    a = ap.parse_args()
    bus = S_500K if a.bus.lower() == "s6" else S_125K
    link = SlcanLink(a.port); link.open(bus, listen_only=False)
    show = Show(link)
    if not show.session():
        print("session FAILED - is the ENGINE RUNNING? (engine-off drops the BCM session)")
        link.close(); return
    stop = False
    def ka():
        while not stop:
            try: show.c.tester_present(TX)
            except Exception: pass
            time.sleep(0.5)
    threading.Thread(target=ka, daemon=True).start()
    try: import winsound; winsound.Beep(1500, 250)
    except Exception: pass
    print(f"# {a.mode} show, {a.duration:.0f}s - filming window. Ctrl-C stops & releases.", flush=True)
    t0 = time.time()
    try:
        if a.mode == "police":   police(show, a.duration)
        elif a.mode == "classic": classic(show, a.duration)
        else:                     play_json(show, a.mode, a.duration)
        print(f"# show complete ({time.time()-t0:.0f}s)", flush=True)
    except KeyboardInterrupt:
        print("# stopped", flush=True)
    finally:
        show.all_off()
        stop = True; time.sleep(0.2)
        show.c.diagnostic_session(0x01, TX, RX)
        link.close()
        try: import winsound; winsound.Beep(600, 300)
        except Exception: pass


if __name__ == "__main__":
    main()
