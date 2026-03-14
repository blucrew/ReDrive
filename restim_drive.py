"""restim_drive.py — ReStim pattern engine with remote "driver" control.

Rider:   python restim_drive.py
Driver:  open  http://<rider-ip>:<ctrl_port>  in any browser (desktop or phone)

The RIDER always controls maximum power on their own device.
The driver controls pattern selection, relative intensity (0–100% of rider's max),
beta position, and alpha oscillation.

Install: pip install aiohttp
"""

import asyncio
import json
import math
import queue
import random as _rng
import threading
import tkinter as tk
from dataclasses import dataclass, asdict, field, fields as dc_fields
from pathlib import Path
from tkinter import ttk
from typing import Optional

import aiohttp
from aiohttp import web


# ── OGB-inspired dark theme palette ──────────────────────────────────────────

BG     = "#111111"
BG2    = "#1a1a1a"
BG3    = "#222222"
BORDER = "#2a2a2a"
FG     = "#ffffff"
FG2    = "#999999"
ACCENT = "#5fa3ff"
SUCCESS= "#4caf50"
ERROR  = "#f44336"
WARN   = "#ff9800"


# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "restim_drive_config.json"

PATTERNS = ["Hold", "Sine", "Ramp ↑", "Ramp ↓", "Pulse", "Burst", "Random", "Edge"]


@dataclass
class DriveConfig:
    restim_url:       str   = "ws://localhost:12346"
    ctrl_port:        int   = 8765          # HTTP port for driver browser UI
    # T-code axes (must match ReStim Preferences → Funscript/T-Code)
    axis_volume:      str   = "L0"
    axis_beta:        str   = "L1"
    axis_alpha:       str   = "L2"
    # Output floor: min T-code value sent when intensity > 0
    tcode_floor:      int   = 0
    # Beta positions  (0 = Left ←── 5000 = Centre ──→ 9999 = Right)
    beta_off:         int   = 9999
    beta_light:       int   = 8099
    beta_active:      int   = 5000
    beta_thresh:      float = 0.35
    # Alpha oscillation
    alpha_min_hz:     float = 0.3
    alpha_max_hz:     float = 1.5
    alpha_min_amp:    float = 0.20
    alpha_max_amp:    float = 0.45
    # Loop tick
    send_interval_ms: int   = 50

    def save(self):
        try:
            CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2))
        except Exception:
            pass

    @classmethod
    def load(cls) -> "DriveConfig":
        if CONFIG_FILE.exists():
            try:
                d = json.loads(CONFIG_FILE.read_text())
                valid = {f.name for f in dc_fields(cls)}
                return cls(**{k: v for k, v in d.items() if k in valid})
            except Exception:
                pass
        cfg = cls()
        cfg.save()
        return cfg


# ── T-code helpers ────────────────────────────────────────────────────────────

def _tv(v: float) -> str:
    return str(int(max(0.0, min(1.0, v)) * 9999)).zfill(4)


def _tv_floor(v: float, floor_val: int) -> str:
    if v <= 0.0:
        return "0000"
    return str(max(floor_val, min(9999, int(v * 9999)))).zfill(4)


# ── Pattern engine ────────────────────────────────────────────────────────────

class PatternEngine:
    """Stateful pattern generator — call tick(dt) each frame → float 0..1.

    intensity is a relative value (0..1 of whatever the rider's device max is).
    The rider always controls absolute power limits on their own hardware.
    """

    def __init__(self):
        self.pattern:      str   = "Hold"
        self.intensity:    float = 0.0
        self.hz:           float = 0.5
        self._phase:       float = 0.0
        self._rng_prev:    float = 0.0
        self._rng_next:    float = 0.0
        self._rng_t:       float = 0.0
        self._edge_phase:  int   = 0     # 0=ramp, 1=hold, 2=drop, 3=rest
        self._edge_t:      float = 0.0

    def tick(self, dt: float) -> float:
        """Advance by dt seconds, return current output 0..1."""
        if self.intensity <= 0.0:
            self._phase = 0.0
            return 0.0

        hz  = max(0.01, self.hz)
        p   = self._phase
        i   = self.intensity
        pat = self.pattern

        if pat == "Hold":
            val = i

        elif pat == "Sine":
            val = i * (0.5 + 0.5 * math.sin(2 * math.pi * p))

        elif pat == "Ramp ↑":
            val = i * (p % 1.0)

        elif pat == "Ramp ↓":
            val = i * (1.0 - p % 1.0)

        elif pat == "Pulse":
            # triangle wave 0→1→0
            t = p % 1.0
            val = i * (1.0 - abs(2.0 * t - 1.0))

        elif pat == "Burst":
            # 50% duty square wave
            val = i if (p % 1.0) < 0.5 else 0.0

        elif pat == "Random":
            # smooth interpolated random
            self._rng_t += dt * hz
            if self._rng_t >= 1.0:
                self._rng_t -= 1.0
                self._rng_prev = self._rng_next
                self._rng_next = _rng.random()
            val = i * (self._rng_prev + (self._rng_next - self._rng_prev) * self._rng_t)

        elif pat == "Edge":
            # slow ramp → hold near peak → quick drop → short rest → repeat
            period  = 1.0 / hz
            phases  = [period * 0.45, period * 0.30, period * 0.10, period * 0.15]
            ep      = self._edge_phase
            if ep == 0:
                val = i * min(1.0, self._edge_t / phases[0]) * 0.92
            elif ep == 1:
                val = i * 0.92
            elif ep == 2:
                val = i * 0.92 * max(0.0, 1.0 - self._edge_t / phases[2])
            else:
                val = 0.0
            self._edge_t += dt
            if self._edge_t >= phases[ep]:
                self._edge_t = 0.0
                self._edge_phase = (ep + 1) % 4

        else:
            val = i

        self._phase = (p + hz * dt) % 1.0
        return max(0.0, min(1.0, val))

    def set_command(self, cmd: dict):
        if "pattern" in cmd:
            name = cmd["pattern"]
            if name in PATTERNS and name != self.pattern:
                self._phase      = 0.0
                self._edge_phase = 0
                self._edge_t     = 0.0
                self.pattern     = name
        if "intensity" in cmd:
            self.intensity = max(0.0, min(1.0, float(cmd["intensity"])))
        if "hz" in cmd:
            self.hz = max(0.01, min(10.0, float(cmd["hz"])))

    def stop(self):
        self.intensity   = 0.0
        self._phase      = 0.0
        self._edge_phase = 0
        self._edge_t     = 0.0


# ── Embedded driver web UI ────────────────────────────────────────────────────

DRIVER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>ReStim Drive</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg:#111; --bg2:#1a1a1a; --bg3:#222;
    --border:#2a2a2a; --fg:#fff; --fg2:#999;
    --accent:#5fa3ff; --ok:#4caf50; --err:#f44336; --warn:#ff9800;
  }
  body {
    background:var(--bg); color:var(--fg);
    font-family:Arial,sans-serif; font-size:14px;
    padding:12px; max-width:480px; margin:0 auto;
  }
  h1 { font-size:15px; color:var(--fg2); margin-bottom:12px; letter-spacing:.05em; }

  /* Status */
  #status-bar { display:flex; align-items:center; gap:8px; margin-bottom:12px; }
  #dot { width:10px; height:10px; border-radius:50%; background:var(--err); flex-shrink:0; }
  #status-text { color:var(--fg2); font-size:12px; flex:1; }

  /* Safety note */
  .safety {
    background:var(--bg2); border:1px solid var(--border); border-radius:5px;
    padding:8px 10px; margin-bottom:12px;
    color:var(--fg2); font-size:11px; line-height:1.5;
  }
  .safety strong { color:var(--warn); }

  /* STOP */
  #stop-btn {
    width:100%; padding:16px; background:var(--err); color:#fff;
    border:none; border-radius:6px; font-size:17px; font-weight:bold;
    cursor:pointer; margin-bottom:14px; letter-spacing:.08em;
  }
  #stop-btn:active { background:#c62828; }

  /* Section labels */
  .section-label {
    color:var(--fg2); font-size:11px; letter-spacing:.06em;
    text-transform:uppercase; margin-bottom:6px;
  }

  /* Pattern grid */
  #pattern-grid {
    display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-bottom:16px;
  }
  .pat-btn {
    padding:10px 4px; background:var(--bg3); color:var(--fg2);
    border:1px solid var(--border); border-radius:5px;
    font-size:12px; cursor:pointer; text-align:center; transition:all .1s;
  }
  .pat-btn:active { background:#333; }
  .pat-btn.active {
    background:var(--accent); border-color:var(--accent);
    color:#000; font-weight:bold;
  }

  /* Sliders */
  .slider-row { margin-bottom:14px; }
  .slider-header { display:flex; justify-content:space-between; margin-bottom:5px; }
  .slider-label { font-size:12px; }
  .slider-val { font-size:12px; color:var(--accent); font-weight:bold; min-width:50px; text-align:right; }
  input[type=range] {
    -webkit-appearance:none; width:100%; height:6px;
    border-radius:3px; background:var(--bg3); outline:none;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance:none; width:22px; height:22px;
    border-radius:50%; background:var(--accent); cursor:pointer;
  }
  #intensity-slider { height:10px; }
  #intensity-slider::-webkit-slider-thumb { width:30px; height:30px; }

  /* Beta presets */
  #beta-row { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-bottom:14px; }
  .beta-btn {
    padding:9px; background:var(--bg3); color:var(--fg2);
    border:1px solid var(--border); border-radius:5px;
    font-size:12px; cursor:pointer; text-align:center;
  }
  .beta-btn.active { background:#1e2d3e; border-color:var(--accent); color:var(--fg); }

  /* Alpha toggle */
  #alpha-row { margin-bottom:14px; }
  #alpha-toggle {
    width:100%; padding:9px; background:var(--bg3); color:var(--fg2);
    border:1px solid var(--border); border-radius:5px;
    font-size:13px; cursor:pointer; text-align:center;
  }
  #alpha-toggle.active { background:#1e2d3e; border-color:var(--accent); color:var(--fg); }

  /* Live */
  #live { color:var(--fg2); font-size:11px; font-family:monospace; min-height:18px; }
</style>
</head>
<body>
<h1>RESTIM DRIVE</h1>

<div id="status-bar">
  <div id="dot"></div>
  <span id="status-text">Connecting…</span>
</div>

<div class="safety">
  <strong>Safety:</strong> the rider always sets their own maximum power limit on their device.
  This interface only controls pattern and relative intensity within that limit.
</div>

<button id="stop-btn" onclick="sendStop()">⬛  STOP</button>

<div class="section-label">Pattern</div>
<div id="pattern-grid"></div>

<div class="slider-row">
  <div class="slider-header">
    <span class="slider-label">Intensity  <small style="color:var(--fg2)">(% of rider's max)</small></span>
    <span class="slider-val" id="int-val">0%</span>
  </div>
  <input type="range" id="intensity-slider" min="0" max="100" value="0"
         oninput="onIntensity(this.value)">
</div>

<div class="slider-row">
  <div class="slider-header">
    <span class="slider-label">Speed (Hz)</span>
    <span class="slider-val" id="hz-val">0.50 Hz</span>
  </div>
  <input type="range" id="hz-slider" min="1" max="100" value="10"
         oninput="onHz(this.value)">
</div>

<div class="section-label">Beta  (left / right balance)</div>
<div id="beta-row">
  <button class="beta-btn" data-beta="8099" onclick="setBeta(this)">◄ Left</button>
  <button class="beta-btn active" data-beta="5000" onclick="setBeta(this)">Centre</button>
  <button class="beta-btn" data-beta="1900" onclick="setBeta(this)">Right ►</button>
</div>

<div id="alpha-row">
  <button id="alpha-toggle" class="active" onclick="toggleAlpha()">
    α  Alpha oscillation: ON
  </button>
</div>

<div id="live"></div>

<script>
const PATTERNS = ["Hold","Sine","Ramp ↑","Ramp ↓","Pulse","Burst","Random","Edge"];
let state = { pattern:"Hold", intensity:0, hz:0.5, beta:5000, alpha:true };

// Build pattern buttons
const grid = document.getElementById("pattern-grid");
PATTERNS.forEach(p => {
  const b = document.createElement("button");
  b.className = "pat-btn" + (p === state.pattern ? " active" : "");
  b.textContent = p;
  b.onclick = () => setPattern(p);
  grid.appendChild(b);
});

function setPattern(p) {
  state.pattern = p;
  document.querySelectorAll(".pat-btn").forEach(b =>
    b.classList.toggle("active", b.textContent === p));
  sendCmd({ pattern: p });
}

function onIntensity(v) {
  state.intensity = v / 100;
  document.getElementById("int-val").textContent = v + "%";
  sendCmd({ intensity: state.intensity });
}

function onHz(v) {
  // map 1–100 → 0.05–8 Hz (log curve)
  const hz = Math.round(Math.pow(v / 100, 2) * 795 + 5) / 100;
  state.hz = hz;
  document.getElementById("hz-val").textContent = hz.toFixed(2) + " Hz";
  sendCmd({ hz: hz });
}

function setBeta(btn) {
  document.querySelectorAll(".beta-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  state.beta = parseInt(btn.dataset.beta);
  sendCmd({ beta: state.beta });
}

function toggleAlpha() {
  state.alpha = !state.alpha;
  const btn = document.getElementById("alpha-toggle");
  btn.classList.toggle("active", state.alpha);
  btn.textContent = "α  Alpha oscillation: " + (state.alpha ? "ON" : "OFF");
  sendCmd({ alpha: state.alpha });
}

function sendStop() {
  state.intensity = 0;
  document.getElementById("intensity-slider").value = 0;
  document.getElementById("int-val").textContent = "0%";
  sendCmd({ stop: true });
}

async function sendCmd(cmd) {
  try {
    const r = await fetch("/command", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(cmd)
    });
    if (!r.ok) throw new Error(r.status);
    setConnected(true);
  } catch { setConnected(false); }
}

function setConnected(ok) {
  document.getElementById("dot").style.background = ok ? "var(--ok)" : "var(--err)";
  document.getElementById("status-text").textContent =
    ok ? "Connected to rider" : "Connection lost — retrying…";
}

async function pollState() {
  try {
    const r = await fetch("/state");
    const d = await r.json();
    setConnected(true);
    document.getElementById("live").textContent =
      `Vol ${Math.round(d.vol*100)}%   β ${d.beta}   α ${Math.round(d.alpha*100)}%   pattern: ${d.pattern}`;
  } catch { setConnected(false); }
}

setInterval(pollState, 400);
pollState();
</script>
</body>
</html>
"""


# ── Bridge + pattern engine (asyncio thread) ──────────────────────────────────

class DriveEngine:
    def __init__(self, cfg: DriveConfig, shared: dict, log_q: queue.Queue):
        self._cfg          = cfg
        self._shared       = shared
        self._log_q        = log_q
        self._ws           = None
        self._session      = None
        self._pattern      = PatternEngine()
        self._current_beta = cfg.beta_off
        self._alpha_phase  = 0.0
        self._alpha_parked = True
        self._alpha_on     = True
        self._beta_override: Optional[int] = None   # None = auto
        self._stop_ev: Optional[asyncio.Event] = None
        self._loop:    Optional[asyncio.AbstractEventLoop] = None

    def _log(self, msg: str):
        self._log_q.put_nowait(msg)

    # ── ReStim connection ────────────────────────────────────────────────────

    async def _connect(self) -> bool:
        try:
            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(
                self._cfg.restim_url, heartbeat=30)
            self._log(f"Connected → {self._cfg.restim_url}")
            return True
        except Exception as e:
            self._log(f"Connect failed: {e}")
            return False

    async def _send(self, cmd: str):
        if self._ws is None or self._ws.closed:
            await self._connect()
            if self._ws is None:
                return
        try:
            await self._ws.send_str(cmd)
        except Exception as e:
            self._log(f"Send error: {e}")
            self._ws = None

    # ── HTTP server (driver browser UI) ─────────────────────────────────────

    async def _handle_index(self, _req):
        return web.Response(text=DRIVER_HTML, content_type="text/html")

    async def _handle_command(self, req):
        try:
            cmd = await req.json()
        except Exception:
            return web.Response(status=400)

        if cmd.get("stop"):
            self._pattern.stop()
        else:
            self._pattern.set_command(cmd)
            if "beta" in cmd:
                self._beta_override = int(cmd["beta"])
            if "alpha" in cmd:
                self._alpha_on = bool(cmd["alpha"])

        # Mirror to shared dict for the GUI poll loop
        self._shared["__cmd_pattern__"]   = self._pattern.pattern
        self._shared["__cmd_intensity__"] = self._pattern.intensity
        self._shared["__cmd_hz__"]        = self._pattern.hz
        return web.Response(text="ok")

    async def _handle_state(self, _req):
        d = {
            "vol":     self._shared.get("__live__l0", 0.0),
            "beta":    int(self._shared.get("__live__l1",
                           self._cfg.beta_off / 9999.0) * 9999),
            "alpha":   self._shared.get("__live__l2", 0.0),
            "pattern": self._pattern.pattern,
        }
        return web.Response(text=json.dumps(d), content_type="application/json")

    async def _start_http(self):
        app = web.Application()
        app.router.add_get("/",         self._handle_index)
        app.router.add_post("/command", self._handle_command)
        app.router.add_get("/state",    self._handle_state)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self._cfg.ctrl_port)
        await site.start()
        self._log(
            f"Driver UI → http://localhost:{self._cfg.ctrl_port}"
            f"  |  share your LAN IP for remote access"
        )

    # ── Output loops ─────────────────────────────────────────────────────────

    async def _pattern_loop(self):
        """Drives L0 volume and L1 beta from the pattern engine."""
        last = self._loop.time()
        while not self._stop_ev.is_set():
            cfg = self._cfg
            now = self._loop.time()
            dt  = now - last
            last = now

            intensity = self._pattern.tick(dt)
            self._shared["__live__l0"] = intensity

            # L0 volume
            tv    = _tv_floor(intensity, cfg.tcode_floor)
            parts = [f"{cfg.axis_volume}{tv}I{cfg.send_interval_ms}"]

            # L1 beta — driver can override or let intensity drive it
            if self._beta_override is not None:
                desired = self._beta_override if intensity > 0.0 else cfg.beta_off
            elif intensity > 0.0:
                desired = (cfg.beta_active
                           if intensity >= cfg.beta_thresh
                           else cfg.beta_light)
            else:
                desired = cfg.beta_off

            if desired != self._current_beta:
                t = 500 if desired == cfg.beta_off else 200
                parts.append(f"{cfg.axis_beta}{desired:04d}I{t}")
                self._current_beta = desired
            self._shared["__live__l1"] = self._current_beta / 9999.0

            if parts:
                await self._send(" ".join(parts))

            await asyncio.sleep(cfg.send_interval_ms / 1000.0)

    async def _alpha_loop(self):
        """Drives L2 alpha oscillation."""
        while not self._stop_ev.is_set():
            cfg = self._cfg
            dt  = cfg.send_interval_ms / 1000.0
            eff = self._pattern.intensity if self._alpha_on else 0.0

            if eff < 0.01:
                if not self._alpha_parked:
                    await self._send(f"{cfg.axis_alpha}{_tv(0.5)}I500")
                    self._alpha_parked = True
                self._alpha_phase = 0.0
                self._shared["__live__l2"] = 0.0
            else:
                self._alpha_parked = False
                hz  = cfg.alpha_min_hz + (cfg.alpha_max_hz  - cfg.alpha_min_hz)  * eff
                amp = cfg.alpha_min_amp + (cfg.alpha_max_amp - cfg.alpha_min_amp) * eff
                pos = 0.5 + amp * math.sin(2 * math.pi * self._alpha_phase)
                self._alpha_phase = (self._alpha_phase + hz * dt) % 1.0
                await self._send(f"{cfg.axis_alpha}{_tv(pos)}I{int(dt * 1000)}")
                self._shared["__live__l2"] = eff

            await asyncio.sleep(dt)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def _run_async(self):
        self._loop    = asyncio.get_event_loop()
        self._stop_ev = asyncio.Event()

        await self._start_http()

        if not await self._connect():
            self._log("Could not connect to ReStim — check URL and try Start again")

        # Park all axes on start
        cfg = self._cfg
        await self._send(
            f"{cfg.axis_beta}{cfg.beta_off:04d}I0 "
            f"{cfg.axis_volume}0000I0 "
            f"{cfg.axis_alpha}{_tv(0.5)}I0"
        )

        try:
            await asyncio.gather(self._pattern_loop(), self._alpha_loop())
        finally:
            if self._ws and not self._ws.closed:
                await self._ws.close()
            if self._session and not self._session.closed:
                await self._session.close()
            self._log("Engine stopped.")

    def start(self):
        threading.Thread(
            target=lambda: asyncio.run(self._run_async()), daemon=True
        ).start()

    def stop(self):
        if self._stop_ev and self._loop:
            self._loop.call_soon_threadsafe(self._stop_ev.set)


# ── Custom widgets ────────────────────────────────────────────────────────────

class IntensityBar(tk.Canvas):
    W, H = 90, 11

    def __init__(self, parent, **kw):
        super().__init__(parent, width=self.W, height=self.H,
                         bg=BG3, highlightthickness=1,
                         highlightbackground=BORDER, **kw)
        self._rect = self.create_rectangle(0, 0, 0, self.H, fill=SUCCESS, outline="")

    def set(self, v: float):
        w = int(max(0.0, min(1.0, v)) * self.W)
        self.coords(self._rect, 0, 0, w, self.H)
        if v < 0.5:
            r, g = int(v * 2 * 220), 187
        else:
            r, g = 220, int((1.0 - (v - 0.5) * 2) * 187)
        self.itemconfig(self._rect, fill=f"#{r:02x}{g:02x}10")


# ── Main GUI ──────────────────────────────────────────────────────────────────

class DriveGUI:
    def __init__(self):
        self.cfg       = DriveConfig.load()
        self._shared:  dict         = {}
        self._log_q:   queue.Queue  = queue.Queue()
        self._engine:  Optional[DriveEngine] = None
        self._running: bool         = False

        self.root = tk.Tk()
        self.root.title("ReStim Drive")
        self.root.minsize(520, 500)

        self._apply_theme()
        self._build_ui()
        self.root.after(150, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Dark theme ────────────────────────────────────────────────────────────

    def _apply_theme(self):
        self.root.configure(bg=BG)
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except Exception:
            pass

        st.configure("TFrame",            background=BG)
        st.configure("TLabelframe",       background=BG, foreground=FG2,
                     bordercolor=BORDER, relief="flat")
        st.configure("TLabelframe.Label", background=BG, foreground=FG2,
                     font=("Arial", 9))
        st.configure("TLabel",            background=BG, foreground=FG,
                     font=("Arial", 9))
        st.configure("TNotebook",         background=BG, bordercolor=BORDER,
                     tabmargins=[0, 0, 0, 0])
        st.configure("TNotebook.Tab",     background=BG3, foreground=FG2,
                     padding=[10, 4], font=("Arial", 9))
        st.map("TNotebook.Tab",
               background=[("selected", BG2), ("active", BG3)],
               foreground=[("selected", FG),  ("active", FG)])
        st.configure("TButton",           background=BG3, foreground=FG,
                     bordercolor=BORDER, focuscolor="none",
                     relief="flat", font=("Arial", 9), padding=[4, 2])
        st.map("TButton",
               background=[("active", "#333333"), ("pressed", "#2a2a2a")],
               foreground=[("disabled", FG2)])
        st.configure("Accent.TButton",    background=ACCENT, foreground="#000000",
                     bordercolor=ACCENT, focuscolor="none",
                     relief="flat", font=("Arial", 9, "bold"), padding=[6, 3])
        st.map("Accent.TButton",
               background=[("active", "#4d91ee"), ("pressed", "#3d81de")])
        st.configure("TEntry",
                     fieldbackground=BG3, foreground=FG, bordercolor=BORDER,
                     insertcolor=FG, selectbackground=ACCENT,
                     selectforeground="#000000")
        st.configure("TSpinbox",
                     fieldbackground=BG3, foreground=FG, bordercolor=BORDER,
                     insertcolor=FG, arrowcolor=FG2, background=BG3)
        st.configure("TCheckbutton",      background=BG, foreground=FG,
                     focuscolor="none", font=("Arial", 9))
        st.map("TCheckbutton",
               background=[("active", BG)],
               indicatorcolor=[("selected", ACCENT), ("!selected", BG3)])
        st.configure("TScale",            background=BG, troughcolor=BG3,
                     sliderlength=12, sliderrelief="flat", bordercolor=BORDER)
        st.map("TScale", background=[("active", ACCENT)])
        st.configure("TScrollbar",        background=BG3, troughcolor=BG,
                     bordercolor=BORDER, arrowcolor=FG2, relief="flat")
        st.map("TScrollbar", background=[("active", "#444444")])
        st.configure("TSeparator",        background=BORDER)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Connection bar ─────────────────────────────────────────────────
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=8, pady=(8, 0))

        self._dot_canvas = tk.Canvas(top, width=14, height=14,
                                     bg=BG, highlightthickness=0)
        self._dot_canvas.pack(side=tk.LEFT, padx=(0, 4))
        self._dot = self._dot_canvas.create_oval(2, 2, 12, 12, fill=ERROR, outline="")

        self._status_lbl = ttk.Label(top, text="Stopped", width=12)
        self._status_lbl.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(top, text="ReStim:").pack(side=tk.LEFT)
        self._url_var = tk.StringVar(value=self.cfg.restim_url)
        ttk.Entry(top, textvariable=self._url_var, width=22).pack(side=tk.LEFT, padx=4)

        self._start_btn = ttk.Button(top, text="Start", style="Accent.TButton",
                                     command=self._toggle, width=8)
        self._start_btn.pack(side=tk.RIGHT)

        # ── Driver URL ─────────────────────────────────────────────────────
        info = ttk.Frame(self.root)
        info.pack(fill=tk.X, padx=8, pady=(4, 0))
        ttk.Label(info, text="Driver URL:", font=("Arial", 8),
                  foreground=FG2).pack(side=tk.LEFT)
        self._ctrl_url_lbl = ttk.Label(
            info,
            text=f"http://localhost:{self.cfg.ctrl_port}  (start engine first)",
            font=("Arial", 8), foreground=ACCENT)
        self._ctrl_url_lbl.pack(side=tk.LEFT, padx=4)

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(
            fill=tk.X, padx=8, pady=8)

        # ── Live output bar ────────────────────────────────────────────────
        live = ttk.Frame(self.root)
        live.pack(fill=tk.X, padx=8)

        ttk.Label(live, text="Live →", font=("Arial", 7),
                  foreground=FG2).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(live, text="Vol", font=("Arial", 7),
                  foreground=FG2).pack(side=tk.LEFT)
        self._vol_bar = IntensityBar(live)
        self._vol_bar.pack(side=tk.LEFT, padx=(2, 2))
        self._vol_lbl = ttk.Label(live, text=" 0%", width=5, font=("Consolas", 7))
        self._vol_lbl.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(live, text="β", font=("Arial", 7),
                  foreground=FG2).pack(side=tk.LEFT)
        self._beta_lbl = ttk.Label(live, text="9999", width=5, font=("Consolas", 7))
        self._beta_lbl.pack(side=tk.LEFT, padx=(2, 10))

        ttk.Label(live, text="α", font=("Arial", 7),
                  foreground=FG2).pack(side=tk.LEFT)
        self._alpha_bar = IntensityBar(live)
        self._alpha_bar.pack(side=tk.LEFT, padx=(2, 2))
        self._alpha_lbl = ttk.Label(live, text=" 0%", width=5, font=("Consolas", 7))
        self._alpha_lbl.pack(side=tk.LEFT)

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(
            fill=tk.X, padx=8, pady=8)

        # ── Local override panel ───────────────────────────────────────────
        ctrl = ttk.LabelFrame(self.root, text="Local override", padding=8)
        ctrl.pack(fill=tk.X, padx=8)

        # Pattern buttons
        pat_row = ttk.Frame(ctrl)
        pat_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(pat_row, text="Pattern", font=("Arial", 8),
                  foreground=FG2).pack(side=tk.LEFT, padx=(0, 8))
        self._pat_btns: dict[str, ttk.Button] = {}
        for p in PATTERNS:
            b = ttk.Button(pat_row, text=p, width=7,
                           command=lambda pat=p: self._set_pattern(pat))
            b.pack(side=tk.LEFT, padx=2)
            self._pat_btns[p] = b
        self._pat_btns["Hold"].configure(style="Accent.TButton")

        # Intensity + Hz sliders
        sliders = ttk.Frame(ctrl)
        sliders.pack(fill=tk.X, pady=(4, 0))

        ttk.Label(sliders, text="Intensity", width=12).grid(
            row=0, column=0, sticky="w", pady=2)
        self._int_var = tk.DoubleVar(value=0.0)
        self._int_lbl = ttk.Label(sliders, text=" 0%", width=6)
        self._int_lbl.grid(row=0, column=2, sticky="w")
        ttk.Scale(sliders, from_=0, to=1, variable=self._int_var,
                  command=self._on_intensity, length=200).grid(
            row=0, column=1, padx=4, sticky="w")

        ttk.Label(sliders, text="Speed (Hz)", width=12).grid(
            row=1, column=0, sticky="w", pady=2)
        self._hz_var = tk.DoubleVar(value=0.5)
        self._hz_lbl = ttk.Label(sliders, text="0.50 Hz", width=8)
        self._hz_lbl.grid(row=1, column=2, sticky="w")
        ttk.Scale(sliders, from_=0.05, to=8.0, variable=self._hz_var,
                  command=self._on_hz, length=200).grid(
            row=1, column=1, padx=4, sticky="w")

        # ── Current pattern readout ────────────────────────────────────────
        self._state_lbl = ttk.Label(
            self.root,
            text="Pattern: Hold   Intensity: 0%   Hz: 0.50",
            font=("Consolas", 8), foreground=FG2)
        self._state_lbl.pack(anchor="w", padx=10, pady=(6, 0))

        # ── Log ────────────────────────────────────────────────────────────
        lf = ttk.LabelFrame(self.root, text="Log", padding=(4, 2))
        lf.pack(fill=tk.X, padx=8, pady=(8, 8))
        self._log_text = tk.Text(
            lf, height=4, state=tk.DISABLED,
            font=("Consolas", 8), bg=BG2, fg=FG2,
            insertbackground=FG, relief=tk.FLAT,
            wrap=tk.WORD, highlightthickness=0)
        self._log_text.pack(fill=tk.X)

    # ── Local control handlers ────────────────────────────────────────────────

    def _set_pattern(self, p: str):
        for name, btn in self._pat_btns.items():
            btn.configure(style="Accent.TButton" if name == p else "TButton")
        if self._engine:
            self._engine._pattern.set_command({"pattern": p})
            self._shared["__cmd_pattern__"] = p

    def _on_intensity(self, v):
        fv = float(v)
        self._int_lbl.config(text=f"{int(fv * 100):2d}%")
        if self._engine:
            self._engine._pattern.set_command({"intensity": fv})
            self._shared["__cmd_intensity__"] = fv

    def _on_hz(self, v):
        fv = float(v)
        self._hz_lbl.config(text=f"{fv:.2f} Hz")
        if self._engine:
            self._engine._pattern.set_command({"hz": fv})
            self._shared["__cmd_hz__"] = fv

    # ── Log ───────────────────────────────────────────────────────────────────

    def _append_log(self, msg: str):
        t = self._log_text
        t.configure(state=tk.NORMAL)
        t.insert(tk.END, msg + "\n")
        lines = int(t.index(tk.END).split(".")[0])
        if lines > 202:
            t.delete("1.0", f"{lines - 200}.0")
        t.see(tk.END)
        t.configure(state=tk.DISABLED)

    # ── Bridge control ────────────────────────────────────────────────────────

    def _toggle(self):
        if self._running:
            if self._engine:
                self._engine.stop()
            self._running = False
            self._start_btn.config(text="Start")
            self._dot_canvas.itemconfig(self._dot, fill=ERROR)
            self._status_lbl.config(text="Stopped")
        else:
            self.cfg.restim_url = self._url_var.get().strip()
            self._shared.clear()
            self._engine = DriveEngine(self.cfg, self._shared, self._log_q)
            self._engine.start()
            self._running = True
            self._start_btn.config(text="Stop")
            self._dot_canvas.itemconfig(self._dot, fill=WARN)
            self._status_lbl.config(text="Connecting…")

    # ── Poll loop ─────────────────────────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                msg = self._log_q.get_nowait()
                self._append_log(msg)
                low = msg.lower()
                if "connected →" in low:
                    self._dot_canvas.itemconfig(self._dot, fill=SUCCESS)
                    self._status_lbl.config(text="Connected")
                elif "failed" in low or "error" in low:
                    self._dot_canvas.itemconfig(self._dot, fill=ERROR)
                    self._status_lbl.config(text="Error")
        except queue.Empty:
            pass

        # Live output bars
        l0 = self._shared.get("__live__l0", 0.0)
        l1 = self._shared.get("__live__l1", self.cfg.beta_off / 9999.0)
        l2 = self._shared.get("__live__l2", 0.0)
        self._vol_bar.set(l0)
        self._vol_lbl.config(text=f"{int(l0 * 100):2d}%")
        self._beta_lbl.config(text=str(int(l1 * 9999)))
        self._alpha_bar.set(l2)
        self._alpha_lbl.config(text=f"{int(l2 * 100):2d}%")

        # State readout
        pat = self._shared.get("__cmd_pattern__", "Hold")
        it  = int(self._shared.get("__cmd_intensity__", 0.0) * 100)
        hz  = self._shared.get("__cmd_hz__", 0.5)
        self._state_lbl.config(
            text=f"Pattern: {pat:<8}  Intensity: {it:3d}%  Hz: {hz:.2f}")

        self.root.after(150, self._poll)

    # ── Close ─────────────────────────────────────────────────────────────────

    def _on_close(self):
        if self._running and self._engine:
            self._engine.stop()
        self.cfg.save()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    DriveGUI().run()
