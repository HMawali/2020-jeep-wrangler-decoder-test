#!/usr/bin/env python3
"""
fullread.py - reliable BCM config snapshot by MERGING several reads.

On the busy 500k CAN-C bus a single `tazerctl read` drops DIDs (gets 7-13/18) because
ISO-TP multi-frame responses get stomped by broadcast traffic. This runs the read
repeatedly and merges the non-null DIDs until all are captured (or --passes reached),
producing a COMPLETE snapshot suitable for before/after diffing.

USAGE
  python -I tools/fullread.py --port COM8 --bus s6 --tx 0x620 --rx 0x504 --save snap.json [--passes 12]

Then diff two snapshots with:  python -I tazer_config/tazerctl.py diff a.json b.json
Read-only (delegates to tazerctl read). Vehicle PARKED, key RUN, SGW bypass in.
"""
import argparse, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TAZERCTL = os.path.join(REPO, "tazer_config", "tazerctl.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--bus", default="s6")
    ap.add_argument("--tx", default="0x620")
    ap.add_argument("--rx", default="0x504")
    ap.add_argument("--save", required=True)
    ap.add_argument("--passes", type=int, default=12)
    a = ap.parse_args()

    merged, order = {}, None
    for i in range(a.passes):
        tmp = os.path.join(tempfile.gettempdir(), f"_fullread_{i}.json")
        subprocess.run([sys.executable, "-I", TAZERCTL, "read", "--port", a.port, "--bus", a.bus,
                        "--tx", a.tx, "--rx", a.rx, "--save", tmp],
                       cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            d = json.load(open(tmp))
        except Exception:
            continue
        order = list(d["dids"].keys())
        for k, v in d["dids"].items():
            if v:
                merged[k] = v
        got = sum(1 for k in order if merged.get(k))
        print(f"  pass {i+1}: {got}/{len(order)} DIDs covered", flush=True)
        if got == len(order):
            break

    snap = {"module": a.tx, "bus": a.bus.upper(), "dids": {k: merged.get(k) for k in (order or [])}}
    json.dump(snap, open(a.save, "w"), indent=1)
    got = sum(1 for k in (order or []) if merged.get(k))
    total = len(order or [])
    print(f"# {a.save}: {got}/{total} DIDs captured" + ("  COMPLETE" if got == total and total else "  INCOMPLETE"))


if __name__ == "__main__":
    main()
