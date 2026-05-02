// ── State ──────────────────────────────────────────────────────────────────────
let _serverWs   = null;
let _restimWs   = null;
let _srvRetry   = 1000;   // ms, exponential backoff
let _rsRetry    = 2000;
let _srvTimer   = null;
let _rsTimer    = null;
let _bridgeOn   = true;
let _restimUrl  = 'ws://localhost:12346/tcode';

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
      break;
    case 'driver_left':
      setSrvStatus('ok', 'waiting for driver…');
      break;
    case 'ping':
      if (_serverWs && _serverWs.readyState === WebSocket.OPEN)
        _serverWs.send(JSON.stringify({ type: 'pong' }));
      break;
  }
}

// ── Stats display ───────────────────────────────────────────────────────────
function updateStats(d) {
  const pat  = document.getElementById('s-pattern');
  const intn = document.getElementById('s-intensity');
  const vol  = document.getElementById('s-vol');
  const vbar = document.getElementById('vol-bar');

  if (pat)  pat.textContent  = d.pattern   ?? '—';
  if (intn) intn.textContent = d.intensity != null
    ? Math.round(d.intensity * 100) + '%' : '—';

  const volPct = d.vol != null ? Math.round(d.vol * 100) : 0;
  if (vbar) vbar.style.width = volPct + '%';
  if (vol)  vol.textContent  = volPct + '%';

  const rampRow = document.getElementById('ramp-row');
  if (rampRow) {
    if (d.ramp_active) {
      rampRow.style.display = 'flex';
      const pct = Math.round((d.ramp_progress ?? 0) * 100);
      const rbar = document.getElementById('ramp-bar');
      const rval = document.getElementById('s-ramp');
      if (rbar) rbar.style.width = pct + '%';
      if (rval) rval.textContent =
        pct + '% → ' + Math.round((d.ramp_target ?? 0) * 100) + '%';
    } else {
      rampRow.style.display = 'none';
    }
  }

  // Keep legacy status dot happy
  const dot = document.getElementById('status-dot');
  const txt = document.getElementById('status-txt');
  if (dot) dot.style.background = 'var(--ok)';
  if (txt) txt.textContent = '';
}

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

// ── Init ────────────────────────────────────────────────────────────────────
reconnect();
