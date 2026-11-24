#!/usr/bin/env python3
"""lightshow.py - sequence confirmed BCM lamp outputs into a light show (UDS 0x2F).

Forces lamps via InputOutputControl on BCM 0x620 in choreographed patterns, keeping one
diagnostic session alive, and RELEASES everything at the end (and on Ctrl-C / error).
Vehicle PARKED. Confirmed lamp DIDs are bench-mapped (see --map). Engine running = stable bus.

  python -I tazer_config/lightshow.py --port COM8 [--bus s6] [--loops 1]
"""
import argparse, sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canlink import SlcanLink, CanFrame, S_500K, S_125K
from uds import UdsClient

TX, RX = 0x620, 0x504
# bench-confirmed on this truck (2026-11-24)
LAMPS = {"MARK_L": 0xD1A4, "MARK_R": 0xD1A5, "BRAKE": 0xD1A6, "REV": 0xD1A8}


def sf(did, payload):
    d = bytes([len(payload)]) + bytes(payload); d += bytes(8 - len(d))
    return CanFrame(TX, d)


class Show:
    def __init__(self, link):
        self.link = link
        self.c = UdsClient(link)
        self.on = set()

    def session(self):
        for _ in range(6):
            r = self.c.diagnostic_session(0x03, TX, RX)
            if r and not r.is_negative:
                return True
            time.sleep(0.2)
        return False

    def force(self, did):
        self.link.transmit(sf(did, [0x2F, (did >> 8) & 0xFF, did & 0xFF, 0x03, 0x01]))
        self.on.add(did)

    def release(self, did):
        self.link.transmit(sf(did, [0x2F, (did >> 8) & 0xFF, did & 0xFF, 0x00]))
        self.on.discard(did)

    def set(self, names, dur):
        """Turn ON exactly these lamp names for dur seconds, then off."""
        want = {LAMPS[n] for n in names}
        for d in want:
            self.force(d)
        time.sleep(dur)
        for d in list(want):
            self.release(d)

    def all_off(self):
        for d in list(LAMPS.values()):
            self.release(d); time.sleep(0.01)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--bus", default="s6")
    ap.add_argument("--loops", type=int, default=1)
    a = ap.parse_args()
    bus = S_500K if a.bus.lower() == "s6" else S_125K
    link = SlcanLink(a.port); link.open(bus, listen_only=False)
    show = Show(link)
    if not show.session():
        print("session FAILED (engine running? bus awake?)"); link.close(); return
    stop = False
    def ka():
        while not stop:
            try: show.c.tester_present(TX)
            except Exception: pass
            time.sleep(0.6)
    threading.Thread(target=ka, daemon=True).start()
    try:
        import winsound; winsound.Beep(1500, 250)
    except Exception:
        pass
    try:
        for _ in range(a.loops):
            # 1) wig-wag markers
            for _ in range(6):
                show.set(["MARK_L"], 0.22); show.set(["MARK_R"], 0.22)
            # 2) all markers + brake flash together
            for _ in range(4):
                show.set(["MARK_L", "MARK_R", "BRAKE"], 0.18); time.sleep(0.18)
            # 3) chase
            for _ in range(3):
                for n in ("MARK_L", "MARK_R", "BRAKE", "REV"):
                    show.set([n], 0.16)
            # 4) rapid strobe all
            for _ in range(8):
                show.set(["MARK_L", "MARK_R", "BRAKE", "REV"], 0.09); time.sleep(0.09)
            # 5) finale
            show.set(["MARK_L", "MARK_R", "BRAKE", "REV"], 1.0)
        print("# show complete", flush=True)
    finally:
        show.all_off()
        stop = True; time.sleep(0.2)
        show.c.diagnostic_session(0x01, TX, RX)
        link.close()
        try:
            import winsound; winsound.Beep(600, 300)
        except Exception:
            pass


if __name__ == "__main__":
    main()
