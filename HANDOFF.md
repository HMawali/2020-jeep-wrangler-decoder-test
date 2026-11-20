# HANDOFF — Tazer-free Jeep JL config (read where we left off)

**For the next Claude Code session (running on the Windows laptop).** This file is the
single source of truth for continuing the work. Read it first.

## The goal
Configure a **2020 Jeep Wrangler JL** body settings **directly over CAN** — using the
WeAct **USB2CANFD** adapter (slcan on COM3) + the **SGW bypass cable** — reproducing what
the **Z Automotive Tazer JL** dongle does, with **no dongle**. The Tazer firmware
(`tazerjl-11.4.7.zfw`) was reverse-engineered to learn its protocol and config model.
This is the owner's own vehicle, for interoperability (repo README: "no vehicle-security
defeat").

## Why the work is split across two machines
- The **Mac** (previous sessions) did the firmware reverse-engineering. It holds the
  decrypted firmware + full disassembly under `…/sniffer_firmware/analysis/` and a native
  macOS build under `…/sniffer_firmware/mac_app/`. **The Mac cannot be moved to the truck.**
- The **Windows laptop** (this and future sessions) is what physically connects to the
  truck. Everything needed to continue on the truck is **self-contained in this repo**
  under `tazer_config/` — you do **not** need the Mac to proceed.

## Status — what is DONE and VERIFIED
1. **Firmware decrypted.** AES-256-CBC, with a raw key+IV blob embedded in the ZPU
   companion app (not a passphrase). **The actual key/IV and the decrypted HEX are NOT in
   this repo on purpose** (a decryption key doesn't belong in a shared git repo) — they
   live only in the Mac's `…/sniffer_firmware/analysis/` + `decrypted/` from the RE
   sessions. **You don't need them for the truck work**; everything the tool needs is
   already distilled into `tazer_config/did_map.json` and this file.
2. **Protocol = standard UDS over ISO-TP / CAN.** Validated from the firmware's
   frame-construction code. Services it uses: `0x10` session, `0x11` reset, `0x14` clearDTC,
   `0x19` readDTC, `0x22` readDataByIdentifier, `0x2E` writeDataByIdentifier,
   `0x31` routineControl, `0x3E` testerPresent.
3. **There is NO SecurityAccess (0x27) → NO seed→key.** The Tazer does *not* do a seed/key
   handshake. Its access to body modules is purely **SGW bypass + extended session**. (This
   corrects the earlier assumption in `WRANGLER_CAN_REFERENCE.md` §7 that a seed/key would
   be required — it is not.)
4. **Config model.** Body settings live in FCA data identifiers **DIDs 0x0122–0x0149**
   (18 blocks). Read a block with `22 01 XX`, write with `2E 01 XX <data>`. Each individual
   setting is a **bit-field = (byte offset, bit mask)** inside a block. The full map (18 DIDs,
   61 fields) is in **`tazer_config/did_map.json`**.
5. **Module IDs** (from firmware flash table @0xf738): PCM `0x7E0`, **BCM `0x620`**,
   `0x7E1`, `0x747`, `0x74B`, `0x740`, `0x753`, `0x744`, `0x762`. Body config is almost
   certainly **BCM 0x620**. NOTE: `0x620` is in the `0x6xx` range the earlier Windows scans
   (`tools/disco.ps1`, 0x700–0x7FF only) never probed — which is why the BCM looked
   unreachable before. The new tool scans `0x600–0x7FF`.
6. **The app is built** — `tazer_config/` (pure Python, zero-dep, runs on this laptop).
   See `tazer_config/README.md`. It is **read-only**.

## ✅ RESOLVED (2026-11-21, Windows laptop, adapter on COM8)
**The open question below is ANSWERED: BCM 0x620 answers UDS on the 500 kbit/s CAN-C bus
(pins 6/14).** Response ID is **0x504** (not the guessed 0x628). Discover (`discover --bus s6`)
found body responders at request IDs **0x620→0x504, 0x740→0x4C0, 0x742, 0x744, 0x74A, 0x74B,
0x751, 0x75A, 0x75E** (all positive `02 7E 00` TesterPresent). The IHS bus (s4, pins 3/11) was
not wired at the time — but the BCM is reachable on **s6** regardless, so use s6.

**Config read WORKS:** `read --bus s6 --tx 0x620 --rx 0x504` → extended session `50 03…` OK,
**13/18 DIDs read** (saved to `before.json`). No-response DIDs on this BCM variant: 0x0126,
0x0130, 0x0134, 0x0144, 0x0145. Baseline values are in `before.json`.

**Remaining BCM-config work is now the label-discovery loop** (read → change one setting →
read → `diff`) to confirm each bit before any write. Writes stay LOCKED per below.

### Label-discovery attempts so far (2026-11-21) — method works, but 0x620 DIDs didn't move
- **Read reliability:** single `read` drops DIDs on the busy 500k bus (gets 7–13/18). Fix =
  **merge several reads** until 18/18 (scratchpad `fullread.py`; fold into the tool). With
  merged snapshots the read is **stable** — two independent full reads are byte-identical.
- **Negative results (no change in ANY of the 18 DIDs on 0x620):**
  - Rotary **headlight switch** AUTO↔on — expected (that's a live switch state / broadcast, not
    stored config), so not a valid config test.
  - Uconnect **"Flash Lights with Lock" ON→OFF** — a real stored setting, yet **no DID changed**.
- **So the customer settings are not appearing in 0x620's 0x0122–0x0149 on a live re-read.**
  Two hypotheses to resolve next:
  1. **Commit-on-sleep** — module writes NVM only on power-down. Test: change one setting, do a
     full **ignition/sleep cycle** (key off, door open, ~2 min), then read+diff.
  2. **Wrong module** — setting lives in the radio/HMI or another responder (0x740/0x742/0x744/
     0x74A/0x74B/0x751/0x75A/0x75E). Test: capture those modules' DIDs before/after a toggle.
- Snapshots saved (scratchpad, not committed): `snap_on.json` (baseline), `snap_flashoff.json`.

### (historical) The question this resolved
Does **BCM 0x620 answer UDS** at the OBD port with the SGW bypass in, and on **which bus**?
Static RE can't answer this — only the truck can. Run, in order:
```bat
python -I tazer_config\tazerctl.py ports
python -I tazer_config\tazerctl.py discover --port COM3 --bus s4   :: 125k IHS first
python -I tazer_config\tazerctl.py discover --port COM3 --bus s6   :: then 500k CAN-C
```
- If a responder shows up near `0x620` (reply likely `0x628`), that's the BCM → use that bus.
- If **both** buses are silent across 0x600–0x7FF, the BCM diag server is still gatewayed
  even with the star-bypass, and the next RE question becomes *how the Tazer's traffic is
  routed* (the bypass may need to present on a different conductor than where we sniff).

## Then: read the config
```bat
python -I tazer_config\tazerctl.py read --port COM3 --bus s4 --tx 0x620 --save before.json
```
(or `tazer_config\tazer_gui.py` for the GUI). This dumps all 18 blocks. Save the JSON.

## Why writes are LOCKED (do not remove this guard without the owner's OK)
We have the bit-field **map** but **not** verified setting **names** or safe **values** —
the firmware reaches each setting through menu dispatch tables that defeat static name
correlation (only one field, "HoodAlarm", auto-matched). **A wrong `2E` write can brick a
body module.** So:
- The tool implements **no** `0x2E`, **no** `0x27`, **no** `0x14` clear. Keep it that way
  until a field is proven.
- **Never fabricate** a write frame, a DID↔name mapping, or a seed/key. If unknown, say so.

## How a setting gets labelled (the safe unlock path)
1. `read … --save before.json`
2. Change **one** setting in the truck by its normal means (switch, menu, or a known-good
   tool), leave everything else alone.
3. `read … --save after.json`
4. `python -I tazer_config\tazerctl.py diff before.json after.json` → it prints the exact
   DID + byte + bit that moved. **That bit is that setting.**
5. Record it in `tazer_config/did_map.json` (`"label": "...", "confirmed": true`).
6. Repeat per setting. Once a field is confirmed, a write for it (set/clear that bit,
   write the block back) can be built and **bench-verified** before any live write.

## Map of this repo
- `tazer_config/` — the new read-only app (START HERE). `README.md` inside.
- `tools/` — earlier PowerShell/Python probes from hands-on sessions (`bcm_discover.py` is
  the cross-platform scanner; the `.ps1` tools are capture/inject/uds helpers).
- `WRANGLER_CAN_REFERENCE.md`, `CAN_CONTROL_FINDINGS.md` — decoded signals + earlier
  conclusions (note §7's "BCM unreachable / seed-key needed" is superseded by points 3 & 5
  above).
- `.claude/launch.json` — run configs: `tazer-gui`, `tazer-read`, `tazer-discover`.

## Safety recap
Vehicle PARKED, key RUN. Use **silent mode** (`sniff`) for anything exploratory. The read
path transmits only tiny well-formed UDS single frames. Do not scan/fuzz the 500k powertrain
bus casually (it carries live torque arbitration — see `CAN_CONTROL_FINDINGS.md` §7).
