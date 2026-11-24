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

### Label-discovery — session 2026-11-21 (Windows laptop, COM8). Method works; 0x620 DIDs are DEALER proxi, not customer menu
- **Read reliability:** a single `read` drops DIDs on the busy 500k bus (7–13/18). **Fix merged
  into the repo: `tools/fullread.py`** — runs the read repeatedly and merges non-null DIDs until
  18/18. Use it for every before/after snapshot:
  `python -I tools/fullread.py --port COM8 --bus s6 --tx 0x620 --rx 0x504 --save snap.json`
  With merged snapshots the read is **stable** — independent full reads are byte-identical.
- **Negative results — NO change in any of the 18 DIDs on 0x620, across these tests:**
  - Rotary **headlight switch** AUTO↔on — a live switch state/broadcast, not stored config (not a valid config test).
  - Uconnect **"Flash Lights with Lock" ON→OFF** — a real customer setting; **no DID moved**.
  - Same setting **re-checked after a full ignition/sleep cycle** — still **no change** → **commit-on-sleep RULED OUT**.
  - A 20 s listen-only sniff during a toggle saw **no UDS/diagnostic frames** on 500k (toggle not
    independently confirmed, so treat as tentative) → customer settings look **radio/HMI-local**, not UDS.
- **CONCLUSION:** the firmware-derived DIDs `0x0122–0x0149` on 0x620 hold the **hidden/dealer
  "proxi" configuration** (what the Tazer changes) — **not** the customer Uconnect-menu settings.
  So those bits **cannot be labelled by toggling the factory menu**; the menu doesn't change them.

### Label-discovery — session 2026-11-21 (Mac): Option 1 DONE — community cross-reference
Found the community resource and cross-referenced it. **Our work is independently
quadruple-confirmed**: the community lists BCM as **req 0x620 / resp 0x504 on CAN-C**, exactly
what the Windows session measured.
- **Sources (cite these; forum/community = untrusted, so labels are unconfirmed):**
  - GitHub `rstellhorn/jeep-jl-powernet-scripts` (scripts; BCM 620/504; actuations via 0x2F).
  - Community Google Sheet "CAN IDs … 2018+ JL" tab **UDS Modules**:
    `docs.google.com/spreadsheets/d/16ypMADKinBBnH1pOY4-gMmVRjeR85fYplpV12aCHJC4`
  - Forum thread 82139 (jlwranglerforums, 403s to automated fetch; open in a browser).
- **Block-level names added to `tazer_config/did_map.json`** (new `block_label` per DID,
  `block_confirmed:false`). 14/18 of our DIDs are named by the sheet:
  `0122-0126`=Vehicle Configuration 1-5, `0130`=ECU Config: Harness Pins, `0131/0132`=ECU Config,
  `0134`=ECU Config: **Wireless**, `0141`=Mixed Functions, `0144`=**Suspension**, `0145`=ECU Config 7,
  **`0146`/`0147`=Vehicle Customer Settings Menu 1/2 (CSM1/CSM2)**. Not in sheet: `013B 013C 013E 0149`.
  These are BLOCK labels only — per-bit field labels in did_map.json are still `null`/unconfirmed.
- **KEY REFRAME of the "customer settings" puzzle:** the sheet shows the config is also mirrored
  as **free-running broadcast frames** — `0x3E8-0x3EB`=Vehicle Config Bitmap 1-4 ("content appears
  identical" to the DID reads), and **`0x3B3 / 0x3B4 / 0x3C2`=Customer Settings Menu Bitmap 1-3**
  (same ID on CAN-C and CAN-IHS). That's why the Windows toggle-sniff saw "no UDS frames" — customer
  settings broadcast as these bitmaps, not as UDS. They can be read **passively in listen-only mode**
  (zero brick risk, no diagnostic session).
- **Module map (for the other responders):** cluster/IPC `742/4C2`, RF-hub-suspected `740/4C0`,
  airbag `744/4C4`, radio `7BF/53F` (CAN-IHS), HVAC `783/503` (CAN-IHS).

### >>> NEXT SESSION: how to get per-BIT labels (block names are done) <<<
Two independent tracks; the diff tooling is ready (`tools/fullread.py` + `tazerctl.py diff`):

**A. Truck, SAFE (listen-only) — find customer-setting bits via broadcast bitmaps.**
   Use the `watch` command (listen-only M1, cannot disturb the bus):
   ```
   python -I tazer_config\tazerctl.py watch --port COMx --bus s6
   ```
   It prints a baseline for each watched bitmap ID (`0x3B3/0x3B4/0x3C2` CSM, `0x3E8-0x3EB`+ vehicle
   config, `0x3F0/0x3F2` ECU config) then shows **live byte/bit changes**. Change ONE Uconnect-menu
   setting and the moved bit prints immediately. Because the broadcast "appears identical" to the DID
   read, that same bit maps back to the `0146/0147` (CSM) or `0122-0126` DID. NO write, NO UDS session.
   (`--ids 3B3,3B4,3C2` narrows it; `--save x.json` + `tazerctl.py diff` compares across key cycles.)
   If a bitmap ID never shows a baseline, it may only broadcast at key-on — cycle the key. If none of
   these IDs appear on s6, try `--bus s4` (they are listed on both CAN-C and CAN-IHS).

**B. Per-bit labels for the hidden proxi config (dealer settings).** Still needs one of:
   - A **known-good writer** (AlfaOBD/wiTECH/Tazer): change one dealer setting, `fullread`
     before/after + `diff` → confirmed bit. Gold standard.
   - **Correlate** the broadcast config bitmaps (`0x3E8…`, identical to the DID bytes) against named
     AlfaOBD settings, once we have an AlfaOBD byte/bit list. **Do NOT fabricate** a per-bit mapping;
     only record ones backed by a diff or a citable source.

- Raw vehicle snapshots stayed on the Windows laptop (owner chose not to commit vehicle config).
  Re-capture with `fullread.py` when needed.

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

### Label-discovery — session 2026-11-21 (Mac): firmware extraction (the "emulation" ask)
Full-system simavr emulation wasn't the pragmatic win (simavr needs an untrusted tap + its
AT90CAN support is uncertain, and the handlers are async/menu-driven). Instead I did a targeted
dataflow extraction of the firmware's own argument setup at all **85 call sites** of the config
wrapper (byte 0x8c00 / word 0x4600), which takes `R25:R24=DID, R22=byte, R20=mask, R18=value,
R16=op`. Results:
- The extracted **(DID, byte, mask)** at each site **matches `did_map.json` exactly** — the
  config map is now confirmed by two independent methods (Ghidra script + this extractor).
- Same **18** `0x01xx` DIDs; plus two extra DID families `0xF010/0xF011` the Tazer also touches
  (left out of our body-config map for now).
- **KEY:** the write **value** (`R18`) and **op** (`R16`) are usually `mov`'d from the handler's
  *inputs* — i.e. the value is the **user's menu selection at runtime, not a static constant**.
  So there is no fixed "magic value" to replay. The correct, safe way to write a setting is a
  **read-modify-write from the live block** (read DID, flip the (byte,mask) bits, write back).
  That is exactly what the new `write` command does.
- The builder at word 0x4063 is the **read** sender (hardcodes `03 22 <DID>`); the write/2E goes
  through the async RX handler doing RMW with the stashed (byte,mask,value). We don't replay the
  firmware's internal 2E routine — we build a standard UDS `2E 01 XX <block>` ourselves from the
  live read, which is simpler and safer.

## Writes: now IMPLEMENTED but HARD-GATED (owner-directed)
The tool has a `write` command (UDS `2E`, read-modify-write). It is **not** a free write:
- **Dry-run by default** — it prints the exact `2E` frame it *would* send and stops. It only
  transmits with `--yes`.
- It **always READs the block first** (aborts if the read fails) and **saves the original** to a
  revert file (`write --revert file.json --yes` restores it).
- `--verify` writes the block back **unchanged** — proves the write path end-to-end while changing
  nothing. **This is the recommended FIRST test on the truck.**
Still **no** `0x27` SecurityAccess and **no** `0x14` clear. **A wrong `2E` can brick a body
module** — keep the dry-run/read-first/revert discipline, and **never fabricate** a DID↔name
mapping, a value, or a seed/key.

### >>> RECOMMENDED FIRST TRUCK TEST (safe, proves we can write) <<<
```
:: 1) prove the write PATH works without changing anything (identical readback-write):
python -I tazer_config\tazerctl.py write --port COMx --bus s6 --tx 0x620 --rx 0x504 --did 0x0146 --verify --yes
::    expect: session OK, a POSITIVE 6E 01 46 response, readback == new. That confirms
::    SGW-bypass + extended session is enough to WRITE (no seed-key), end to end.
:: 2) ONLY after that: flip ONE Customer-Settings-Menu bit (0146/0147 are menu-reversible,
::    the safest block), observe the car, then revert:
python -I tazer_config\tazerctl.py write ... --did 0x0146 --byte 7 --mask 0x80 --value 0x80   (dry-run: shows frame)
python -I tazer_config\tazerctl.py write ... --did 0x0146 --byte 7 --mask 0x80 --value 0x80 --yes
python -I tazer_config\tazerctl.py write --revert revert_0146.json --yes                      (undo)
```
Pair this with `watch` (listen-only) in another window to see the matching broadcast bitmap move.

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

## 2026-11-24 — Light-show / actuation mechanism extracted; gated `iocontrol` added
Q answered: with ONE sniffer + SGW bypass you can test ALL features (incl. light show) one bus at a
time — the Tazer itself has a single AT90CAN controller it switches between buses (code:0973), so it
is never on two buses at once. Both-buses-at-once (ESP32 2nd channel) is only a convenience.

Firmware extraction (see analysis/FINDINGS.md "ACTUATION MECHANISM"):
- Light/body actuations = **UDS 0x2F InputOutputControl**, NOT 0x31. Lamp driver word 0x3e50 → BCM
  0x620. FORCE `2F <did> 03 <state>`, RELEASE `2F <did> 00`. Lamp DIDs = 0xD1xx family
  (0xD1A8/A9, 0xD1B2/B3, 0xD1C2; community overhead-flash 0xD1BE). 0xD0xx outputs → module 0x74B.
- DID→specific-lamp and the show choreography are icall-dispatched → NOT statically resolvable;
  map them EMPIRICALLY on the truck.

New tool command `iocontrol` (gated like `write`: dry-run default, only --yes transmits, forces one
output then AUTO-RELEASES). Use to map each 0xD1xx DID → physical lamp:
  python -I tazer_config\tazerctl.py iocontrol --port COMx --bus s6 --did 0xD1C2 --state 01 --hold 2 --yes
Expect a POSITIVE 6F response + a lamp energising for 2s, then release. Try 0xD1A8, 0xD1A9, 0xD1B2,
0xD1B3, 0xD1C2, 0xD1BE and note which lamp each lights. NOTE: state byte + release form not
firmware-confirmed — that's exactly what the bench mapping confirms. Once mapped, a light-show
sequencer (chained forces + delays) can be built.
