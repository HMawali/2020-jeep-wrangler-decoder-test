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
- `write` (UDS `0x2E`) and `iocontrol` (UDS `0x2F` forced output, auto-releases) now exist but are
  **hard-gated** (dry-run default, reads/saves revert where applicable, only `--yes` transmits).
  Keep that discipline; do **not** loosen it, and do **not** add `0x27` SecurityAccess or `0x14`
  DTC-clear. A wrong write can brick a body module; a forced output actuates real hardware.
- **Never fabricate** a CAN frame, a DID↔setting-name mapping, a write value, or a seed/key. If a
  value is not verified, say it's unverified. Writes must be read-modify-write from a live read.
- Vehicle PARKED, key RUN. Prefer silent/listen-only for exploration. Don't fuzz the 500k
  powertrain bus.

## Run (Windows laptop)
`python -I tazer_config\tazerctl.py discover --port COM3 --bus s4` then `… read … --save before.json`,
or the GUI `python -I tazer_config\tazer_gui.py`. See `tazer_config/README.md`.
