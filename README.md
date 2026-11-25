# Wrangler CAN RE

Reverse-engineering notes, tools, and captured data for the CAN buses of a **2020 Jeep Wrangler (JL)**,
using a WeAct Studio USB2CANFD adapter through the OBD-II port (with an SGW star-connector bypass).

> **Scope / ethics.** This is hobbyist reverse-engineering of my **own vehicle** for understanding,
> diagnostics, and interoperability. It contains **no** vehicle-security defeat: no Secure Gateway
> bypass method, no module Security Access (seed→key) algorithm, and no key-programming material.
> The injection examples are benign *soft-button* CAN messages (e.g. toggling auto stop-start), not
> anything that unlocks or reprograms a protected module.

## What's here

| Path | Contents |
|---|---|
| [`WRANGLER_CAN_REFERENCE.md`](WRANGLER_CAN_REFERENCE.md) | The main reference: bus pinout, decoded CAN IDs (both buses), UDS findings, injection notes, and the gateway/security boundary |
| [`CAN_CONTROL_FINDINGS.md`](CAN_CONTROL_FINDINGS.md) | Companion session notes: exact slcan commands and bit maps, climate-panel decode (`0x30E`), the ESS toggle frame, the turn-signal "not injectable" proof, and the OBD-II/UDS DTC read + enhanced-clear procedure |
| `tools/` | Reusable PowerShell + Python scripts (capture, UDS/ISO-TP client, bit/signal analysis, frame injection) |
| `can_dashboard/` | Live web dashboard (`server.py` + `dashboard.html`) showing RPM / speed / gear / pedal / wheels |
| `logs/` | Raw capture CSVs (`time_s,type,id,dlc,data`), one file per experiment |

## Buses (at the OBD-II port)

| Bus | OBD pins | Bitrate | Carries |
|---|---|---|---|
| CAN-C (powertrain) | 6 / 14 | 500 kbit/s | engine, trans, ABS, wheel speeds |
| CAN-IHS (body) | 3 / 11 | 125 kbit/s | doors, lights, switches, radio |

## Quick start — live dashboard

Requires Python 3 (standard library only) and the adapter on pins **6/14**:

```bash
python -I can_dashboard/server.py
```

Then open http://localhost:8765. See the reference doc for the slcan command details and every decoded signal.

## Note

This is a **private** repository. The files in `logs/` contain raw bus data from a specific vehicle
(including its VIN in the `0x3E0` broadcast) — keep it private or scrub those identifiers before sharing.

## Desktop Cockpit UI (no-build, Windows/macOS/Linux)
A tactile dark "cockpit" GUI over the Python backend — one command, **zero dependencies** (pure
stdlib HTTP bridge + a no-build HTML/JS frontend; no pip, no npm):
```
python run_ui.py            REM  or double-click run_ui.bat on Windows
```
It opens `http://127.0.0.1:8787/`. Pick **SIMULATOR** in the top bar to drive the whole UI offline
(the simulator speaks real ISO-TP so every read/write/0x2F/light-show path is exercised with no
truck), or **LIVE TRUCK** + COM port + `s6` when the WeAct USB2CANFD + SGW bypass are connected.

The bridge (`tazer_config/ui/server.py`) reuses the real `canlink`/`uds`/`did_catalog` modules and
the firmware catalogs — single source of truth, same gating as the CLI (dry-run default, read-first,
revert snapshots, engine-running interlock for 0x2F / light shows, confirmed-only actuations).

Workspaces: **Vehicle Settings** (37 cards + pending-changes cart + dry-run diff + polarity-verify
helper + tire calculator), **Live Functions** (confirmed actuation switches + boost/vac/RPM gauges +
bench-capture queue for unresolved features), **Light Show Studio** (20-lamp Jeep visualizer, show
runner with tick slider, single-lamp `iocontrol` tester), **Remap & Memory** (cruise-button remapper +
persistent automations, saved locally for the ESP32 port), **Diagnostics** (fullread snapshot + diff,
multi-module DTC 0x19/0x14, listen-only broadcast-bitmap watch). Bottom drawer = live UDS/CAN frame
inspector; top bar = adapter/bus/mode/vehicle-state.
