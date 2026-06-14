// ── Rider join ────────────────────────────────────────────────────────────────
function joinRider() {
  const c = document.getElementById('code-in').value.trim();
  if (c.length === 10) window.location = '/room/' + c + '/rider';
  else alert('Enter a 10-character room code');
}

// ── FAQ toggle ────────────────────────────────────────────────────────────────
function toggleFaq() {
  const body = document.getElementById('faq-body');
  const hint = document.getElementById('faq-hint');
  const open = body.classList.toggle('open');
  hint.innerHTML = open ? '&#9660; Hide' : '&#9654; Show';
}

// ── Public live sessions ──────────────────────────────────────────────────────
async function refreshPublicRooms() {
  try {
    const resp = await fetch('/api/rooms');
    const rooms = await resp.json();
    const section = document.getElementById('live-section');
    const el = document.getElementById('live-sessions-list');
    if (!rooms.length) { section.style.display = 'none'; return; }
    section.style.display = '';
    let html = '<table class="live-table"><thead><tr>' +
      '<th>Code</th><th>Riders</th><th>Uptime</th><th></th>' +
      '</tr></thead><tbody>';
    for (const r of rooms) {
      html += `<tr>
        <td class="td-code">${r.code}</td>
        <td>${r.riders}</td>
        <td>${r.age_minutes}m</td>
        <td class="td-join"><a class="join-link" href="/room/${r.code}/rider">JOIN</a></td>
      </tr>`;
    }
    html += '</tbody></table>';
    el.innerHTML = html;
  } catch(_) {}
}
refreshPublicRooms();
setInterval(refreshPublicRooms, 30000);

// ── Wordmark: perch the ReStim position dot on the V ──────────────────────────
(function () {
  const wm = document.querySelector('.wordmark');
  if (wm && wm.textContent.trim() === 'REDRIVE') {
    wm.innerHTML = 'REDRI<span class="wm-v">V</span>E';
  }
})();

// ── Hero oscilloscope ─────────────────────────────────────────────────────────
// A live trace that morphs through ReDrive's actual pattern shapes — the page
// shows you the signal the product sends.
(function scope() {
  const cv = document.getElementById('scope');
  if (!cv) return;
  const ctx = cv.getContext('2d');
  const readout = document.getElementById('scope-readout');
  const PATTERNS = ['SINE', 'PULSE', 'BURST', 'RAMP', 'EDGE', 'RANDOM'];
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let pat = 0;
  let rng = Array.from({ length: 16 }, () => Math.random());

  function reseed() { rng = Array.from({ length: 16 }, () => Math.random()); }

  // y in -1..1 for the current pattern. p = 0..1 across width, phase scrolls.
  function shape(p, phase) {
    const x = (p * 4 + phase) % 1;       // 4 cycles across the panel
    switch (PATTERNS[pat]) {
      case 'SINE':  return Math.sin(x * Math.PI * 2);
      case 'PULSE': return 1 - Math.abs(2 * x - 1) * 2;            // triangle
      case 'BURST': return (x % 0.5 < 0.26)                         // tone bursts
        ? Math.sin(x * Math.PI * 18) * (x < 0.5 ? 1 : 0.45) : 0;
      case 'RAMP':  return x * 2 - 1;                               // sawtooth
      case 'EDGE':                                                  // rise→hold→drop
        if (x < 0.55) return -1 + (x / 0.55) * 1.78;
        if (x < 0.70) return 0.78;
        return 0.78 - ((x - 0.70) / 0.30) * 1.78;
      case 'RANDOM': {
        const i = Math.floor(x * 16) % 16;
        const f = (x * 16) % 1;
        const a = rng[i], b = rng[(i + 1) % 16];
        return (a + (b - a) * f) * 2 - 1;
      }
    }
    return 0;
  }

  let lastW = -1;
  function sizeCanvas() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = cv.clientWidth, h = cv.clientHeight || 150;
    cv.width = w * dpr; cv.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    lastW = w;
  }

  function draw(phase, head) {
    const w = cv.clientWidth, h = cv.clientHeight || 150;
    ctx.clearRect(0, 0, w, h);

    // baseline
    ctx.strokeStyle = 'rgba(95,176,255,0.12)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();

    const amp = h * 0.33;
    const g = ctx.createLinearGradient(0, 0, w, 0);
    g.addColorStop(0, '#5fb0ff'); g.addColorStop(1, '#b07cff');
    ctx.strokeStyle = g; ctx.lineWidth = 2.4; ctx.lineJoin = 'round';
    ctx.shadowColor = 'rgba(95,176,255,0.85)'; ctx.shadowBlur = 13;

    const N = Math.max(90, Math.floor(w / 3));
    ctx.beginPath();
    for (let i = 0; i <= N; i++) {
      const p = i / N;
      const y = h / 2 - shape(p, phase) * amp;
      i ? ctx.lineTo(p * w, y) : ctx.moveTo(p * w, y);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;

    // scan head
    if (head != null) {
      const hy = h / 2 - shape(head, phase) * amp;
      ctx.fillStyle = '#fff';
      ctx.beginPath(); ctx.arc(head * w, hy, 2.6, 0, Math.PI * 2); ctx.fill();
    }
  }

  if (readout) readout.textContent = PATTERNS[pat];
  sizeCanvas();

  if (reduce) { draw(0.12, null); return; }   // static frame, no animation

  let t0 = null;
  function frame(ts) {
    if (t0 === null) t0 = ts;
    const t = (ts - t0) / 1000;
    if (cv.clientWidth !== lastW) sizeCanvas();
    draw(t * 0.35, (t * 0.18) % 1);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  setInterval(() => {
    pat = (pat + 1) % PATTERNS.length;
    if (PATTERNS[pat] === 'RANDOM') reseed();
    if (readout) readout.textContent = PATTERNS[pat];
  }, 3200);
})();
