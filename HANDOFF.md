# HANDOFF — Tazer-free Jeep JL config (read where we left off)

> **UPDATE 2026-11-25 — FULL firmware extraction done (Mac).** `tazer_config/settings_map.json`
> now has **37 config settings** (names firmware-proven, DID/byte/mask on BCM 0x620, enum tables,
> composite write sequences) and `tazer_config/actuations.json` has the actuation/live-function CAN
> frames (Sway/Cooldown/ForceRWD/Splash/lightshow confirmed; PCM tire/gear + raw broadcasts frame-only;
> Line Lock/Rock Crawl/Winch/TC-Kill unresolved→bench-capture). New CLI `tazerctl cfg list|get|set`
> drives it (gated, dry-run default). TRUCK TODO: for each setting, `cfg set … ` (dry-run → --yes) then
> before/after `diff` to confirm the Yes/No direction (value_polarity_verified=false until you do).
> See analysis/FINDINGS.md "FULL STATIC EXTRACTION" for the method.


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

## 2026-11-24 (later, Windows/COM8) — LIGHT SHOW CONFIRMED WORKING on the truck + firmware ask
Empirically validated the actuation end-to-end. **UDS 0x2F to BCM 0x620 DOES drive real exterior
lamps.**
- **Preconditions found:** needs **ENGINE RUNNING** for a stable diagnostic session — with the
  engine OFF (key-on/accessory) the BCM dropped the `10 03` session (reads/forces failed). State
  byte range is small: `0x01`/`0x02` accepted, `0x04+` -> requestOutOfRange. Responses are
  intermittently dropped on the busy 500k bus — **retry the force until POSITIVE** (see
  `scratchpad map_robust.py` approach; folded into `tazer_config/lightshow.py`).
- **Enumerated 15 valid output DIDs** in 0xD1A0-0xD1CF: D1A4 A5 A6 A7 A8 AA B2 B4 B5 BD BE BF C1 C2
  C5. (D1AD, D1C6 = conditionsNotCorrect — maybe engine-off-only.)
- **Bench-mapped lamps (live-observed, in `tazer_config/lamp_map.json`):**
  `0xD1A6`=**Brake lights** (confirmed), `0xD1A8`=**Reverse lights** (confirmed),
  `0xD1A4`/`0xD1A5`=front fender markers L/R (tentative). A7/AA/B2 partially seen (a brake side).
  B4/B5/BD/BE/BF/C1/C2/C5 still unmapped (likely turn signals / headlights / fogs / DRL).
- **New tool:** `tazer_config/lightshow.py` — opens one session (retried), keep-alive, forces the
  confirmed lamps in patterns (wig-wag / all-flash / chase / strobe / finale), releases all on
  exit. `python -I tazer_config/lightshow.py --port COM8 --bus s6`. Runs; patterns visible but
  coarse because only 4 lamps are confirmed and attribution is still fuzzy.

### >>> OWNER REQUEST (do on the Mac): extract the lamp map + show choreography FROM FIRMWARE <<<
Owner wants the lamp DID->lamp names and the 6 preset (+3 custom) light-show sequences pulled from
the Tazer firmware and encoded into the tool, instead of guessing on the truck. NOTE: the earlier
Mac pass concluded the DID->specific-lamp and the show choreography are **icall-dispatched / runtime
menu-table driven -> not statically resolvable** (handoff 2026-11-24 top). So this needs a DEEPER
pass on the Mac:
  1. Resolve the indirect-call dispatch tables (the icall targets / jump tables feeding the lamp
     driver at word 0x3e50 and the show sequencer) to recover DID->lamp and the per-show step lists.
  2. If static resolution stays blocked, do DYNAMIC extraction (emulate the show handler, or trace
     the frame-builder with the stashed (DID,byte,state) like the config extractor did at the 85
     call sites) to dump each show's ordered 2F sequence + timings.
  3. Encode results into `tazer_config/lamp_map.json` (confirmed labels) and a new `shows.json`
     (ordered steps), and have `lightshow.py` play from `shows.json`.
The firmware + disassembly are Mac-only (`…/sniffer_firmware/analysis/` + `decrypted/`) — NOT in
this repo and NOT on the Windows laptop, so this step cannot be done from Windows. Our empirical
map above is the ground-truth to cross-check the firmware extraction against.

## 2026-11-24 (Mac) — LIGHT SHOW EXTRACTED FROM FIRMWARE (answered the owner request)
Decompiled the firmware's light-show code (ZES-128, Ghidra headless — REA's provider was down but
analyzeHeadless works directly). Found the primitives and the choreography:
- `set_output(DID, state)` = word 0x3e4e (byte 0x7c9c): forces a lamp via 2F <DID> 03 <state>.
- `blink_step(light1, light2, blinkCount, delay)` = word 0x5b38: ON both lamps, delay, OFF both,
  × blinkCount — i.e. ONE light-show step, exactly ZPU's (light1,light2,blink,delay) format.
- Show runner = word 0x5b7a; a state machine keyed on a show index. Extracted its ordered D1xx
  step list by dataflow over the ldi args (the decompiler mangles AVR's reg-passed args, so the
  asm slice is the better source).
LAMP MAP (firmware L/R pairing × truck observation × ZPU light names), in lamp_map.json:
  0xD1A6/A7 = Brake L/R (A6 truck-confirmed); 0xD1A8/A9 = Reverse L/R (A8 truck-confirmed);
  0xD1A4/A5 = Front markers L/R (inferred); 0xD1B2/B3 and 0xD1B8/B9 = firmware pairs, names TBD.
  (The show also toggles 0xD0xx on module 0x74A/0x74B — a DIFFERENT module, not driven by this
  BCM-only tool, so those steps are omitted from the replay.)
NEW: `tazer_config/shows.json` encodes the firmware opening sequence ("firmware" show) + a wig-wag.
`lightshow.py` now loads lamp_map.json + shows.json and plays them:
  python -I tazer_config\lightshow.py --port COM8 --bus s6 --mode firmware --duration 30
TRUCK TODO: run `iocontrol --did 0xD1B2` (and B3/B8/B9) to name the two unknown firmware pairs;
set confidence:confirmed in lamp_map.json. Tune shows.json tick_ms by eye (firmware ms/tick unknown,
default 50). Then the "firmware" show is a faithful replay of the Tazer's own opening choreography.

## 2026-11-24 (Windows/COM8) — light-show timing tuned by eye
Played `--mode firmware` at tick_ms 20/25/30/35/55 on the truck; owner picked the **fastest (~20ms)**
as the closest to the real Tazer. Set `shows.json tick_ms=20` as the default. Added `--tick-ms`
override to `lightshow.py`. OPEN: exact firmware ms-per-tick still unknown — **Mac TODO: read the
show-runner's timer tick (the delay unit feeding blink_step @0x5b38) to lock the replay to the
Tazer's true speed.** Couldn't match from YouTube (can't frame-count video; forums/manuals don't
publish timing).

## 2026-11-24 (Windows/COM8) — headlight/fog hunt: confirmed they're on module 0x74B (0xD0xx), not the BCM
Research confirms the Tazer show **does flash the headlights** (and factory fogs, if equipped) — but
those are driven on a DIFFERENT module, matching the firmware (show toggles 0xD0xx on 0x74A/0x74B).
The BCM (0x620 / 0xD1xx) does NOT carry headlights/fogs — verified by sweeping the unmapped BCM DIDs
(D1AA/B4/B5/BD/BE/BF/C1/C2/C5 → nothing visible). So stop looking on the BCM for them.
- **0x74B answers UDS** (req 0x74B / resp 0x4CB; `10 03` → `50 03 00 28 00 C8`). Enumerated **20 valid
  0xD0xx outputs** (in `lamp_map.json` → `module_0x74B`): D013 D028 D036 D039 D03A D03D D045 D046 D047
  D04A D055 D056 D058 D05B D05D D061 D06D D081 D087 D088.
- Bench-tested the first 5 (D013/D028/D036/D039/D03A) at state 01, engine running → **no visible lamp**.
  15 untested. (Test via `iocontrol --tx 0x74B --rx 0x4CB --did 0xD0xx --state 01 --hold 4 --yes`.)

### >>> MAC TODO (do this instead of blind-testing 20 DIDs) <<<
The firmware already knows WHICH 0xD0xx DIDs the show drives and on which module. In the show-runner
analysis (ZES-128 @0x5b7a, set_output @0x3e4e, blink_step @0x5b38), **extract the specific 0xD0xx DIDs
+ their target module (0x74A vs 0x74B)** used by the show's headlight/fog/marker steps — the same way
the 0xD1xx steps were pulled into shows.json. Then:
  1. Add those exact 0xD0xx DIDs to lamp_map.json (module_0x74B / a new module_0x74A) and label them.
  2. Extend lightshow.py to drive a second module (it currently hardcodes TX=0x620) so shows.json steps
     can target 0x74A/0x74B too — then the replay includes headlights/fogs and matches the Tazer fully.
Also worth checking module **0x74A (resp 0x4CA)** — the firmware note pairs 0x74A/0x74B for 0xD0xx.
Our empirical 0x74B enumeration above is ground-truth to cross-check the firmware extraction.

## 2026-11-24 (Mac) — answered the 0xD0xx/module + timing TODOs
1) MODULE ROUTING — the show's D0xx go to the BCM, NOT 0x74B. The show's lamp driver set_output
   (ZES-128 word 0x3e4e) routes EVERY DID to BCM 0x620 (only 0xD001 -> module 0x749). So stop
   testing 0x74B. The firmware show drives these 0xD0xx on the **BCM 0x620**:
     D0A0 D0A1 D0A2 D0A3 D0A8 D0A9 D0AA D0AB D014 D015 D039 D03A
   TRUCK TODO: iocontrol --tx 0x620 --rx 0x504 --did 0xD0xx --state 01 --hold 4 --yes for each ->
   name them (headlights/fogs/park/turn likely live here). Added to lamp_map.json
   (show_D0xx_outputs_on_BCM); the 0x74B enumeration is a different module the show does NOT use.
   NOTE: no second-module support needed in lightshow.py — the whole show is on BCM 0x620.
2) TIMING — delay is Timer2-based (word 0x6e02 -> unit 0x6de4: /1024 prescaler, 16-count overflow).
   F_CPU=16MHz (proven by the 500k CAN bit-timing constants 06/04/13), so one firmware delay-unit
   ~= 1.0ms; the show's delay=10 ~= 10ms nominal. Real cadence is limited by CAN TX time per 2F
   (why ~20ms felt right). tick_ms stays the practical knob. Recorded in shows.json _tick_note.

## 2026-11-24 (Mac) — FOG config extracted from firmware (owner's aftermarket yellow off-road fogs)
Owner's fogs: aftermarket YELLOW OFF-ROAD, on FACTORY fog wires, triggered by the FACTORY fog switch
=> BCM-controlled (good: can be configured/flashed over CAN; the "won't work" rumor is for fogs on an
independent switch). Traced the Tazer's fog settings menu->config-wrapper (0x8c00) to exact bits
(now labelled in did_map.json; writes go to BCM 0x620 via 0x2E):
  - Fogs Enabled ("Fogs En")  = DID 0x0130, byte 4, mask 0x02   [fw @47b3]
  - LED Fogs ("LED FOGS")     = DID 0x0131, byte 4, mask 0x20   [fw @484c]  <- SET THIS for LED fogs
  - Fog Drop ("Fog Drop")     = DID 0x0131, byte 1, mask 0x10   [fw @47cd]  (fogs stay on w/ high beam)
  - DRLLoc is a 5-way menu; "Fog" = option value 4 (storage is a multi-bit field, not yet pinned).
KEY INSIGHT: the fog FEATURES are implemented as BCM CONFIG writes (the fog-drop runtime @0x40e8 just
writes config DIDs 0149/013d/0131) — the fog LAMP itself is driven NATIVELY by the BCM (switch+config),
NOT force-driven by the Tazer, EXCEPT in the light show. So:
  - To make LED off-road fogs behave (incl. flashing cleanly): write LED Fogs = Yes (0x0131 b4 0x20).
    Verify Fogs En (0x0130 b4 0x02) is already set (it is, since the switch works).
  - To FLASH fogs in the light show: the fog forced-output DID is one of the BCM outputs but the
    firmware does NOT label it "fog" (set_output is DID-parameterized). Firmware-wide set_output DIDs:
    D014 D015 D0A0-A3 D0A8-AB D0AD D1A4-A9 D1B2/B3 D1B8/B9 F1A6 (+ config 0F01/0F02/0010/D001).
    TRUCK TODO: force the unmapped BCM candidates (D1AA/B4/B5/BD/BE/BF/C1/C2/C5 + the show D0xx) one at
    a time and watch the yellow fogs: iocontrol --tx 0x620 --rx 0x504 --did 0xXXXX --state 01 --hold 4 --yes.
    The one that lights the fogs is the fog output DID -> add to lamp_map.json + shows.json.

## 2026-11-24 (Windows/COM8) — FULL EXTERIOR LAMP MAP COMPLETE + mega show (session summary)
All exterior lamps are now bench-confirmed on the **BCM 0x620** (req 0x620 / resp 0x504, s6 500k,
ENGINE RUNNING, UDS 2F force `2F <did> 03 01` / release `2F <did> 00`). This corrected the earlier
"turn signals not injectable" note — they ARE reachable as BCM forced-outputs (just not via comfort-bus
status-frame injection).

CONFIRMED LAMP DIDs (in lamp_map.json):
  D0A0/D0A1 = Fog L/R            D0A8/D0A9 = Headlight L/R
  D0AA/D0AB = High beam L/R      D014/D015 = Turn signal L/R
  D0A2/D0A3 = Brake L/R (A2 seen; A3 inferred pair)
  D1A6/D1A7 = Tail-brake L/R     D1A8/D1A9 = Reverse L/R
  D1A4/D1A5 = Front marker L/R   D1B2 = Center brake (CHMSL)   D1B8/D1B9 = White fender L/R
  (D039/D03A: in firmware show list but would NOT force on the BCM - they are 0x74B's outputs; the
   firmware set_output routes everything else to BCM. Skip them for the BCM replay.)

TOOL: lightshow.py now has modes police / classic / mega / firmware / wigwag.
  - `mega` = full-exterior police choreography (headlights/high beams/fogs/turns + rear). Python-coded.
  - `firmware` = Tazer's extracted opening sequence from shows.json (0xD1xx steps only so far).
  Run: `python -I tazer_config/lightshow.py --port COM8 --bus s6 --mode mega --duration 60` (engine running).

REMAINING (nice-to-have, for Mac or next truck visit):
  1. Fold the confirmed 0xD0xx lamps into shows.json's `firmware` steps (the Mac extracted the show
     also drives D0A0-A3/D0A8-AB/D014/D015 on the BCM) so the firmware replay includes headlights/fogs/
     turns and matches the Tazer's real opening show exactly (currently mega covers them, firmware doesn't).
  2. Confirm D0A3 (right brake) and re-check D039/D03A on 0x74B if a rear-element is missing.
  3. Fog FEATURE config (not the show): to make the yellow LED off-road fogs behave, write LED Fogs =
     0x0131 b4 0x20 (via the gated `write` cmd); Fogs En 0x0130 b4 0x02 already set.
Raw vehicle captures (snap_*.json, watch_*.json) stayed local (gitignored) - re-capture as needed.

## 2026-11-24 (Mac) — folded confirmed 0xD0xx into the 'firmware' show (remaining item #1 done)
With the truck's full BCM lamp map confirmed (fogs D0A0/A1, brakes D0A2/A3, headlights D0A8/A9,
high beams D0AA/AB, turns D014/D015), I:
1) Promoted all 10 confirmed 0xD0xx into lamp_map.json `lamps` (names + confidence:confirmed) — so
   all_lamp_dids() now returns all 20 lamps and all_on/all_off cover the full exterior.
2) Rebuilt shows.json `firmware` to the Tazer's CONTIGUOUS OPENING sequence (ZES-128 @0x5b7a,
   0x5b93-0x5c0d + the x2/finale tail), with the D0xx folded in exactly where the firmware sets them:
   it wig-wags brake/marker/turn (D1xx) while alternating headlight/high-beam/fog L<->R (D0xx), then
   the turn/reverse/marker x2 burst, all-on/all-off finale, and the white-fender tail. D039/D03A are
   0x74B outputs (not BCM) so they're omitted. Mock-traced: the show now drives all 20 confirmed lamps
   incl. fog/headlight/highbeam/turn.
   Run: `python -I tazer_config\lightshow.py --port COM8 --bus s6 --mode firmware --duration 30`
NOTE on fidelity: the opening (0x5b93-0x5c0d) is a contiguous single path = faithful. The later
portions of the show runner branch on the show-index (R17) and the decompiler mangled the AVR reg
args, so beyond the opening I used the clean extracted steps rather than tracing every R17 branch.
`mega` remains the hand-built full-exterior alternative. Remaining nice-to-haves: confirm D0A3 (right
brake) and whether any 0x74B element (D039/D03A) adds a rear lamp the BCM set misses.

## 2026-11-25 — CRITICAL: plain 2E config writes do NOT apply/persist (blocks the 37-setting feature)
Tested DRLLoc Dedic(5)->Turn(3) end-to-end via the UI on the live truck:
- The 2E WriteDataByIdentifier DID change the UDS read-back (read Turn 3x consistently), writes
  returned POSITIVE / responsePending(0x78).
- BUT: (a) NO physical change (DRL did not become the turn signal), and (b) after an ENGINE cycle
  the field drifted to 0x07 (invalid) - i.e. the BCM re-derived/overwrote our write.
- Restored to factory Dedic(5) (confirmed), so the truck is back to stock.
CONCLUSION: a bare `2E 01 XX <block>` to the proxi-config DIDs is NOT the full mechanism on this
truck. The Tazer almost certainly does MORE after the write. >>> MAC TODO (firmware): find how the
Tazer COMMITS proxi config - candidates to look for in the ZES-128 settings-write path (config
wrapper 0x8c00 / the 0x2E sender):
  1. A routineControl (0x31) "commit/save configuration" after the 2E (FCA proxi often needs a
     write-then-commit, or an ECUReset 0x11 / specific NRC-0x78 completion handshake).
  2. A PROGRAMMING session (0x10 0x02) rather than extended (0x10 0x03) for the write to stick.
  3. A full power-DOWN/sleep (not engine cycle) required to load the new NVM config to the outputs.
  4. Whether the real config lives in a different DID/region and 0x01xx is a volatile mirror.
Until this is known, the UI's `cfg set` / Vehicle Settings writes read back changed but will NOT
take effect - treat the 37-setting write feature as UNPROVEN. (Light show / 0x2F actuation is
unaffected and fully works.) Also fixed: UI revert snapshot now only saves the FIRST (factory)
block so a revert can't capture an already-changed value.
