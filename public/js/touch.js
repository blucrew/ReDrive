// ROOM_CODE injected by server
const _ROOM_CODE = (typeof ROOM_CODE !== 'undefined') ? ROOM_CODE : null;
const _BASE = _ROOM_CODE ? '/room/' + _ROOM_CODE : '';

// ── ReStim bridge ──────────────────────────────────────────────────────────
// In relay mode, the rider's browser forwards T-code from the relay WS
// directly to their local ReStim device via WebSocket.
let _restimWs = null;
let _restimUrl = localStorage.getItem('reDriveRestimUrl') || 'ws://localhost:12346/tcode';
let _restimEnabled = localStorage.getItem('reDriveRestimEnabled') !== 'false';
let _restimConnected = false;

function connectRestim() {
  if (!_restimEnabled || _restimWs) return;
  try {
    const ws = new WebSocket(_restimUrl);
    ws.onopen = () => {
      _restimWs = ws;
      _restimConnected = true;
      updateRestimStatus();
      console.log('ReStim connected:', _restimUrl);
    };
    ws.onclose = () => {
      _restimWs = null;
      _restimConnected = false;
      updateRestimStatus();
      if (_restimEnabled) setTimeout(connectRestim, 3000);
    };
    ws.onerror = () => { try { ws.close(); } catch(_) {} };
  } catch(e) {
    console.warn('ReStim connect error:', e);
    setTimeout(connectRestim, 5000);
  }
}

function disconnectRestim() {
  if (_restimWs) {
    try { _restimWs.close(); } catch(_) {}
    _restimWs = null;
  }
  _restimConnected = false;
  updateRestimStatus();
}

function updateRestimStatus() {
  const el = document.getElementById('restim-status');
  if (!el) return;
  if (!_restimEnabled) {
    el.textContent = 'ReStim: disabled';
    el.style.color = 'var(--fg2)';
  } else if (_restimConnected) {
    el.textContent = 'ReStim: connected';
    el.style.color = 'var(--ok)';
  } else {
    el.textContent = 'ReStim: connecting...';
    el.style.color = 'var(--warn)';
  }
}

// ── Connection status ────────────────────────────────────────────────────────
function setConn(ok) {
  document.getElementById('cdot').style.background = ok ? 'var(--ok)' : 'var(--err)';
  document.getElementById('ctxt').textContent = ok ? 'Connected' : 'Connection lost \u2014 retrying\u2026';
}

// ── Power bar ────────────────────────────────────────────────────────────────
function updatePower(v) {
  v = Math.max(0, Math.min(1, v || 0));
  const bar = document.getElementById('power-bar');
  const pct = document.getElementById('power-pct');
  bar.style.width = Math.round(v * 100) + '%';
  pct.textContent = v > 0.01 ? Math.round(v * 100) + '%' : '\u2014';
  v > 0.01 ? bar.classList.add('live') : bar.classList.remove('live');
}

// ── STOP / RESUME ────────────────────────────────────────────────────────────
let _riderStopped = false;
function doStop() {
  if (_riderStopped) {
    // Resume: re-enable ReStim forwarding
    _riderStopped = false;
    const btn = document.getElementById('stop-btn');
    if (btn) { btn.textContent = '\u25a0 STOP'; btn.style.background = 'var(--err)'; }
    return;
  }
  // Stop: tell server to zero output, pause ReStim forwarding
  _riderStopped = true;
  fetch(_BASE + '/command', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({stop:true})});
  // Send zero to ReStim directly
  if (_restimWs && _restimWs.readyState === WebSocket.OPEN) {
    try { _restimWs.send('V00000I200 L00000I200 L15000I200'); } catch(_) {}
  }
  const btn = document.getElementById('stop-btn');
  if (btn) { btn.textContent = '\u25b6 RESUME'; btn.style.background = 'var(--ok)'; }
}

// ── Room code copy ────────────────────────────────────────────────────────────
if (_ROOM_CODE) {
  const btn = document.getElementById('room-code-btn');
  btn.textContent = _ROOM_CODE;
}
function copyRoomCode(btn) {
  if (!_ROOM_CODE) return;
  const url = location.origin + '/room/' + _ROOM_CODE + '/rider';
  navigator.clipboard.writeText(url)
    .then(() => { const t = btn.textContent; btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = t, 1500); })
    .catch(() => {});
}

// ── State poll removed - now received via WS pushes ─────────────────────────
let _bottleOverlayActive = false;
let _bottleOverlayMode   = 'normal';
let _bottleOverlayIv     = null;
let _bottlePhaseTimer    = null;

// One initial fetch so the page isn't blank before WS connects
(async function initialStateFetch() {
  try {
    const d = await (await fetch(_BASE + '/rider-state')).json();
    setConn(true);
    updatePower(d.intensity ?? 0);
    if (d.bottle_active) showBottleOverlay(d.bottle_mode || 'normal', d.bottle_remaining || 0);
    else if (_bottleOverlayActive) hideBottleOverlay();
  } catch(_) {}
})();

// ── Bottle overlay ───────────────────────────────────────────────────────────
function showDeepHuffDots(containerEl) {
  containerEl.innerHTML = '';
  const dots = [];
  for (let i = 0; i < 10; i++) {
    const d = document.createElement('span');
    d.textContent = '\u25cf';
    d.style.cssText = 'font-size:20px;margin:0 4px;transition:opacity 0.5s;color:#ffcc14';
    containerEl.appendChild(d); dots.push(d);
  }
  let idx = 0;
  const iv = setInterval(() => {
    if (idx < dots.length) { dots[idx].style.opacity = '0'; idx++; }
    else clearInterval(iv);
  }, 2000);
  return iv;
}
function _clearBottleTimers() {
  if (_bottleOverlayIv)  { clearInterval(_bottleOverlayIv);  _bottleOverlayIv  = null; }
  if (_bottlePhaseTimer) { clearTimeout(_bottlePhaseTimer);  _bottlePhaseTimer = null; }
}
function showBottleOverlay(mode, remaining) {
  const ov      = document.getElementById('bottle-overlay');
  const heading = document.getElementById('bottle-overlay-heading');
  const sub     = document.getElementById('bottle-overlay-sub');
  const dots    = document.getElementById('bottle-overlay-dots');
  const cd      = document.getElementById('bottle-overlay-cd');
  if (!ov) return;
  if (_bottleOverlayActive && _bottleOverlayMode === mode) { cd.textContent = Math.ceil(remaining) + 's'; return; }
  _clearBottleTimers();
  _bottleOverlayActive = true; _bottleOverlayMode = mode;
  dots.innerHTML = ''; ov.style.display = 'flex';
  if (mode === 'normal') {
    heading.textContent = 'Take a huff!'; sub.textContent = ''; cd.textContent = Math.ceil(remaining) + 's';
  } else if (mode === 'deep_huff') {
    heading.textContent = 'DEEP HUFF'; sub.textContent = 'HOLD IT\u2026'; cd.textContent = '';
    _bottleOverlayIv = showDeepHuffDots(dots);
  } else if (mode === 'double_hit') {
    heading.textContent = 'HIT #1 \ud83e\uddf4'; sub.textContent = ''; cd.textContent = '';
    _bottlePhaseTimer = setTimeout(() => {
      ov.style.display = 'none';
      _bottlePhaseTimer = setTimeout(() => {
        ov.style.display = 'flex';
        heading.textContent = 'HIT #2 \ud83e\uddf4'; sub.textContent = ''; cd.textContent = '';
      }, 15000);
    }, 10000);
  }
}
function hideBottleOverlay() {
  _bottleOverlayActive = false; _clearBottleTimers();
  const ov = document.getElementById('bottle-overlay');
  if (ov) ov.style.display = 'none';
}

// Dismiss poppers overlay via Esc or click (safety: rider must be able to reach STOP)
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && _bottleOverlayActive) hideBottleOverlay();
});
document.addEventListener('DOMContentLoaded', () => {
  const ov = document.getElementById('bottle-overlay');
  if (ov) ov.addEventListener('click', () => { if (_bottleOverlayActive) hideBottleOverlay(); });
});

// ── Rider name ────────────────────────────────────────────────────────────────
let _riderWs = null, _riderNameTimer = null;
(function initRiderName() {
  const inp = document.getElementById('rider-name-input');
  if (!inp) return;
  const saved = localStorage.getItem('reDriveRiderName') || '';
  if (saved) inp.value = saved;
  inp.addEventListener('input', () => {
    const val = inp.value;
    localStorage.setItem('reDriveRiderName', val);
    clearTimeout(_riderNameTimer);
    _riderNameTimer = setTimeout(() => {
      if (_riderWs && _riderWs.readyState === WebSocket.OPEN)
        _riderWs.send(JSON.stringify({type:'set_name', name:val.trim()}));
    }, 600);
  });
})();

// ── Riders panel ──────────────────────────────────────────────────────────────
function renderRidersPanel(data) {
  const panel = document.getElementById('riders-panel');
  if (!panel) return;
  const parts = (data.participants || []);
  if (!parts.length) { panel.style.display = 'none'; return; }
  panel.style.display = 'flex';
  panel.textContent = '';
  parts.forEach(p => {
    let bg;
    if (p.avatar && p.avatar.startsWith('data:image/')) {
      bg = 'background-image:url(' + JSON.stringify(p.avatar) + ');background-size:cover;background-position:top center';
    } else if (p.anatomy) {
      const url = '/touch_assets/anatomy/' + p.anatomy.split('/').map(encodeURIComponent).join('/');
      bg = "background-image:url('" + url + "');background-size:cover;background-position:top center";
    } else {
      bg = 'background:#222';
    }
    const card = document.createElement('div');
    card.className = 'rider-card';
    const avatar = document.createElement('div');
    avatar.className = 'rider-avatar';
    avatar.style.cssText = bg + ';position:relative';
    const label = document.createElement('div');
    label.style.cssText = 'position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,0.65);font-size:8px;color:#ccc;text-align:center;padding:2px;border-radius:0 0 5px 5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
    label.textContent = p.name || 'Rider';
    avatar.appendChild(label);
    card.appendChild(avatar);
    panel.appendChild(card);
  });
}

// ── Emotes ────────────────────────────────────────────────────────────────────
function sendLike(emoji) {
  if (_riderWs && _riderWs.readyState === WebSocket.OPEN)
    _riderWs.send(JSON.stringify({type:'like', emoji}));
}

// ── Driver connected indicator ────────────────────────────────────────────────
function updateDriverStatus(connected, name) {
  const el = document.getElementById('driver-status');
  if (!el) return;
  const color = connected ? 'var(--ok)' : 'var(--err)';
  const displayName = name || (connected ? 'Anonymous' : 'None');
  el.textContent = '';
  const dot = document.createElement('span');
  dot.style.color = color;
  dot.textContent = '\u25cf';
  el.appendChild(dot);
  el.appendChild(document.createTextNode(' Driver: ' + displayName));
}

// ── Room WebSocket (state, participants, driver status, bottle) ──────────────
(function connectRoomWS() {
  const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  let wsUrl;
  if (_ROOM_CODE) {
    wsUrl = wsProto + '//' + location.host + '/room/' + _ROOM_CODE + '/rider-ws';
  } else {
    // LAN mode
    wsUrl = wsProto + '//' + location.host + '/rider-ws';
  }

  let pingInterval = null;

  function connect() {
    try {
      const ws = new WebSocket(wsUrl);
      _riderWs = ws;
      ws.onopen = () => {
        setConn(true);
        const name = localStorage.getItem('reDriveRiderName') || '';
        if (name) ws.send(JSON.stringify({type:'set_name', name}));
        // Send saved avatar immediately so driver sees it on first connect
        const savedAvatar = localStorage.getItem('reDriveAnatomyB64');
        if (savedAvatar) ws.send(JSON.stringify({type:'set_avatar', data: savedAvatar}));
        if (pingInterval) clearInterval(pingInterval);
        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({type: "ping"}));
          }
        }, 30000);
      };
      ws.onmessage = ev => {
        const d = ev.data;
        // T-code (raw string, not JSON) - forward to local ReStim
        if (!d.startsWith('{')) {
          if (!_riderStopped && _restimWs && _restimWs.readyState === WebSocket.OPEN) {
            try { _restimWs.send(d); } catch(_) {}
          }
          return;
        }
        try {
          const msg = JSON.parse(d);
          switch (msg.type) {
            case 'rider_state':
              setConn(true);
              updatePower(msg.intensity ?? 0);
              // Update bottle countdown from periodic rider_state push
              if (msg.bottle_active) showBottleOverlay(msg.bottle_mode || 'normal', msg.bottle_remaining || 0);
              else if (_bottleOverlayActive) hideBottleOverlay();
              break;
            case 'bottle_status':
              if (msg.active) showBottleOverlay(msg.mode || 'normal', msg.remaining || 0);
              else if (_bottleOverlayActive) hideBottleOverlay();
              break;
            case 'driver_status':
              updateDriverStatus(msg.connected, msg.name);
              break;
            case 'participants_update': {
              const dbDiv  = document.getElementById('driven-by');
              const dbName = document.getElementById('driven-by-name');
              if (dbDiv && dbName) {
                if (msg.driver_name) { dbName.textContent = msg.driver_name; dbDiv.style.display = 'block'; }
                else dbDiv.style.display = 'none';
              }
              renderRidersPanel(msg);
              break;
            }
            case 'pong':
              setConn(true);
              break;
          }
        } catch(_) {}
      };
      ws.onclose = () => {
        _riderWs = null;
        if (pingInterval) { clearInterval(pingInterval); pingInterval = null; }
        setTimeout(connect, 3000);
      };
      ws.onerror = () => { try { ws.close(); } catch(_) {} };
    } catch(_) { setTimeout(connect, 3000); }
  }
  connect();
})();

// ── Rider avatar ─────────────────────────────────────────────────────────────
const _AVATAR_MAX_BYTES = 400 * 1024; // 400KB base64 limit (server caps at 512KB)
const _AVATAR_MAX_DIM = 512;          // max width or height in pixels

// ── Crop modal state ──────────────────────────────────────────────────────────
let _cropImg = null;      // original Image element
let _cropObjUrl = null;   // object URL to revoke
let _cropOff = { x:0, y:0 };
let _cropDrag = null;     // {startX, startY, origX, origY} during drag
let _cropScale = 1;
let _cropW = 0, _cropH = 0; // scaled image dimensions

function onAnatFileSelected(input) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0]; input.value = '';
  _showCropModal(file);
}

function _showCropModal(file) {
  const modal = document.getElementById('crop-modal');
  const imgEl = document.getElementById('crop-img');
  const vp = document.getElementById('crop-viewport');
  const img = new Image();
  _cropObjUrl = URL.createObjectURL(file);
  img.onload = () => {
    _cropImg = img;
    imgEl.src = img.src;
    modal.style.display = 'flex';
    // Read dimensions after the modal is visible
    requestAnimationFrame(() => {
      const vpW = vp.offsetWidth, vpH = vp.offsetHeight;
      _cropScale = Math.max(vpW / img.width, vpH / img.height);
      _cropW = img.width * _cropScale;
      _cropH = img.height * _cropScale;
      imgEl.style.width = _cropW + 'px';
      imgEl.style.height = _cropH + 'px';
      _cropOff.x = (vpW - _cropW) / 2;
      _cropOff.y = (vpH - _cropH) / 2;
      _cropApplyOffset();
    });
  };
  img.onerror = () => { URL.revokeObjectURL(_cropObjUrl); _cropObjUrl = null; };
  img.src = _cropObjUrl;
  // Attach drag listeners to viewport
  vp.onpointerdown = _cropPointerDown;
  vp.onpointermove = _cropPointerMove;
  vp.onpointerup = _cropPointerUp;
  vp.onpointercancel = _cropPointerUp;
}

function _cropApplyOffset() {
  const el = document.getElementById('crop-img');
  el.style.left = _cropOff.x + 'px';
  el.style.top = _cropOff.y + 'px';
}

function _cropClamp() {
  const vp = document.getElementById('crop-viewport');
  const vpW = vp.offsetWidth, vpH = vp.offsetHeight;
  _cropOff.x = Math.min(0, Math.max(vpW - _cropW, _cropOff.x));
  _cropOff.y = Math.min(0, Math.max(vpH - _cropH, _cropOff.y));
}

function _cropPointerDown(e) {
  e.preventDefault();
  this.setPointerCapture(e.pointerId);
  _cropDrag = { startX: e.clientX, startY: e.clientY, origX: _cropOff.x, origY: _cropOff.y };
}
function _cropPointerMove(e) {
  if (!_cropDrag) return;
  _cropOff.x = _cropDrag.origX + (e.clientX - _cropDrag.startX);
  _cropOff.y = _cropDrag.origY + (e.clientY - _cropDrag.startY);
  _cropClamp();
  _cropApplyOffset();
}
function _cropPointerUp() { _cropDrag = null; }

function _cropConfirm() {
  if (!_cropImg) return;
  const vp = document.getElementById('crop-viewport');
  const vpW = vp.offsetWidth, vpH = vp.offsetHeight;
  // Source rect in original image coordinates
  const srcX = -_cropOff.x / _cropScale;
  const srcY = -_cropOff.y / _cropScale;
  const srcW = vpW / _cropScale;
  const srcH = vpH / _cropScale;
  // Output at 9:16, max 512px tall
  const outH = Math.min(_AVATAR_MAX_DIM, Math.round(srcH));
  const outW = Math.round(outH * 9 / 16);
  const canvas = document.createElement('canvas');
  canvas.width = outW; canvas.height = outH;
  canvas.getContext('2d').drawImage(_cropImg, srcX, srcY, srcW, srcH, 0, 0, outW, outH);
  // Compress to JPEG under size limit
  let quality = 0.85;
  let dataUrl = canvas.toDataURL('image/jpeg', quality);
  while (dataUrl.length > _AVATAR_MAX_BYTES && quality > 0.2) {
    quality -= 0.1;
    dataUrl = canvas.toDataURL('image/jpeg', quality);
  }
  // Save and send
  localStorage.setItem('reDriveAnatomyB64', dataUrl);
  if (_riderWs && _riderWs.readyState === WebSocket.OPEN) {
    _riderWs.send(JSON.stringify({ type: 'set_avatar', data: dataUrl }));
  }
  _cropCleanup();
  const btn = document.getElementById('upload-avatar-btn');
  if (btn) {
    btn.childNodes[0].textContent = 'Saved!';
    setTimeout(() => { btn.childNodes[0].textContent = '\u{1F4F7} My Pic'; }, 2000);
  }
}

function _cropCancel() { _cropCleanup(); }

function _cropCleanup() {
  document.getElementById('crop-modal').style.display = 'none';
  if (_cropObjUrl) { URL.revokeObjectURL(_cropObjUrl); _cropObjUrl = null; }
  _cropImg = null; _cropDrag = null;
}

// ── ReStim settings UI ─────────────────────────────────────────────────────
function toggleSettings() {
  const panel = document.getElementById('settings-panel');
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

function onRestimToggle(checked) {
  _restimEnabled = checked;
  localStorage.setItem('reDriveRestimEnabled', checked ? 'true' : 'false');
  if (checked) {
    connectRestim();
  } else {
    disconnectRestim();
  }
}

function saveRestimUrl() {
  const input = document.getElementById('restim-url-input');
  const url = input.value.trim();
  if (!url) return;
  _restimUrl = url;
  localStorage.setItem('reDriveRestimUrl', url);
  disconnectRestim();
  if (_restimEnabled) setTimeout(connectRestim, 500);
}

// Initialize ReStim settings UI and connection
(function initRestim() {
  const restimToggle = document.getElementById('restim-toggle');
  if (restimToggle) restimToggle.checked = _restimEnabled;
  const restimUrlInput = document.getElementById('restim-url-input');
  if (restimUrlInput) restimUrlInput.value = _restimUrl;
  updateRestimStatus();
  if (_restimEnabled) connectRestim();
})();

// Avatar is sent via WS on connect (see ws.onopen above). No filesystem upload needed.
