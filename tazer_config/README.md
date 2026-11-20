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

`--bus s4` = 125k CAN-IHS (body, pins 3/11, default). `--bus s6` = 500k CAN-C (pins 6/14).

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
| `tazerctl.py` | CLI: `ports` / `sniff` / `discover` / `read` / `diff` |
| `tazer_gui.py` | Tkinter GUI (read + save) |
