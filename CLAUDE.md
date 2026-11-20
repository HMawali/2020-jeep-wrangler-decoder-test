# Project context for Claude Code

This repo is hobbyist reverse-engineering of the owner's **own** 2020 Jeep Wrangler JL,
for diagnostics and interoperability (no vehicle-security defeat).

**Before doing anything, read [`HANDOFF.md`](HANDOFF.md)** — it is the running state of the
work and tells you exactly where the last session stopped and what to do next.

## TL;DR
- Goal: configure JL body settings **directly over CAN** (WeAct USB2CANFD on COM3 + SGW
  bypass), reproducing the Z Automotive Tazer JL dongle — **no dongle**.
- The protocol + config model were reverse-engineered from the Tazer firmware: standard
  **UDS/ISO-TP**, config in **DIDs 0x0122–0x0149** (read `22 01 XX`, write `2E 01 XX`),
  body module **BCM = 0x620**, and there is **no seed→key** (access = SGW bypass + extended
  session).
- The tool is in **`tazer_config/`** (pure Python, zero-dep). It is **READ-ONLY**.

## Hard rules
- **Do not implement writes (`0x2E`), SecurityAccess (`0x27`), or DTC clears (`0x14`)** until
  a setting is confirmed by the read→change→re-read **diff** workflow in HANDOFF.md. A wrong
  write can brick a body module.
- **Never fabricate** a CAN frame, a DID↔setting-name mapping, or a seed/key. If a value is
  not verified, say it's unverified.
- Vehicle PARKED, key RUN. Prefer silent/listen-only for exploration. Don't fuzz the 500k
  powertrain bus.

## Run (Windows laptop)
`python -I tazer_config\tazerctl.py discover --port COM3 --bus s4` then `… read … --save before.json`,
or the GUI `python -I tazer_config\tazer_gui.py`. See `tazer_config/README.md`.
