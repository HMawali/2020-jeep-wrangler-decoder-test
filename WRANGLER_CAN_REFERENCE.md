# 2020 Jeep Wrangler (JL) — CAN Reverse-Engineering Reference

Findings from a hands-on session using a **WeAct Studio USB2CANFD** adapter through the
OBD-II port, with a **Secure Gateway (SGW) star-connector bypass** installed.

> Everything here was observed on **one specific truck**. IDs and bit positions are very likely
> the same across 2018–2023 JL Wranglers, but treat anything marked *assumed* as unconfirmed.
> The VIN appears in some captures (`0x3E0`) — treat the raw CSV logs as personal data.

---

## 1. Hardware & setup

| Item | Value |
|---|---|
| Adapter | WeAct Studio USB2CANFD, firmware `V1.0.0.6` (reports as `WeAct Studio V1.0.0.6`) |
| USB ID | `VID_0483 & PID_5740` (STM32 virtual COM, Windows `usbser` driver — no install needed) |
| Port | **COM3**, 115200 baud (USB CDC, baud is nominal) |
| Protocol | **slcan** ("Lawicel"/CANable-style ASCII) |
| Gateway | FCA SGW bypassed at the **star connector** ("two square ports") |

### slcan command cheat-sheet (this firmware)
| Cmd | Meaning |
|---|---|
| `C` | Close channel |
| `M1` / `M0` | **Silent (listen-only)** / Normal mode — *set with channel closed* |
| `S0..SD` | Bitrate preset (`S4`=125k, `S6`=500k) |
| `Y1..Y5` | CAN-FD data bitrate (unused here; bus is classic CAN) |
| `O` | Open channel |
| `t`/`T` | Transmit 11-bit / 29-bit data frame |
| `E` | Read error register |
| response `\r` = ok, `0x07` (BEL) = rejected/error | |

- **Listen safely:** `C` → `M1` → `S<rate>` → `O`. In silent mode the adapter never ACKs or transmits.
- **Transmit / diagnostics:** `C` → `M0` → `S<rate>` → `O`, then send `t`/`T` frames.
- Bitrate setting **persists** in the firmware between sessions until changed.

---

## 2. Buses at the OBD-II port

| Bus | OBD pins | Bitrate | Carries | Traffic |
|---|---|---|---|---|
| **CAN-C** (powertrain) | **6** (H) / **14** (L) | **500 kbit/s** (`S6`) | engine, trans, ABS, wheel speeds | ~2200 frames/s, 146 IDs |
| **CAN-IHS** (interior/body) | **3** (H) / **11** (L) | **125 kbit/s** (`S4`) | doors, lights, switches, radio | ~215 frames/s, ~92 IDs |
| Ground | 4 or 5 | — | — | — |

All traffic observed was **classic CAN, 11-bit IDs** (no CAN-FD on either bus).

---

## 3. Decoded signals — CAN-C (500 kbit/s, pins 6/14)

| CAN ID | Bytes | Signal | Scaling / notes |
|---|---|---|---|
| **0x025** | 0–1 (BE) | **Engine RPM** | `value / 1` = rpm. Idle ≈ 670. 100 Hz. |
| **0x08B** | 0–1,2–3,4–5,6–7 | **4 wheel speeds** | each 16-bit, **low 12 bits**, `×0.1 km/h`. Upper nibble `0x4` = status flag. Order FL/FR/RL/RR *assumed*. |
| **0x085** | 1 | **Gear** | `DD`=P, `11`=1, `22`=2, `33`=3, `44`=4; shifting shows both nibbles (e.g. `21` = 1→2) |
| 0x085 | 3–4 | Vehicle speed (likely) | ≈ 2.05 × wheel value |
| **0x09D** | 0 | **Accelerator pedal** | raw ~0–100, exact scale unconfirmed |
| 0x07B | 2 | Pedal (mirror of 0x09D b0) | |
| 0x0AB | 2 | Gear (mirror of 0x085 b1) | |
| **0x297** | 6 | **Auto-stop/start (ESS) button press** | pulses to `0x24` (bits 2+5) for ~200 ms on press. **Injectable** — see §6 |
| **0x137** | 6–7 | **ESS state** | `00 17` = enabled, `01 0D` = disabled (latched) |
| 0x3E0 | 0–7 | **VIN** (ASCII fragments, multi-frame broadcast) | sensitive |

---

## 4. Decoded signals — CAN-IHS (125 kbit/s, pins 3/11)

| CAN ID | Bytes/bits | Signal | Notes |
|---|---|---|---|
| **0x2FA** | byte 0, bit 0 | **Driver door** | `1` = open, `0` = closed. Other doors likely adjacent bits (*assumed*) |
| **0x318** | byte 0, bit 0 | **Left turn active** | status only — **hardwired**, not injectable |
| **0x318** | byte 0, bit 1 | **Right turn active** | status only — **hardwired**, not injectable |
| **0x328** | 0–7 | **Radio/Uconnect display text** | UTF-16 text, burst at key-on |
| 0x1CE | byte 0 | System voltage-ish analog | drifts ~13.3–13.7 V range |

> The IHS bus is a **broadcast / status mirror** at the OBD port. You can read it, but most body
> functions are driven by hardwired switches (see §6), and no module here answers **diagnostics** (§7).

---

## 5. UDS / OBD-II diagnostics (CAN-C, 500k)

Request `0x7DF` (functional) or `0x7E0` (engine physical); responses on `0x7E8`+.
ISO-TP framing (single + multi-frame with flow control) implemented in `tools/uds.ps1`.

| Request | Meaning | Result on this truck |
|---|---|---|
| `01 00` | supported PIDs | `0x7E8` engine + `0x7E9` transmission respond |
| `01 0C` | RPM | `0A 78` → 670 rpm (matches 0x025) |
| `01 05` | coolant temp | `0x81` → 89 °C |
| `03` | stored DTCs | `43 00` → **no fault codes** |
| `09 00` | mode-9 support | advertises VIN/CalID/CVN |
| `09 02` / `22 F190` | VIN | **no response — gated** (VIN is secured; read it passively from `0x3E0`) |
| `10 03` | extended session | `0x7E9` enters it (`50 03…`); `0x7E8` declines (`7F 10 12`) |

Only the **emissions modules (engine `7E8`, transmission `7E9`)** expose a diagnostic endpoint
at the OBD port. ABS/BCM/cluster do **not** (see §7).

---

## 6. Injection — what works and what doesn't

**Rule of thumb:**
- ✅ **Soft-button messages** (a button whose press travels on the bus to a *different* consumer module) can be **replayed**.
- ❌ **Hardwired functions** (switch wired straight to the body module, which drives the output locally) **cannot** — the bus only carries a status report, and injecting it changes nothing.

| Function | Category | Injectable? | Evidence |
|---|---|---|---|
| **Auto-stop/start (ESS)** | soft button (`0x297` b6=`0x24`) | ✅ **Yes** | replaying it toggled `0x137` state off↔on, repeatably |
| Door ajar / door lock | hardwired | ❌ No | injecting `0x2FA` had no effect; lock switch is local |
| Turn signals (stalk) | hardwired | ❌ No | injecting `0x318` had no effect |
| Hazards | hardwired | ❌ No | no bus command found on either bus |

**ESS replay (verified):** on CAN-C, send `0x297` = `F0 FF 03 00 00 0C 24 FF` at ~100 Hz for ~300 ms
(engine running). See `tools/inject_ess.ps1` — it reads `0x137` before/after to confirm the toggle.

Our frames always **ACK with 0 bus errors**, confirming the star-bypass puts us on the real
multi-node bus — injection fails only because of *consumer architecture*, not connectivity.

---

## 7. BCM / Security Access — not reachable from OBD

The BCM (and other body modules) **do not answer diagnostic requests** injected at the OBD port.
Tried exhaustively:

| Method | CAN-C | IHS |
|---|---|---|
| 11-bit `7DF`/`7Ex` | PCM+TCM only | none |
| 29-bit functional `18DB33F1` | none | none |
| 29-bit physical sweep `18DAxxF1` | none | none |

**Conclusion:** BCM diagnostics are **gatewayed** — a dealer tool (wiTECH) reaches the BCM *through*
the SGW's diagnostic routing, not by direct bus addressing. The star-bypass restores broadcast
**read** access but not the BCM's diagnostic *server*. Therefore **Security Access can't even start**
from here, and no seed/key handshake is possible.

This is also why aftermarket programmers (e.g. Z Automotive Tazer) differ from what we can do: they
(a) hold FCA's per-module **seed→key** algorithms and (b) write **configuration** to the body/cluster/
radio modules via a routed diagnostic path — not by spoofing status. For live tricks they emulate
**soft-button** CAN messages (the ESS category above), which is the one thing reproducible here.

---

## 8. Tools (copied into `tools/`)

| Script | Purpose |
|---|---|
| `capture.ps1` | Silent-mode capture to CSV (`-Rate 4|6 -Seconds N -Out file.csv`) |
| `uds.ps1` | ISO-TP/UDS client (`-Request 0100 -TxId 7DF`) |
| `disco.ps1` / `disco29.ps1` / `disco29phys.ps1` | Diagnostic address discovery (11-bit / 29-bit functional / 29-bit physical) |
| `inject.ps1` | Generic frame injector (`-Frame t... -Seconds N`) |
| `inject_ess.ps1` | ESS button replay with before/after state verify |
| `toggles.py` / `bits.py` / `bit_timeline.py` | Find bits that change / follow an on-off pattern |
| `speed_trace.py` / `find_signal.py` / `active.py` | Signal-vs-action correlation helpers |
| `raw.py` | Dump raw frames for chosen IDs at intervals |

Live dashboard: `can_dashboard/server.py` + `dashboard.html` (powertrain gauges; run on pins 6/14).
Launch via `.claude/launch.json` → `python -I can_dashboard/server.py`, open http://localhost:8765.

### Raw capture logs (in project root)
`wrangler_can_500k.csv`, `wrangler_rpm_test.csv`, `wrangler_speed_test.csv`, `wrangler_ess_test.csv`,
`wrangler_ihs_*_test*.csv`, `wrangler_keyon_test.csv` — one row per frame (`time_s,type,id,dlc,data`).

---

## 9. Safety notes

- Default to **silent mode (`M1`)** for anything exploratory — it can't disturb the bus.
- Only switch to **normal mode (`M0`)** to inject or run diagnostics; watch the error register (`E`).
- Keep the vehicle **parked**; ESS replay needs the engine running, diagnostics only need key-in-RUN.
- Injection here is reversible (real modules keep broadcasting ground truth), but never inject while driving.
