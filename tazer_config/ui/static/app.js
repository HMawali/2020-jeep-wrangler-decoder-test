/* Tazer JL Cockpit — frontend. Talks to the stdlib bridge in server.py. No build step. */
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const hx = v => (typeof v === 'number' ? '0x' + v.toString(16).toUpperCase() : v);

const api = {
  async get(p) { const r = await fetch(p); return r.json(); },
  async post(p, b) { const r = await fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }); return r.json(); }
};

const S = {
  mode: 'sim', connected: false, engine: false, profile: '2020 JL',
  bus: 's6', port: null, cat: null, act: null, lampcat: null, shows: null,
  live: { lamps: {}, tele: {}, show: null }, cart: {}, armTester: false, ws: 'settings',
  remap: JSON.parse(localStorage.getItem('tz_remap') || '{}'),
  memory: JSON.parse(localStorage.getItem('tz_memory') || '{}'),
};

/* ---------- setting grouping ---------- */
const GROUPS = [
  ['Exterior Lighting', 'Front/rear lighting blueprint · DRL · fogs · halos · LED conversions',
    ['Fogs En', 'LED FOGS', 'Fog Drop', 'DRLLoc', 'DRLType', 'DRL Drop', 'Halo En', 'OneTouch',
     'AutoHiBm', 'AutoHL', 'LED Heads', 'LED Tails', 'LED FTrn', 'Tail']],
  ['Drivetrain & Chassis', 'Hardware declarations for axle/t-case/sway/steering swaps',
    ['LOCKER', 'FullTcase', 'TrlrBrk', 'DTCM', 'EPSteer', 'Paddles']],
  ['TPMS', 'Tire-pressure monitoring',
    ['TPMS']],
  ['Infotainment, Cameras & Retrofits', 'Radio/HMI, camera, comfort retrofits',
    ['Cam En', 'CargoCam', 'DVD_CD', 'TravelLnk', 'OffRdPgs', 'Splash', 'DualZone', 'HomeLink',
     'DimMirror', 'ProxEntry', 'Bed115v', 'AUX', 'BlindSpot', 'PanicBtn', 'SGW']],
];

/* ---------- toast + modal ---------- */
function toast(msg, kind = '') {
  const t = document.createElement('div'); t.className = 'toast ' + kind; t.innerHTML = msg;
  $('#toast-wrap').appendChild(t); setTimeout(() => t.remove(), 4200);
}
function modal(html) {
  $('#modal').innerHTML = html; $('#modal-wrap').classList.remove('hidden');
}
function closeModal() { $('#modal-wrap').classList.add('hidden'); }
$('#modal-wrap').addEventListener('click', e => { if (e.target.id === 'modal-wrap') closeModal(); });

/* ---------- connection / topbar ---------- */
async function refreshPorts() {
  const { ports } = await api.get('/api/ports');
  const sel = $('#port-sel');
  sel.innerHTML = (S.mode === 'sim')
    ? '<option>SIMULATOR</option>'
    : (ports.length ? ports.map(p => `<option>${p}</option>`).join('') : '<option value="">(no ports)</option>');
}
async function connect() {
  if (S.connected) { await api.post('/api/disconnect'); return syncState(); }
  const body = { mode: S.mode, bus: S.bus, port: (S.mode === 'live' ? $('#port-sel').value : null) };
  if (S.mode === 'live' && !body.port) return toast('Pick a COM port first.', 'warn');
  const r = await api.post('/api/connect', body);
  if (r.error) return toast(r.error, 'err');
  toast(`Connected · ${r.mode.toUpperCase()} · ${r.bus_label}`, 'ok');
  syncState();
}
async function syncState() {
  const st = await api.get('/api/state');
  S.connected = st.connected; S.mode = st.mode || S.mode; S.engine = st.engine_running;
  const cb = $('#connect-btn');
  cb.textContent = st.connected ? 'DISCONNECT' : 'CONNECT';
  cb.classList.toggle('connected', st.connected);
  $('#engine-lbl').textContent = st.engine_running ? 'ENGINE RUNNING' : 'IGN RUN · ENGINE OFF';
  $('#engine-btn').classList.toggle('on', st.engine_running);
  updateInterlock();
}
function updateInterlock() {
  const el = $('#interlock');
  if (S.mode === 'live' && S.connected && !S.engine && (S.ws === 'lightshow' || S.ws === 'live')) {
    el.classList.remove('hidden');
    el.textContent = '⚠ 0x2F outputs & light shows need ENGINE RUNNING — the BCM drops the 10 03 session with the engine off. Start the engine or flip Vehicle State.';
  } else el.classList.add('hidden');
}

/* ---------- live polling ---------- */
let lastFrameN = 0;
async function poll() {
  try {
    const d = await api.get('/api/stream');
    S.connected = d.connected; S.engine = d.engine_running; S.live.lamps = d.lamps || {};
    S.live.tele = d.telemetry || {}; S.live.show = d.show;
    $('#tx-n').textContent = d.tx; $('#rx-n').textContent = d.rx;
    const live = d.mode === 'live';
    $('#tx-pill').classList.toggle('live', live && d.tx > 0);
    $('#rx-pill').classList.toggle('live', live && d.rx > 0);
    renderConsole(d.frames);
    if (S.ws === 'lightshow') paintLamps();
    if (S.ws === 'live') paintGauges();
    if (S.ws === 'diag') paintWatch(d.frames);
  } catch (e) { /* server starting */ }
  setTimeout(poll, 300);
}

/* ---------- console ---------- */
function renderConsole(frames) {
  const body = $('#console-body');
  if (!frames || frames.length === lastFrameN) return;
  lastFrameN = frames.length;
  body.innerHTML = frames.map(f =>
    `<div class="fr"><span class="t">${(f.t % 1000).toFixed(3)}</span>` +
    `<span class="d-${f.dir.toLowerCase()}">${f.dir}</span>` +
    `<span class="id">${f.id}</span><span class="hex">${f.hex}</span>` +
    `<span class="dec">${f.decode || ''}</span></div>`).join('');
  if ($('#autoscroll').checked) body.scrollTop = body.scrollHeight;
}

/* =========================================================================
   WORKSPACE 1 — VEHICLE SETTINGS
   ========================================================================= */
function cardCtl(name, d) {
  if (d.module === 'TAZER')
    return `<span class="badge tazer">TAZER FLAG</span>`;
  if (d.values) {
    const opts = Object.entries(d.values).map(([k, v]) => `<option value="${k}">${v} · ${k}</option>`).join('');
    return `<select class="enum-sel" data-name="${name}">${opts}</select>`;
  }
  const on = S.cart[name] === 'on';
  return `<div class="toggle ${on ? 'on' : ''}" data-name="${name}" data-type="bool"></div>`;
}
function renderSettings() {
  const S4 = S.cat.settings;
  const seen = new Set();
  let html = `<div class="ws-head"><div class="ws-title">Vehicle Settings</div>
    <div class="ws-sub">${Object.keys(S4).length} firmware-extracted settings · BCM 0x620 · read 22 01 XX / write 2E 01 XX (RMW)</div></div>`;
  for (const [title, sub, names] of GROUPS) {
    const cards = names.filter(n => S4[n]).map(n => { seen.add(n); return settingCard(n, S4[n]); });
    if (!cards.length) continue;
    html += `<div class="group"><div class="group-h">${title} <small>${sub}</small></div>
      ${title === 'Drivetrain & Chassis' ? tireStudio() : ''}
      <div class="grid">${cards.join('')}</div></div>`;
  }
  const other = Object.keys(S4).filter(n => !seen.has(n));
  if (other.length)
    html += `<div class="group"><div class="group-h">Other</div><div class="grid">${other.map(n => settingCard(n, S4[n])).join('')}</div></div>`;
  $('#workspace').innerHTML = html;
  wireSettings();
  renderCart();
}
function settingCard(name, d) {
  const r = d.read; const ver = d.value_polarity_verified;
  const badge = d.module === 'TAZER' ? '' :
    (ver ? `<span class="badge ver">POLARITY ✓</span>` : `<span class="badge unver">POLARITY UNVERIFIED</span>`);
  const typ = d.type === 'composite' ? ` · ${d.write_ops.length}-op composite` : '';
  return `<div class="card" data-name="${name}" id="card-${cssId(name)}">
    <div class="card-top"><div><div class="card-name">${name}</div><div class="card-menu">${d.menu_label}</div></div>${badge}</div>
    <div class="card-meta">${r.did} · byte ${r.byte} · mask ${r.mask}${typ} · ${d.module}</div>
    <div class="card-ctl">
      ${cardCtl(name, d)}
      <div style="display:flex;gap:6px">
        <button class="btn sm ghost" data-read="${name}">READ</button>
        ${d.module !== 'TAZER' ? `<button class="btn sm ghost" data-verify="${name}" title="Polarity verify helper">⌖</button>` : ''}
      </div>
    </div>
    <div class="card-val kv" id="val-${cssId(name)}"></div>
  </div>`;
}
function cssId(n) { return n.replace(/[^a-z0-9]/gi, '_'); }
function tireStudio() {
  return `<div class="panel" style="margin-bottom:12px">
    <div class="group-h" style="border:none;margin-bottom:8px">Tire Calibration Studio <small>compute rolling diameter → gear/tire DID candidates</small></div>
    <div class="row" style="align-items:center">
      <label class="kv">Preset
        <select id="tire-preset"><option value="">custom</option><option>33</option><option>35</option><option>37</option><option>40</option></select></label>
      <label class="kv">Section mm <input id="tw" class="inp" value="285" style="width:70px"></label>
      <label class="kv">Aspect % <input id="ta" class="inp" value="70" style="width:60px"></label>
      <label class="kv">Rim in <input id="tr" class="inp" value="17" style="width:60px"></label>
      <button class="btn sm" id="tire-calc">COMPUTE</button>
      <div class="kv" id="tire-out" style="color:var(--cyan)"></div>
    </div>
    <div class="note" style="margin-top:7px">Diameter feeds the PCM tire/gear write (<span class="mono">2E 22XX…</span>, frame-only &amp; <b>unverified</b> — bench-confirm the exact DID &amp; scaling before sending).</div>
  </div>`;
}
function wireSettings() {
  $$('.toggle[data-type=bool]').forEach(t => t.onclick = () => {
    const n = t.dataset.name; const on = !t.classList.contains('on');
    t.classList.toggle('on', on); stage(n, on ? 'on' : 'off');
  });
  $$('.enum-sel').forEach(s => s.onchange = () => stage(s.dataset.name, s.value));
  $$('[data-read]').forEach(b => b.onclick = () => readOne(b.dataset.read));
  $$('[data-verify]').forEach(b => b.onclick = () => polarityHelper(b.dataset.verify));
  const tc = $('#tire-calc'); if (tc) {
    const calc = () => {
      const p = $('#tire-preset').value;
      let dia;
      if (p) { dia = +p; $('#tire-out').textContent = `${p}" tire → ${(dia * 25.4).toFixed(0)} mm rolling dia`; }
      else {
        const w = +$('#tw').value, a = +$('#ta').value, r = +$('#tr').value;
        dia = r + 2 * (w * a / 100) / 25.4;
        $('#tire-out').textContent = `${dia.toFixed(2)} in  (${(dia * 25.4).toFixed(0)} mm) · revs/mi ≈ ${(20168 / dia).toFixed(0)}`;
      }
    };
    tc.onclick = calc; $('#tire-preset').onchange = calc;
  }
}
function stage(name, value) {
  S.cart[name] = value;
  const c = $('#card-' + cssId(name)); if (c) c.classList.add('staged');
  renderCart();
}
async function readOne(name) {
  if (!S.connected) return toast('Connect first.', 'warn');
  const r = await api.post('/api/cfg/get', { name });
  const el = $('#val-' + cssId(name));
  if (r.error) { el.innerHTML = `<span style="color:var(--red)">${r.error}</span>`; return; }
  if (r.skip) { el.innerHTML = `<span style="color:var(--violet)">${r.note}</span>`; return; }
  el.innerHTML = `block <b>${r.block}</b> → field ${r.field} = <b style="color:var(--cyan)">${r.value}</b>`;
}

/* pending cart */
function renderCart() {
  const names = Object.keys(S.cart);
  const old = $('#cart'); if (old) old.remove();
  if (!names.length) return;
  const rows = names.map(n => `<div class="cart-row"><span>${n} → <b style="color:var(--amber)">${S.cart[n]}</b></span>
    <span class="x" data-uncart="${n}">✕</span></div>`).join('');
  const el = document.createElement('div'); el.id = 'cart';
  el.innerHTML = `<h4>⟳ PENDING CHANGES (${names.length})</h4><div id="cart-items">${rows}</div>
    <div class="cart-foot"><button class="btn" id="cart-preview">PREVIEW DRY-RUN</button>
    <button class="btn go" id="cart-commit">COMMIT (--yes)</button>
    <button class="btn ghost sm" id="cart-clear">clear</button></div>`;
  document.body.appendChild(el);
  $$('[data-uncart]').forEach(x => x.onclick = () => { unstage(x.dataset.uncart); });
  $('#cart-clear').onclick = () => { for (const n of Object.keys(S.cart)) unstage(n); };
  $('#cart-preview').onclick = () => cartRun(true);
  $('#cart-commit').onclick = () => cartRun(false);
}
function unstage(n) { delete S.cart[n]; const c = $('#card-' + cssId(n)); if (c) c.classList.remove('staged'); renderCart(); }
async function cartRun(dry) {
  if (!S.connected) return toast('Connect first.', 'warn');
  const names = Object.keys(S.cart);
  if (!dry) {
    const ok = await confirmModal(`Transmit ${names.length} setting write(s) to the BCM?`,
      `This sends real <span class="mono">2E</span> writes. A revert snapshot is saved for each. Unverified-polarity settings may move the opposite way — verify after.`);
    if (!ok) return;
  }
  const results = [];
  for (const n of names) {
    const r = await api.post('/api/cfg/set', { name: n, value: S.cart[n], dry_run: dry });
    results.push(r);
  }
  showCartResults(results, dry);
  if (!dry) { S.cart = {}; renderSettings(); }
}
function showCartResults(results, dry) {
  const body = results.map(r => {
    if (r.error) return `<div class="diffbox"><b style="color:var(--red)">${r.name}: ${r.error}</b></div>`;
    const fr = (r.frames || []).map(f =>
      `<div><b>${r.name}</b> · ${f.did}\n  <span class="del">- ${f.old}</span>\n  <span class="add">+ ${f.new}</span>\n  ${(f.diff || []).join('\n  ')}\n  frame: ${f.frame}</div>`).join('\n');
    const sent = r.sent ? '\n→ ' + r.sent.map(s => `${s.did}: ${s.result}`).join('  ') : '';
    const pv = r.polarity_verified ? '' : '  ⚠ polarity unverified';
    return `<div class="diffbox">${fr}${sent}${pv}</div>`;
  }).join('');
  modal(`<h3>${dry ? 'Dry-Run Preview' : 'Transmitted'} · ${results.length} setting(s)</h3>${body}
    <div class="modal-foot"><button class="btn" onclick="closeModal()">Close</button></div>`);
}
async function polarityHelper(name) {
  if (!S.connected) return toast('Connect first.', 'warn');
  const before = await api.post('/api/cfg/get', { name });
  modal(`<h3>Polarity Verify · ${name}</h3>
    <div class="note">Firmware proved the <b>bit</b>; this confirms which value means ON. Read before → change it → read after → see the bit move. Then mark it verified.</div>
    <div class="diffbox" id="pv-box">BEFORE: block ${before.block || '—'} → ${before.value || before.error || ''}</div>
    <div class="chiprow">
      <button class="btn sm" id="pv-set-on">Set ON (dry→yes)</button>
      <button class="btn sm" id="pv-set-off">Set OFF (dry→yes)</button>
      <span class="note">…or toggle it with the factory control, then:</span>
      <button class="btn sm go" id="pv-after">READ AFTER + DIFF</button>
    </div>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Close</button></div>`);
  const setv = async v => {
    await api.post('/api/cfg/set', { name, value: v, dry_run: true });
    const ok = await confirmModal(`Write ${name}=${v}?`, 'Real 2E write (revert saved).');
    if (!ok) return polarityHelper(name);
    await api.post('/api/cfg/set', { name, value: v, dry_run: false });
    polarityAfter(name, before);
  };
  $('#pv-set-on').onclick = () => setv('on');
  $('#pv-set-off').onclick = () => setv('off');
  $('#pv-after').onclick = () => polarityAfter(name, before);
}
async function polarityAfter(name, before) {
  const after = await api.post('/api/cfg/get', { name });
  const moved = before.field !== after.field;
  $('#pv-box') && ($('#pv-box').innerHTML =
    `BEFORE: ${before.block} → ${before.value} (${before.field})\nAFTER : ${after.block} → ${after.value} (${after.field})\n` +
    (moved ? `✓ bit moved — record the ON value in settings_map.json (value_polarity_verified:true)` : `· no change (try the other value / confirm engine+session)`));
}

/* =========================================================================
   WORKSPACE 2 — LIVE FUNCTIONS
   ========================================================================= */
function renderLive() {
  const A = S.act;
  const conf = Object.entries(A.confirmed).filter(([k]) => k !== 'lightshow_lamp');
  const confHtml = conf.map(([k, v]) => `<div class="switch">
    <div class="s-name">${v.feature}</div>
    <div class="s-mod">module ${v.module}</div>
    <div class="s-frame">${v.frame || v.iso_tp || ''}</div>
    <div class="s-actions">
      <button class="btn sm" data-actdry="${k}">DRY-RUN</button>
      <button class="btn sm go" data-actsend="${k}">SEND</button>
    </div></div>`).join('');
  const unresolved = A.unresolved.features.map(f => `<div class="switch locked">
    <div class="s-name">${f}</div>
    <span class="badge unver">AWAITING BENCH CAPTURE</span>
    <div class="s-actions"><button class="btn sm ghost" data-capture="${f}">Log capture…</button></div></div>`).join('');
  const frameOnly = Object.entries(A.frame_only).filter(([k]) => k !== 'raw_broadcast').map(([k, v]) =>
    `<div class="switch locked"><div class="s-name mono">${k}</div><div class="s-mod">${v.module || ''}</div>
     <div class="s-frame">${v.frame || ''}</div><span class="badge unver">FRAME-ONLY · UNVERIFIED</span></div>`).join('');
  $('#workspace').innerHTML = `
    <div class="ws-head"><div class="ws-title">Live Functions & Actuations</div>
      <div class="ws-sub">overhead switch panel · UDS 0x2F / 0x31 · confirmed senders are gated (engine-running + dry-run)</div></div>
    <div class="panel" style="margin-bottom:16px"><div class="group-h" style="border:none">Performance Cluster <small>live CAN-C telemetry / simulator</small></div>
      <div class="gauges" id="gauges"></div></div>
    <div class="group"><div class="group-h">✓ Confirmed Actuations</div><div class="switch-grid">${confHtml}</div></div>
    <div class="group"><div class="group-h">Frame-only <small>exact frame extracted, feature inferred — bench-confirm</small></div><div class="switch-grid">${frameOnly}</div></div>
    <div class="group"><div class="group-h">Bench-Capture Queue <small>icall-dispatched — not statically resolvable</small></div><div class="switch-grid">${unresolved}</div></div>`;
  paintGauges();
  $$('[data-actdry]').forEach(b => b.onclick = () => doAct(b.dataset.actdry, true));
  $$('[data-actsend]').forEach(b => b.onclick = () => doAct(b.dataset.actsend, false));
  $$('[data-capture]').forEach(b => b.onclick = () => captureHelper(b.dataset.capture));
  updateInterlock();
}
function paintGauges() {
  const g = $('#gauges'); if (!g) return; const t = S.live.tele || {};
  const bar = (v, max) => Math.min(100, (v / max) * 100);
  g.innerHTML = `
    <div class="gauge"><div class="g-val">${(t.boost_psi ?? 0).toFixed ? (t.boost_psi).toFixed(1) : t.boost_psi || 0}</div><div class="g-lbl">BOOST PSI</div><div class="gbar"><i style="width:${bar(t.boost_psi || 0, 20)}%"></i></div></div>
    <div class="gauge"><div class="g-val cyan">${t.vac_inhg || 0}</div><div class="g-lbl">VAC inHg</div><div class="gbar"><i style="width:${bar(t.vac_inhg || 0, 30)}%"></i></div></div>
    <div class="gauge"><div class="g-val">${t.rpm || 0}</div><div class="g-lbl">RPM</div><div class="gbar"><i style="width:${bar(t.rpm || 0, 6000)}%"></i></div></div>
    <div class="gauge"><div class="g-val cyan">${t.speed_mph || 0}</div><div class="g-lbl">MPH</div><div class="gbar"><i style="width:${bar(t.speed_mph || 0, 60)}%"></i></div></div>`;
}
async function doAct(key, dry) {
  if (!S.connected) return toast('Connect first.', 'warn');
  if (!dry) { const ok = await confirmModal(`Send actuation "${key}"?`, 'Real frame to a vehicle module. Confirmed shape, but verify on bench.'); if (!ok) return; }
  const r = await api.post('/api/actuation', { key, dry_run: dry });
  if (r.error) return toast(r.error, 'err');
  toast(`${r.feature || key} · ${r.module || ''}<br><span class="mono">${r.frame}</span> · ${r.status}`, dry ? 'warn' : 'ok');
}
function captureHelper(feature) {
  modal(`<h3>Bench Capture · ${feature}</h3>
    <div class="note">This feature routes through multi-layer <span class="mono">icall</span> dispatch and was not statically pinned. Capture it on the bench: trigger it with the Tazer/steering combo while sniffing <span class="mono">s6</span>, then paste the CAN frame(s) below to append to <span class="mono">actuations.json</span>.</div>
    <textarea id="cap-txt" class="inp" style="width:100%;height:90px;margin-top:10px" placeholder="e.g.  7E0  04 31 01 30 20 03"></textarea>
    <div class="modal-foot"><button class="btn ghost" onclick="closeModal()">Cancel</button>
    <button class="btn go" id="cap-save">Save note</button></div>`);
  $('#cap-save').onclick = () => {
    const txt = $('#cap-txt').value.trim();
    const caps = JSON.parse(localStorage.getItem('tz_captures') || '{}'); caps[feature] = txt;
    localStorage.setItem('tz_captures', JSON.stringify(caps));
    toast(`Capture note saved locally for "${feature}".`, 'ok'); closeModal();
  };
}

/* =========================================================================
   WORKSPACE 3 — LIGHT SHOW STUDIO
   ========================================================================= */
const LAMP_XY = {
  '0xD0A8': [205, 60, 'Head L'], '0xD0A9': [315, 60, 'Head R'],
  '0xD0AA': [232, 48, 'Hi L'], '0xD0AB': [288, 48, 'Hi R'],
  '0xD0A0': [212, 80, 'Fog L'], '0xD0A1': [308, 80, 'Fog R'],
  '0xD1A4': [178, 66, 'Mark L'], '0xD1A5': [342, 66, 'Mark R'],
  '0xD014': [172, 50, 'Turn L'], '0xD015': [348, 50, 'Turn R'],
  '0xD1B8': [150, 175, 'Fender L'], '0xD1B9': [370, 175, 'Fender R'],
  '0xD1A6': [200, 300, 'Brake L'], '0xD1A7': [320, 300, 'Brake R'],
  '0xD0A2': [182, 300, 'Brk L(D0)'], '0xD0A3': [338, 300, 'Brk R(D0)'],
  '0xD1A8': [228, 312, 'Rev L'], '0xD1A9': [292, 312, 'Rev R'],
  '0xD1B2': [260, 286, 'CHMSL'],
};
function renderLightshow() {
  const shows = Object.keys(S.shows.shows);
  const extraModes = ['police', 'classic', 'mega'];
  const dots = Object.entries(LAMP_XY).map(([did, [x, y, lbl]]) =>
    `<g class="lamp-dot" data-did="${did}"><circle cx="${x}" cy="${y}" r="9" fill="#1a2230" stroke="#2e4157"></circle>
      <text x="${x}" y="${y + 20}" fill="#5a6f8c" font-size="7.5" text-anchor="middle">${lbl}</text></g>`).join('');
  $('#workspace').innerHTML = `
    <div class="ws-head"><div class="ws-title">Light Show Studio & Lamp Tester</div>
      <div class="ws-sub">20 confirmed BCM 0x620 outputs · forces 2F &lt;did&gt; 03 01, auto-release on stop</div></div>
    <div class="showbar panel">
      <label class="kv">Show <select id="show-sel">${shows.map(s => `<option>${s}</option>`).join('')}${extraModes.map(m => `<option>${m}</option>`).join('')}</select></label>
      <label class="kv">Duration <input id="show-dur" class="inp" value="30" style="width:56px">s</label>
      <label class="kv">tick <span id="tick-val" class="mono" style="color:var(--cyan)">20</span>ms
        <input type="range" min="5" max="80" value="20" class="slider" id="tick-slider"></label>
      <button class="btn go" id="show-play">▶ PLAY</button>
      <button class="btn red" id="show-stop">■ STOP + RELEASE</button>
      <label class="chk" style="margin-left:auto"><input type="checkbox" id="arm-tester"> ARM lamp tester (real forces)</label>
    </div>
    <div class="jeep-wrap">
      <svg class="jeep-svg" width="520" height="360" viewBox="0 0 520 360">
        <rect x="160" y="40" width="200" height="280" rx="26" fill="#0e1622" stroke="#243244" stroke-width="2"></rect>
        <rect x="178" y="95" width="164" height="150" rx="14" fill="#0b121c" stroke="#1b2735"></rect>
        <rect x="140" y="70" width="22" height="46" rx="6" fill="#0a0f17" stroke="#243244"></rect>
        <rect x="358" y="70" width="22" height="46" rx="6" fill="#0a0f17" stroke="#243244"></rect>
        <rect x="140" y="250" width="22" height="46" rx="6" fill="#0a0f17" stroke="#243244"></rect>
        <rect x="358" y="250" width="22" height="46" rx="6" fill="#0a0f17" stroke="#243244"></rect>
        <text x="260" y="180" fill="#2e4157" font-size="12" text-anchor="middle">FRONT ▲</text>
        <text x="260" y="200" fill="#2e4157" font-size="10" text-anchor="middle">click a lamp to test</text>
        ${dots}
      </svg>
      <div class="col">
        <div class="panel"><div class="group-h" style="border:none">Single-Lamp iocontrol Tester</div>
          <div class="note">Click any lamp on the Jeep (or enter a candidate DID). Dry-run unless <b>ARM</b> is checked. Pulses <span class="mono">2F &lt;did&gt; 03 01</span> for 2s then auto-releases.</div>
          <div class="row" style="margin-top:10px;align-items:center">
            <label class="kv">DID <input id="t-did" class="inp" value="0xD0A3" style="width:90px"></label>
            <label class="kv">module <input id="t-mod" class="inp" value="0x620" style="width:80px"></label>
            <button class="btn" id="t-pulse">PULSE 2s</button>
          </div>
          <div class="kv" id="t-out" style="margin-top:8px"></div>
        </div>
        <div class="panel" style="margin-top:12px"><div class="group-h" style="border:none">Confirmed Lamp Map</div>
          <div id="lamp-list" style="max-height:200px;overflow:auto"></div></div>
      </div>
    </div>`;
  const list = $('#lamp-list');
  list.innerHTML = Object.entries(S.lampcat.lamps || {}).map(([did, v]) =>
    `<div class="cart-row"><span class="mono">${did}</span><span>${v.label} <span class="badge ${v.confidence === 'confirmed' ? 'ver' : 'unver'}" style="font-size:8px">${v.confidence}</span></span></div>`).join('');
  $('#tick-slider').oninput = e => $('#tick-val').textContent = e.target.value;
  $('#arm-tester').onchange = e => S.armTester = e.target.checked;
  $('#show-play').onclick = async () => {
    if (!S.connected) return toast('Connect first.', 'warn');
    const r = await api.post('/api/show/start', { name: $('#show-sel').value, duration: +$('#show-dur').value, tick_ms: +$('#tick-slider').value });
    r.error ? toast(r.error, 'err') : toast(`▶ ${r.show} playing (${r.duration}s)`, 'ok');
  };
  $('#show-stop').onclick = async () => { await api.post('/api/show/stop'); toast('Show stopped — all lamps released.', 'ok'); };
  $$('.lamp-dot').forEach(g => g.onclick = () => pulseLamp(g.dataset.did, '0x620'));
  $('#t-pulse').onclick = () => pulseLamp($('#t-did').value, $('#t-mod').value);
  paintLamps();
  updateInterlock();
}
async function pulseLamp(did, mod) {
  if (!S.connected) return toast('Connect first.', 'warn');
  const dry = !S.armTester;
  const r = await api.post('/api/io', { did, module: mod, state: '01', hold: 2.0, dry_run: dry });
  if (r.error) return toast(r.error, 'err');
  const out = $('#t-out'); if (out) out.innerHTML = `${dry ? 'DRY' : 'FORCE'} <span class="mono">${r.force}</span> → ${r.status}`;
  toast(`${did} · <span class="mono">${r.force}</span> · ${r.status}`, dry ? 'warn' : 'ok');
}
function paintLamps() {
  const L = S.live.lamps || {};
  $$('.lamp-dot').forEach(g => {
    const on = L[g.dataset.did];
    const c = g.querySelector('circle');
    c.setAttribute('fill', on ? '#ffcf4d' : '#1a2230');
    c.setAttribute('stroke', on ? '#ffb63d' : '#2e4157');
    c.style.filter = on ? 'drop-shadow(0 0 7px #ffb63d)' : 'none';
  });
}

/* =========================================================================
   WORKSPACE 4 — REMAP & MEMORY
   ========================================================================= */
const REMAP_ACTIONS = ['— none —', 'Light Show 1', 'Light Show 2', 'Light Show 3', 'Backup Camera',
  'TC Kill', 'Line Lock', 'Rock Crawl', 'Turn Assist', 'Winch Mode', 'Cooldown',
  'Front Locker', 'Rear Locker', 'Both Lockers', 'SwayKill', 'Dark Mode', 'Force RWD', 'Partial Reboot'];
const MEMORY_ITEMS = [
  ['autostopstart', 'AutoStopStart last-state memory'], ['autotrackill', 'AutoTracKill last-state memory'],
  ['sway2wd', '2WD Sway Disconnect < 30 mph'], ['plateblank', 'License Plate Blanking (Gladiator)'],
  ['kfbed', 'Keyfob Bed/Reverse Lights'], ['lockerctl', '2WD/4Hi Axle Locker Control']];
function renderRemap() {
  const btns = ['plus', 'minus', 'res'];
  const remapHtml = btns.map(b => {
    const opts = REMAP_ACTIONS.map(a => `<option ${S.remap[b] === a ? 'selected' : ''}>${a}</option>`).join('');
    return `<div class="switch"><div class="s-name">Cruise ${b === 'res' ? 'RES' : b === 'plus' ? '+' : '−'}</div>
      <select data-remap="${b}">${opts}</select></div>`;
  }).join('');
  const memHtml = MEMORY_ITEMS.map(([k, lbl]) => {
    const on = S.memory[k];
    return `<div class="card"><div class="card-top"><div class="card-name" style="font-size:13px">${lbl}</div>
      <div class="toggle ${on ? 'on' : ''}" data-mem="${k}"></div></div></div>`;
  }).join('');
  $('#workspace').innerHTML = `
    <div class="ws-head"><div class="ws-title">Remap & Non-Menu Memory</div>
      <div class="ws-sub">steering-wheel button assignments + persistent automations (saved locally for the ESP32 standalone port)</div></div>
    <div class="note" style="margin-bottom:14px">These map to Tazer "non-menu" live functions. Most route through unresolved icall dispatch, so assignments are stored locally now and become the config the standalone ESP32 firmware will enforce once their frames are bench-captured.</div>
    <div class="group"><div class="group-h">Cruise-Cluster Button Remapper</div><div class="switch-grid">${remapHtml}</div></div>
    <div class="group"><div class="group-h">Persistent State Automations</div><div class="grid">${memHtml}</div></div>`;
  $$('[data-remap]').forEach(s => s.onchange = () => { S.remap[s.dataset.remap] = s.value; localStorage.setItem('tz_remap', JSON.stringify(S.remap)); toast(`Cruise ${s.dataset.remap} → ${s.value}`, 'ok'); updateEvic(); });
  $$('[data-mem]').forEach(t => t.onclick = () => { const k = t.dataset.mem; S.memory[k] = !S.memory[k]; t.classList.toggle('on', S.memory[k]); localStorage.setItem('tz_memory', JSON.stringify(S.memory)); });
}

/* =========================================================================
   WORKSPACE 5 — DIAGNOSTICS
   ========================================================================= */
const DTC_MODS = ['BCM', 'PCM', 'IPC', 'RFH', 'Airbag', '0x74B', '0x74A'];
function renderDiag() {
  $('#workspace').innerHTML = `
    <div class="ws-head"><div class="ws-title">Diagnostics, Broadcast Watch & Backup Vault</div>
      <div class="ws-sub">fullread snapshot · multi-module DTC (0x19/0x14) · listen-only bitmap watch</div></div>
    <div class="row">
      <div class="col panel"><div class="group-h" style="border:none">Fullread Snapshot & Backup <small>18 config DIDs</small></div>
        <div class="s-actions"><button class="btn go" id="fr-go">READ 18/18</button>
          <button class="btn" id="fr-base">Save as baseline</button>
          <button class="btn amber" id="fr-diff">Diff vs baseline</button></div>
        <div id="fr-out" class="diffbox" style="margin-top:10px">—</div></div>
      <div class="col panel"><div class="group-h" style="border:none">Multi-Module DTC Scanner</div>
        <div class="chiprow" id="dtc-mods">${DTC_MODS.map(m => `<span class="chip" data-dtc="${m}">${m}</span>`).join('')}</div>
        <div class="s-actions" style="margin-top:8px"><button class="btn" id="dtc-read">READ selected</button>
          <button class="btn red" id="dtc-clear">CLEAR selected</button></div>
        <div id="dtc-out" class="diffbox" style="margin-top:10px">—</div></div>
    </div>
    <div class="panel" style="margin-top:14px"><div class="group-h" style="border:none">Passive Broadcast Bitmap Watcher <small>listen-only · 0x3B3/3B4/3C2 CSM · 0x3E8–3EB config</small></div>
      <div id="watch-out" class="diffbox">watching live frames…</div></div>`;
  let snap = null;
  $('#fr-go').onclick = async () => {
    if (!S.connected) return toast('Connect first.', 'warn');
    $('#fr-out').textContent = 'reading…';
    const r = await api.post('/api/fullread', {});
    snap = r.dids;
    $('#fr-out').textContent = `${r.ok}/${r.total} DIDs read @ ${r.module}\n` +
      Object.entries(r.dids).map(([d, v]) => `${d}: ${v || '—'}`).join('\n');
  };
  $('#fr-base').onclick = () => { if (!snap) return toast('Read first.', 'warn'); localStorage.setItem('tz_baseline', JSON.stringify(snap)); toast('Baseline saved.', 'ok'); };
  $('#fr-diff').onclick = async () => {
    const base = JSON.parse(localStorage.getItem('tz_baseline') || 'null');
    if (!base) return toast('No baseline saved.', 'warn');
    const r = await api.post('/api/fullread', {});
    const lines = Object.keys(r.dids).map(d => {
      const a = base[d], b = r.dids[d];
      return a === b ? null : `${d}: <span class="del">${a || '—'}</span> → <span class="add">${b || '—'}</span>`;
    }).filter(Boolean);
    $('#fr-out').innerHTML = lines.length ? lines.join('\n') : 'No changes vs baseline.';
  };
  let sel = new Set(['BCM']);
  $$('#dtc-mods .chip').forEach(c => { if (sel.has(c.dataset.dtc)) c.classList.add('sel'); c.onclick = () => { const m = c.dataset.dtc; sel.has(m) ? sel.delete(m) : sel.add(m); c.classList.toggle('sel'); }; });
  $('#dtc-read').onclick = async () => {
    if (!S.connected) return toast('Connect first.', 'warn');
    const out = [];
    for (const m of sel) { const r = await api.post('/api/dtc/read', { module: m }); out.push(`${m} (${r.id}) ${r.result}: ${r.codes && r.codes.length ? r.codes.join(', ') : 'no codes'}`); }
    $('#dtc-out').textContent = out.join('\n');
  };
  $('#dtc-clear').onclick = async () => {
    const ok = await confirmModal('Clear DTCs on: ' + [...sel].join(', ') + '?', 'Sends UDS 0x14 (clearDiagnosticInformation).'); if (!ok) return;
    const out = [];
    for (const m of sel) { const r = await api.post('/api/dtc/clear', { module: m }); out.push(`${m}: ${r.result}`); }
    $('#dtc-out').textContent = out.join('\n');
  };
}
function paintWatch(frames) {
  const ids = ['0x3B3', '0x3B4', '0x3C2', '0x3E8', '0x3E9', '0x3EA', '0x3EB'];
  const latest = {};
  (frames || []).forEach(f => { if (ids.includes(f.id)) latest[f.id] = f.hex; });
  const el = $('#watch-out'); if (!el) return;
  el.textContent = Object.keys(latest).length
    ? Object.entries(latest).map(([i, h]) => `${i}: ${h}`).join('\n')
    : 'no bitmap broadcasts seen yet (cycle key / confirm bus)';
}

/* ---------- confirm modal (promise) ---------- */
function confirmModal(title, body) {
  return new Promise(res => {
    modal(`<h3>${title}</h3><div class="note">${body}</div>
      <div class="modal-foot"><button class="btn ghost" id="cm-no">Cancel</button><button class="btn go" id="cm-yes">Confirm</button></div>`);
    $('#cm-yes').onclick = () => { closeModal(); res(true); };
    $('#cm-no').onclick = () => { closeModal(); res(false); };
  });
}

/* ---------- EVIC + wheel ---------- */
function updateEvic(msg) { $('#evic-body').textContent = msg || `+:${S.remap.plus || '—'}`; }
function wireWheel() {
  $$('.whl-btn').forEach(b => b.onclick = () => {
    const k = b.dataset.whl;
    const map = { plus: S.remap.plus, minus: S.remap.minus, res: S.remap.res };
    if (k === 'left') return updateEvic('◀ menu');
    if (k === 'canc') return updateEvic('CANCEL');
    if (k === 'onoff') return updateEvic('CRUISE ⏻');
    const act = map[k] || '— unassigned —';
    updateEvic(`${k === 'plus' ? '+' : '−'} → ${act}`);
    toast(`Steering ${k} → ${act}`, 'warn');
  });
}

/* ---------- router + init ---------- */
const WS = { settings: renderSettings, live: renderLive, lightshow: renderLightshow, remap: renderRemap, diag: renderDiag };
function go(ws) {
  S.ws = ws;
  $$('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.ws === ws));
  WS[ws]();
  updateInterlock();
}
async function init() {
  S.cat = await api.get('/api/catalog');
  S.act = await api.get('/api/actuations');
  S.lampcat = await api.get('/api/lamps');
  S.shows = await api.get('/api/shows');

  $$('#mode-seg .seg-btn').forEach(b => b.onclick = () => {
    S.mode = b.dataset.mode; $$('#mode-seg .seg-btn').forEach(x => x.classList.toggle('active', x === b)); refreshPorts();
  });
  $$('#bus-seg .seg-btn').forEach(b => b.onclick = () => { S.bus = b.dataset.bus; $$('#bus-seg .seg-btn').forEach(x => x.classList.toggle('active', x === b)); });
  $('#ports-refresh').onclick = refreshPorts;
  $('#connect-btn').onclick = connect;
  $('#engine-btn').onclick = async () => { const r = await api.post('/api/vehicle', { engine_running: !S.engine }); S.engine = r.engine_running; syncState(); };
  $('#profile-sel').onchange = e => api.post('/api/vehicle', { profile: e.target.value });
  $$('.nav-btn').forEach(b => b.onclick = () => go(b.dataset.ws));
  $('#console-toggle').onclick = () => $('#console').classList.toggle('collapsed');
  $('#console-clear').onclick = () => { $('#console-body').innerHTML = ''; lastFrameN = -1; };
  window.closeModal = closeModal;

  wireWheel(); updateEvic(); await refreshPorts(); await syncState();
  go('settings'); poll();
}
init();
