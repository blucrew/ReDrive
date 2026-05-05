// ── State ──────────────────────────────────────────────────────────────────────
let _serverWs        = null;
let _restimWs        = null;
let _srvRetry        = 1000;   // ms, exponential backoff
let _rsRetry         = 2000;
let _srvTimer        = null;
let _rsTimer         = null;
let _bridgeOn        = true;
let _restimUrl       = 'ws://localhost:12346/tcode';
let _driverConnected = false;

// ── Server WebSocket ────────────────────────────────────────────────────────
function connectServer() {
  if (_serverWs) { try { _serverWs.close(); } catch(_) {} }
  setSrvStatus('warn', 'connecting…');
  _serverWs = new WebSocket(RIDER_WS);

  _serverWs.onopen = () => {
    _srvRetry = 1000;
    setSrvStatus('ok', 'connected');
  };

  _serverWs.onmessage = (e) => {
    const data = e.data;
    // T-code strings start with an axis letter, not '{'
    if (data[0] !== '{') {
      forwardTcode(data);
      return;
    }
    try { handleServerMsg(JSON.parse(data)); } catch(_) {}
  };

  _serverWs.onclose = () => {
    setSrvStatus('err', 'reconnecting…');
    clearTimeout(_srvTimer);
    _srvTimer = setTimeout(() => { if (_bridgeOn) connectServer(); }, _srvRetry);
    _srvRetry = Math.min(_srvRetry * 1.5, 15000);
  };

  _serverWs.onerror = () => setSrvStatus('err', 'error');
}

// ── ReStim WebSocket ────────────────────────────────────────────────────────
function connectRestim() {
  if (_restimWs) { try { _restimWs.close(); } catch(_) {} }
  setRsStatus('warn', 'connecting…');
  _restimUrl = document.getElementById('restim-url-input')?.value.trim()
               || 'ws://localhost:12346/tcode';
  _restimWs = new WebSocket(_restimUrl);

  _restimWs.onopen = () => {
    _rsRetry = 2000;
    setRsStatus('ok', 'connected');
  };

  _restimWs.onclose = () => {
    setRsStatus('err', 'waiting for ReStim…');
    clearTimeout(_rsTimer);
    _rsTimer = setTimeout(() => { if (_bridgeOn) connectRestim(); }, _rsRetry);
    _rsRetry = Math.min(_rsRetry * 1.5, 10000);
  };

  _restimWs.onerror = () => setRsStatus('err', 'cannot reach ReStim');
}

function forwardTcode(cmd) {
  if (_restimWs && _restimWs.readyState === WebSocket.OPEN) {
    _restimWs.send(cmd);
  }
}

// ── Server message handler ──────────────────────────────────────────────────
function handleServerMsg(msg) {
  switch (msg.type) {
    case 'rider_state':
      updateStats(msg);
      break;
    case 'bottle_status':
      handleBottle(msg);
      break;
    case 'driver_joined':
      setSrvStatus('ok', 'driver connected');
      _driverConnected = true;
      break;
    case 'driver_left':
      setSrvStatus('ok', 'waiting for driver…');
      _driverConnected = false;
      updateStats({ driver_connected: false });
      break;
    case 'ping':
      if (_serverWs && _serverWs.readyState === WebSocket.OPEN)
        _serverWs.send(JSON.stringify({ type: 'pong' }));
      break;
  }
}

// ── Feel text ───────────────────────────────────────────────────────────────
// Maps pattern name → [headline, flavour descriptor]
// Must match PATTERNS list in engine.py: Hold, Sine, Ramp ↑, Ramp ↓, Pulse, Burst, Random, Edge
const _PATTERN_FEEL = {
  'Hold':    ['Steady hold',       'constant pressure'],
  'Sine':    ['Rhythmic waves',    'smooth sine pulse'],
  'Ramp ↑':  ['Building up',       'rising intensity'],
  'Ramp ↓':  ['Easing down',       'falling intensity'],
  'Pulse':   ['Sharp pulses',      'quick bursts'],
  'Burst':   ['Burst pattern',     'repeated surges'],
  'Random':  ['Varied sensation',  'unpredictable rhythm'],
  'Edge':    ['Edging pattern',    'teasing waves'],
};

function buildFeelText(d) {
  const pat   = d.pattern || 'Hold';
  const vol   = d.vol     ?? 0;
  const hz    = Math.max(0.05, d.hz   ?? 0.5);
  const depth = d.depth   ?? 1.0;

  if (!d.driver_connected) {
    return { main: 'Waiting for driver…', sub: '' };
  }
  if (vol < 0.005) {
    return { main: 'Idle', sub: 'signal paused' };
  }

  const known = _PATTERN_FEEL[pat];
  const main  = known ? known[0] : pat;
  const desc  = known ? known[1] : 'active';
  const hzStr = hz.toFixed(1) + ' Hz';
  const sub   = `${hzStr}  ·  ${desc}  ·  ${Math.round(depth * 100)}% depth`;

  return { main, sub };
}

// ── Stats display ───────────────────────────────────────────────────────────
function updateStats(d) {
  _driverConnected = !!d.driver_connected;

  const vol       = d.vol       ?? 0;
  const hz        = Math.max(0.05, d.hz ?? 0.5);
  const beta      = d.beta      ?? 5000;
  const intensity = d.intensity ?? 0;

  // ── Driver name ──────────────────────────────────────────────────────────
  const nameEl = document.getElementById('driver-name-disp');
  if (nameEl && d.driver_name) nameEl.textContent = d.driver_name;

  // ── Orb ──────────────────────────────────────────────────────────────────
  const orb = document.getElementById('feel-orb');
  if (orb) {
    const quiet = !_driverConnected || intensity < 0.01;
    orb.classList.toggle('quiet', quiet);

    if (!quiet) {
      // Breathing speed tracks stimulation frequency
      const period = (1 / hz).toFixed(2);
      orb.style.animationDuration = period + 's';

      // Glow and size scale with output volume
      const sz   = Math.round(90 + vol * 36);          // 90 → 126 px
      const g1   = Math.round(18 + vol * 56);          // inner glow radius
      const g2   = Math.round(50 + vol * 80);          // outer glow radius
      const a1   = (0.12 + vol * 0.45).toFixed(2);
      const a2   = (0.03 + vol * 0.12).toFixed(2);
      orb.style.width     = sz + 'px';
      orb.style.height    = sz + 'px';
      orb.style.boxShadow =
        `0 0 ${g1}px rgba(95,163,255,${a1}), 0 0 ${g2}px rgba(95,163,255,${a2})`;
    } else {
      orb.style.animationDuration = '';
      orb.style.width     = '';
      orb.style.height    = '';
      orb.style.boxShadow = '';
    }
  }

  // ── Feel text ─────────────────────────────────────────────────────────────
  const ft       = buildFeelText(d);
  const feelText = document.getElementById('feel-text');
  const feelSub  = document.getElementById('feel-sub');
  if (feelText) feelText.textContent = ft.main;
  if (feelSub)  feelSub.textContent  = ft.sub;

  // ── Beta position dot ─────────────────────────────────────────────────────
  // beta 0 = fully A-side (left), beta 9999 = fully B-side (right)
  const betaDot = document.getElementById('beta-dot');
  if (betaDot) {
    betaDot.style.left = ((beta / 9999) * 100).toFixed(1) + '%';
  }

  // ── Output bar ────────────────────────────────────────────────────────────
  const volBar    = document.getElementById('vol-bar');
  const volPctEl  = document.getElementById('vol-pct');
  const volPctVal = Math.round(vol * 100);
  if (volBar)   volBar.style.width   = volPctVal + '%';
  if (volPctEl) volPctEl.textContent = _driverConnected ? (volPctVal + '%') : '—';

  // ── Ramp row ──────────────────────────────────────────────────────────────
  const rampRow = document.getElementById('ramp-row');
  if (rampRow) {
    if (d.ramp_active) {
      rampRow.style.display = 'flex';
      const pct  = Math.round((d.ramp_progress ?? 0) * 100);
      const rbar = document.getElementById('ramp-bar');
      const rval = document.getElementById('s-ramp');
      if (rbar) rbar.style.width = pct + '%';
      if (rval) rval.textContent =
        pct + '% → ' + Math.round((d.ramp_target ?? 0) * 100) + '%';
    } else {
      rampRow.style.display = 'none';
    }
  }

  // ── Bottle overlay (driven from rider_state so it works on page load + auto-hides) ──
  if (d.bottle_active !== undefined) {
    const overlay = document.getElementById('bottle-overlay');
    const cd      = document.getElementById('bottle-cd');
    if (overlay) {
      if (d.bottle_active) {
        overlay.style.display = 'flex';
        if (cd) cd.textContent = Math.ceil(d.bottle_remaining ?? 0) + 's';
      } else {
        overlay.style.display = 'none';
      }
    }
  }
}

// ── Bottle overlay ──────────────────────────────────────────────────────────
function handleBottle(msg) {
  const overlay = document.getElementById('bottle-overlay');
  const cd      = document.getElementById('bottle-cd');
  if (!overlay) return;
  if (msg.active ?? (msg.remaining > 0)) {
    overlay.style.display = 'flex';
    if (cd) cd.textContent = (msg.remaining ?? 0) + 's';
  } else {
    overlay.style.display = 'none';
  }
}

// ── Status helpers ──────────────────────────────────────────────────────────
function setSrvStatus(level, text) {
  const dot = document.getElementById('srv-dot');
  const txt = document.getElementById('srv-txt');
  if (dot) dot.className = 'bdot ' + level;
  if (txt) txt.textContent = text;
}

function setRsStatus(level, text) {
  const dot = document.getElementById('rs-dot');
  const txt = document.getElementById('rs-txt');
  if (dot) dot.className = 'bdot ' + level;
  if (txt) txt.textContent = text;
}

// ── Public controls ─────────────────────────────────────────────────────────
function reconnect() {
  _bridgeOn = true;
  _srvRetry = 1000;
  _rsRetry  = 2000;
  clearTimeout(_srvTimer);
  clearTimeout(_rsTimer);
  connectServer();
  connectRestim();
}

// ── Tab visibility keepalive ─────────────────────────────────────────────────
// When a backgrounded tab comes back to the foreground, immediately ping so
// the server knows we're alive (prevents the room from being culled).
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  if (_serverWs && _serverWs.readyState === WebSocket.OPEN) {
    try { _serverWs.send(JSON.stringify({ type: 'ping' })); } catch(_) {}
  }
});

// ── Init ────────────────────────────────────────────────────────────────────
reconnect();
