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
