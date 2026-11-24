# tazer_config — Jeep JL body-config tool (Windows / cross-platform)

Talks to the 2020 Jeep Wrangler JL **directly over CAN** via the WeAct **USB2CANFD**
(slcan) + **SGW bypass** — no Tazer dongle. Protocol + config model were
reverse-engineered from the decrypted Tazer JL 11.4.7 firmware. **Read-only** for now
(writing is deliberately not implemented — see `../HANDOFF.md`).

Pure Python 3, **zero dependencies** (Tkinter ships with Python on Windows).

## Run on the Windows laptop
Vehicle **PARKED**, key in **RUN**, **SGW bypass installed**, adapter on **COM3**.

```bat
cd 2020-jeep-wrangler-decoder-test

:: 1) confirm the adapter and which COM port
python -I tazer_config\tazerctl.py ports

:: 2) does the BCM answer?  (benign TesterPresent probe over 0x600-0x7FF)
python -I tazer_config\tazerctl.py discover --port COM3 --bus s4

:: 3) read all 18 config blocks from the BCM (0x620)
python -I tazer_config\tazerctl.py read --port COM3 --bus s4 --tx 0x620 --save before.json

:: GUI version of the same thing
python -I tazer_config\tazer_gui.py
```

## Find a customer-setting's bit the SAFE way (listen-only, no write)
The config is also broadcast as free-running frames (community sheet): `0x3B3/0x3B4/0x3C2` =
Customer Settings Menu bitmap, `0x3E8-0x3EB` = Vehicle Config bitmap. `watch` captures them in
silent mode and prints byte/bit changes live — toggle one menu setting and watch the bit move:
```bat
python -I tazer_config\tazerctl.py watch --port COM3 --bus s6
:: (then change ONE setting in the Uconnect menu; the moved bit is that setting)
:: narrow to just the Customer Settings Menu bitmaps:
python -I tazer_config\tazerctl.py watch --port COM3 --bus s6 --ids 3B3,3B4,3C2
```
`watch` is listen-only (M1) — it cannot ACK or transmit, so it can't disturb the bus.

## Writing a setting (DANGEROUS — gated)
`write` does a read-modify-write (UDS `2E`). It is **dry-run by default** (prints the exact frame
and stops); only `--yes` transmits. It always reads the block first and saves a revert file.
```bat
:: SAFE first test — write the block back UNCHANGED to prove the write path works, change nothing:
python -I tazer_config\tazerctl.py write --port COM3 --bus s6 --tx 0x620 --rx 0x504 --did 0x0146 --verify --yes

:: flip one bit (dry-run first, then --yes), 0146/0147 = Customer Settings Menu = menu-reversible:
python -I tazer_config\tazerctl.py write --port COM3 --bus s6 --tx 0x620 --rx 0x504 --did 0x0146 --byte 7 --mask 0x80 --value 0x80
python -I tazer_config\tazerctl.py write ...same... --yes
python -I tazer_config\tazerctl.py write --revert revert_0146.json --yes   :: undo
```
A wrong `2E` can brick a body module. Keep the read-first / dry-run / revert discipline.

`--bus s4` = 125k CAN-IHS (body, pins 3/11, default). `--bus s6` = 500k CAN-C (pins 6/14).

## Actuations / light show — forcing BCM outputs (DANGEROUS — gated)
The Tazer flashes lamps with **UDS `0x2F` InputOutputControl** (not `0x31`). Firmware-confirmed
shape (lamp driver word `0x3e50` → BCM `0x620`): `2F <did> 03 <state>` to force, `2F <did> 00` to
release. Lamp DIDs are the **`0xD1xx`** family (`0xD1A8/A9`, `0xD1B2/B3`, `0xD1C2`, community `0xD1BE`).

`iocontrol` forces one output, holds, then **auto-releases** — use it to map which DID = which lamp.
Dry-run by default; only `--yes` transmits. Parked, key **RUN**.
```bat
:: dry-run first (prints the exact 2F frames, sends nothing):
python -I tazer_config\tazerctl.py iocontrol --port COM3 --bus s6 --did 0xD1C2

:: actually force it for 2s then auto-release (watch which lamp lights):
python -I tazer_config\tazerctl.py iocontrol --port COM3 --bus s6 --did 0xD1C2 --state 01 --hold 2 --yes
```
The state byte and exact release form are **not firmware-confirmed** — verify on the bench. Once each
`0xD1xx`→lamp is mapped, chaining forces with delays = a light show (sequencer can then be built).

## Labelling a setting (how writes get unlocked safely)
```bat
python -I tazer_config\tazerctl.py read --port COM3 --tx 0x620 --save before.json
:: now change ONE setting in the truck by its normal means, then:
python -I tazer_config\tazerctl.py read --port COM3 --tx 0x620 --save after.json
python -I tazer_config\tazerctl.py diff before.json after.json
```
`diff` prints exactly which DID byte/bit moved → that bit **is** that setting. Record it
in `did_map.json` (`label`, `confirmed: true`). Only then is a write for it safe to build.

## Files
| file | role |
|---|---|
| `canlink.py` | serial (Windows ctypes + POSIX) + slcan link |
| `uds.py` | ISO-TP (single+multi-frame+flow control) + UDS client (read-only helpers) |
| `did_catalog.py` + `did_map.json` | the 18 config DIDs and their bit-fields (from firmware) |
| `tazerctl.py` | CLI: `ports` / `sniff` / `discover` / `read` / `watch` / `write` / `diff` |
| `tazer_gui.py` | Tkinter GUI (read + save) |

## Light show (firmware-extracted)
`lightshow.py` plays choreographies from `shows.json`. The **`firmware`** show is the Tazer's own
opening sequence, extracted from the decrypted firmware (lamp driver `set_output` word 0x3e4e,
`blink_step` word 0x5b38, runner word 0x5b7a); lamp DIDs/names are in `lamp_map.json`.
```bat
python -I tazer_config\lightshow.py --port COM3 --bus s6 --mode firmware --duration 30
```
Vehicle PARKED, **ENGINE RUNNING** (engine-off drops the BCM session). It keeps one session alive
and RELEASES every lamp on exit/Ctrl-C. Only BCM `0xD1xx` lamps are driven (the firmware also uses
`0xD0xx` outputs on module 0x74A/0x74B, which this BCM-only tool omits). `tick_ms` in shows.json
scales step timing (firmware ms/tick unknown — tune by eye).
