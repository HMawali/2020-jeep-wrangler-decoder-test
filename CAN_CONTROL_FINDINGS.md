# 2020 Jeep Wrangler (JL) — CAN Control & Diagnostics Findings

A hands-on session with a **WeAct Studio USB2CANFD** adapter (slcan) through the OBD-II port,
behind an **SGW star-connector bypass**. This file focuses on **exact commands, bit maps, what is
controllable by injection, and the OBD-II/UDS procedures** — a companion to
[`WRANGLER_CAN_REFERENCE.md`](./WRANGLER_CAN_REFERENCE.md).

> Observed on one specific truck. Bit positions are very likely shared across 2018–2023 JL.
> Anything marked *status-only* is a read mirror, not a command. Raw CSV logs contain the VIN
> (`0x3E0`) — treat them as personal data.
>
> **Safety:** inject only while **parked**. The 500 kbit/s bus carries live PCM↔TCM torque
> arbitration — fuzzing it **set transmission DTCs** here (see §7). Keep exploratory work on the
> 125 kbit/s comfort bus, and default to listen-only (`M1`).

---

## 1. Adapter & connection

| Item | Value |
|---|---|
| Adapter | WeAct Studio USB2CANFD, firmware `V1.0.0.6` |
| USB ID | `VID_0483 & PID_5740` (STM32 virtual COM, Windows `usbser`, no driver install) |
| Port | Windows `COMx`, 115200 baud nominal (USB CDC) |
| Protocol | **slcan** (Lawicel / CANable ASCII) |

### slcan command sequences (this firmware)
```
Listen-only (safe):   C → M1 → S<rate> → O        # never ACKs or transmits
Transmit/diagnostics: C → M0 → S<rate> → O        # then send t/T frames
Close:                C
Read firmware:        V                            # -> "WeAct Studio V1.0.0.6..."
Read error register:  E
```
- Bitrate presets: **`S4` = 125 kbit/s**, **`S6` = 500 kbit/s** (persist across sessions).
- Reply `\r` = ok, `0x07` (BEL) = rejected/TX failed.
- Transmit frame format: `t` + `III` (11-bit id) + `L` (dlc) + data hex, e.g. `t2978F0FF0300000C24FF`.

---

## 2. Buses at the OBD-II port

| Bus | OBD pins | Bitrate (slcan) | Carries |
|---|---|---|---|
| **CAN-C** (powertrain) | **6** (H) / **14** (L) | **500 kbit/s** (`S6`) | engine, trans, ABS, ESS, diagnostics |
| **CAN-IHS** (interior/body) | **3** (H) / **11** (L) | **125 kbit/s** (`S4`) | climate, doors, switches, radio |

Both are classic CAN, 11-bit IDs. On this truck **only these two buses appear** at the OBD port;
every other bitrate was silent.

---

## 3. Decoded signals — CAN-C (500 kbit/s, pins 6/14)

| CAN ID | Bytes/bits | Signal | Decode |
|---|---|---|---|
| **0x025** | 0–1 (BE) | **Engine RPM** | `rpm = (b0<<8) | b1`. Idle ≈ 670–677. 100 Hz |
| **0x08B** | 4 × 16-bit | **Wheel speeds** | each 16-bit, **low 12 bits × 0.1 km/h**; upper nibble `0x4` = status |
| **0x085** | byte 1 | **Gear** | `DD`=P, `11..44`=1..4; split nibble (e.g. `21`) = shifting 1→2 |
| **0x085** | 3–4 (BE) | Vehicle speed | `× 0.1` (0 when parked) |
| **0x09D** | byte 0 | **Accelerator** | ~0–255 → scale to 0–100 % |
| **0x137** | byte 6 | **Auto Stop/Start (ESS) state** | `b6=0x00` → ON/armed, `b6=0x01` → OFF (latched) |
| 0x3E0 | 0–7 | VIN (multi-frame) | sensitive |

---

## 4. Decoded signals — CAN-IHS (125 kbit/s, pins 3/11)

### 4.1 Climate panel — `0x30E` (1000 ms), template `XX EE YY ZZ 07 FF 07 FF`
| Function | Byte.bit | Mask | Notes |
|---|---|---|---|
| **Recirculation** | byte 0, bit 4 | `0x10` | on when set |
| **Sync** | byte 0, bit 2 | `0x04` | on when set |
| **AC** | byte 2, bit 0 | `0x01` | on when set |

Baseline observed: `14 EE 1D 09 07 FF 07 FF` (AC on, recirc on, sync off). **0x30E is the panel
*display* frame** — flooding a modified copy (~10 ms) fights the module's 1 Hz frame and visibly
toggles the indicators (see §5.2).

### 4.2 Other IHS (status-only mirrors at the OBD port)
| CAN ID | Byte.bit | Signal |
|---|---|---|
| 0x2FA | byte 0, bit 0 | Driver door ajar (`1`=open) |
| **0x318** | byte 0 bit 0 / bit 1 | **Left / Right turn active — status only, hardwired, NOT injectable** |

---

## 5. Injection — what works

> Rule: a **soft-button** (press travels on the bus to a *different* consumer module) can be replayed.
> A **hardwired** function (switch → local module drives the output) only puts a *status mirror* on
> the bus and cannot be driven by injection.

### 5.1 Auto Stop/Start (ESS) toggle — ✅ verified
Soft-button on CAN-C. Replay toggles the ESS state at `0x137` repeatably, 0 bus errors.
```
Bus:    500 kbit/s (M0)
Frame:  ID 0x297, data F0 FF 03 00 00 0C 24 FF   (byte6 = 0x24 = bits 2+5)
slcan:  t2978F0FF0300000C24FF
Pulse:  ~100 Hz for ~300 ms (30 frames @ 10 ms), engine running
Verify: read 0x137 byte6 before/after → flips 0x00 (ON) ↔ 0x01 (OFF)
```
Clean single-ID replay — **set no DTCs** (unlike fuzzing).

### 5.2 Climate panel indicators — ✅ (display reacts)
Flood a modified `0x30E` on the **125 kbit/s** bus to toggle the panel indicators:
```
Bus:   125 kbit/s (M0)
AC off:      t30E814EE1C0907FF07FF   (byte2 bit0 cleared)
Recirc off:  t30E804EE1D0907FF07FF   (byte0 bit4 cleared)
Sync on:     t30E814EE1D0907FF07FF   (byte0 bit2 set)
Rate:  ~10 ms, a few seconds (fights the 1 Hz real frame → visible flicker/toggle)
```

### 5.3 Fuzz-responsive systems (125 kbit/s)
A full `0xFF` sweep of all ~92 IHS IDs (ignition on) visibly moved: **airflow direction, parking
sensors, traction control, display brightness, infotainment** — good targets for further bit-level
decode.

---

## 6. Injection — what does NOT work

| Function | Why |
|---|---|
| **Turn signals** | **Hardwired.** Injecting `0x318` (stalk input), the lamp-report frames, *and* a full `0xFF` fuzz of every IHS ID did nothing. The BCM owns the bulbs; no "blink" command is exposed to the OBD port. On CAN-C, `0x127` byte6 mirrors the tell-tale (`0x9A` off, `0x9E` left, `0x97/98` right) but is read-only. |
| Door lock / ajar | Hardwired; `0x2FA` is a status mirror |
| Hazards | No bus command found on either bus |

**Conclusion:** turn signals / exterior lighting are **not reachable from the OBD port** on this
truck — their control bus isn't gatewayed here.

---

## 7. OBD-II / UDS diagnostics (CAN-C, 500k)

Functional request `0x7DF` (or physical `0x7E0` engine / `0x7E1` transmission); responses on
`0x7E8` (engine) and `0x7E9` (transmission). ISO-TP single + multi-frame (flow control `30 00 00`).

### 7.1 Useful requests
All requests are ISO-TP single frames: `[len][service][pid…]` zero-padded to 8 data bytes, DLC `8`.

| Purpose | Service | slcan to `0x7DF` | Response |
|---|---|---|---|
| MIL + DTC count | `01 01` | `t7DF80201010000000000` | `41 01 A…`; `A&0x80`=MIL, `A&0x7F`=count |
| Live RPM | `01 0C` | `t7DF802010C0000000000` | `41 0C hi lo` → `/4` rpm |
| Live speed | `01 0D` | `t7DF802010D0000000000` | `41 0D v` km/h |
| Coolant temp | `01 05` | `t7DF80201050000000000` | `41 05 t` → `t-40 °C` |
| Stored DTCs | `03` | `t7DF80103000000000000` | `43 n <2-byte codes>` |
| Pending DTCs | `07` | `t7DF80107000000000000` | `47 …` |

DTC byte pair → code: first letter from top 2 bits (`00`=P,`01`=C,`10`=B,`11`=U), then nibbles.

### 7.2 Clearing codes (what actually works here)
- **Generic `04`** clears emissions codes only — it did **not** clear the TCM's enhanced `P1DD2`.
- **Enhanced clear** that worked:
```
Target:  TCM physical request 0x7E1 (responds 0x7E9)
Precondition: ENGINE OFF, KEY ON  (engine running → NRC 0x22 conditionsNotCorrect)
1) Extended session:  7E1 ← 10 03        (→ 7E9: 50 03…)
2) Clear all DTCs:    7E1 ← 14 FF FF FF   (UDS ClearDiagnosticInformation)
3) (optional) 7E1 ← 10 01, and generic 7DF ← 04
Verify: 01 01 → MIL off, count 0 on 7E8 & 7E9
```
- Only **engine (7E8)** and **transmission (7E9)** answer diagnostics at the OBD port. BCM/ABS/
  cluster are gatewayed (no direct seed/key from here — Security Access can't start).

---

## 8. Incident & lesson

Fuzzing the **500 kbit/s** bus set these (all cleared afterward):
- `P1DD2` — Torque Request Signal From TCM Denied (PCM↔TCM comms)
- `U0401` — Invalid data from PCM
- `U1412` — network / implausible data

These are **communication** faults from injection disrupting the real-time torque handshake — not
mechanical. **Do not fuzz CAN-C.** Reading diagnostics and passive capture on it are fine; do
injection experiments on the **125 kbit/s** comfort bus.

---

## 9. Tools used this session

A separate PyQt app (`can_sniffer`) was used alongside this repo's scripts:
- **Sniffer** (`main.py`): grouped/log live table, changed-byte highlight, ID filters, "hide all
  current IDs" to isolate a new message, ID labels, decoded-packet library, transmit (one-shot/
  periodic), record + timed playback.
- **Powertrain dashboard** (`dashboard.py`): live read-only RPM / speed / gear / accelerator gauges
  from §3, plus the ESS status and a guarded ESS toggle button (§5.1).
- Button-learning helper: capture baseline + press, diff per (id,byte,bit) to find a button's signal
  and classify momentary vs latch.

All decode in §3–§5 was confirmed against this adapter on the live vehicle.
