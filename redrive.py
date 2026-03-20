"""redrive.py — ReDrive · ReStim pattern engine with remote "driver" control.

Rider:   python redrive.py
Driver:  open  http://<rider-ip>:<ctrl_port>  in any browser (desktop or phone)

The RIDER always controls maximum power on their own device.
The driver controls pattern selection, relative intensity (0–100% of rider's max),
beta position, and alpha oscillation.

Install: pip install aiohttp
"""

import asyncio
import json
import queue
import threading
from pathlib import Path
from typing import Optional

try:
    import tkinter as tk
    from tkinter import ttk
    _HAS_TK = True
except ImportError:
    _HAS_TK = False

from aiohttp import web
from template_env import get_jinja_env

from engine import (
    DriveConfig, DriveEngine, PatternEngine,
    PRESETS, PATTERNS, CONFIG_FILE,
    _tv, _tv_floor,
)

_jinja_env = get_jinja_env


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


# ── HTTP handlers (layered on top of engine) ─────────────────────────────────
# These methods are monkey-patched onto DriveEngine so that the existing
# local-mode code paths and tests that call _handle_state / _handle_rider_state
# / _handle_command / _handle_index / _handle_touch continue to work.
# They are thin wrappers that return aiohttp web.Response objects.

async def _handle_index(self, _req):
    env = _jinja_env()
    tmpl = env.get_template("driver.html")
    html = tmpl.render(api_prefix="", driver_key="", room_code="")
    return web.Response(text=html, content_type="text/html")

async def _handle_touch(self, _req):
    env = _jinja_env()
    tmpl = env.get_template("touch.html")
    html = tmpl.render(api_prefix="", room_code="")
    return web.Response(text=html, content_type="text/html")

async def _handle_assets_list(self, req):
    """Return JSON list of PNG/JPG files in touch_assets/{type}/ subfolder."""
    type_ = req.rel_url.query.get("type", "anatomy")
    if "/" in type_ or "\\" in type_ or ".." in type_:
        raise web.HTTPForbidden()
    folder = Path(__file__).parent / "touch_assets" / type_
    folder.mkdir(parents=True, exist_ok=True)
    files = sorted(
        f.name for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    )
    return web.Response(text=json.dumps(files), content_type="application/json")

async def _handle_assets_file(self, req):
    """Serve a file from touch_assets/{type}/{name}."""
    type_ = req.match_info["type"]
    name  = req.match_info["name"]
    if "/" in type_ or "\\" in type_ or ".." in type_ or "/" in name or ".." in name:
        raise web.HTTPForbidden()
    path = Path(__file__).parent / "touch_assets" / type_ / name
    if not path.is_file():
        raise web.HTTPNotFound()
    ct = {".png": "image/png", ".jpg": "image/jpeg",
          ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower(), "application/octet-stream")
    return web.Response(body=path.read_bytes(), content_type=ct)

async def _handle_command(self, req):
    try:
        cmd = await req.json()
    except Exception:
        return web.Response(status=400)
    await self._process_command(cmd)
    return web.Response(text="ok")

async def _handle_state(self, _req):
    d = self._build_state_dict()
    return web.Response(text=json.dumps(d), content_type="application/json")

async def _handle_rider_state(self, _req):
    d = self._build_rider_state_dict()
    return web.Response(text=json.dumps(d), content_type="application/json")

async def _handle_driver_ws(self, req):
    import aiohttp as _aiohttp
    ws = web.WebSocketResponse(max_msg_size=65536)
    await ws.prepare(req)
    self._driver_wss.add(ws)

    # Send initial state
    state = self._build_state_dict()
    await ws.send_str(json.dumps({"type": "state", "data": state}))

    # Broadcast driver_status to riders
    await self._broadcast_to_riders(json.dumps({
        "type": "driver_status",
        "connected": True,
        "name": self._driver_name or "Anonymous",
    }))

    try:
        async for msg in ws:
            if msg.type == _aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "command":
                        cmd = data.get("data", {})
                        await self._process_command(cmd)
                        await ws.send_str(json.dumps({"type": "command_ack", "ok": True}))
                    elif data.get("type") == "ping":
                        await ws.send_str(json.dumps({"type": "pong"}))
                except Exception as e:
                    await ws.send_str(json.dumps({
                        "type": "command_ack", "ok": False, "error": str(e),
                    }))
            elif msg.type in (_aiohttp.WSMsgType.ERROR, _aiohttp.WSMsgType.CLOSE):
                break
    finally:
        self._driver_wss.discard(ws)
        if not self._driver_wss:
            await self._broadcast_to_riders(json.dumps({
                "type": "driver_status",
                "connected": False,
                "name": "",
            }))
    return ws

async def _handle_rider_ws(self, req):
    import aiohttp as _aiohttp
    ws = web.WebSocketResponse(max_msg_size=65536)
    await ws.prepare(req)
    self._rider_wss.add(ws)

    # Send initial rider state
    rstate = self._build_rider_state_dict()
    rstate["type"] = "rider_state"
    await ws.send_str(json.dumps(rstate))

    # Send current driver status
    driver_connected = len(self._driver_wss) > 0
    await ws.send_str(json.dumps({
        "type": "driver_status",
        "connected": driver_connected,
        "name": self._driver_name or ("Anonymous" if driver_connected else ""),
    }))

    try:
        async for msg in ws:
            if msg.type == _aiohttp.WSMsgType.TEXT:
                pass  # rider messages (future: set_name, like, etc.)
            elif msg.type in (_aiohttp.WSMsgType.ERROR, _aiohttp.WSMsgType.CLOSE):
                break
    finally:
        self._rider_wss.discard(ws)
    return ws


async def _state_push_loop(self):
    """Push state to driver WS at 5Hz and rider state at ~2Hz."""
    import time
    rider_tick = 0
    while not self._stop_ev.is_set():
        await asyncio.sleep(0.2)
        # Driver state push
        if self._driver_wss:
            state = self._build_state_dict()
            msg = json.dumps({"type": "state", "data": state})
            dead = set()
            for ws in list(self._driver_wss):
                try:
                    await ws.send_str(msg)
                except Exception:
                    dead.add(ws)
            self._driver_wss -= dead

        # Rider state push (every ~600ms)
        rider_tick += 1
        if rider_tick >= 3 and self._rider_wss:
            rider_tick = 0
            now = time.monotonic()
            active = now < self._bottle_until
            rmsg = json.dumps({
                "type": "rider_state",
                "intensity": self._pattern.intensity,
                "bottle_active": active,
                "bottle_remaining": round(max(0, self._bottle_until - now), 1) if active else 0,
                "bottle_mode": self._bottle_mode,
                "driver_name": self._driver_name,
                "driver_connected": len(self._driver_wss) > 0,
            })
            dead = set()
            for ws in list(self._rider_wss):
                try:
                    await ws.send_str(rmsg)
                except Exception:
                    dead.add(ws)
            self._rider_wss -= dead


def _build_app(self):
    """Build and return the aiohttp Application with all routes."""
    app = web.Application()
    app.router.add_get("/",                              self._handle_index)
    app.router.add_get("/touch",                         self._handle_touch)
    app.router.add_post("/command",                      self._handle_command)
    app.router.add_get("/state",                         self._handle_state)
    app.router.add_get("/rider-state",                   self._handle_rider_state)
    app.router.add_get("/driver-ws",                     self._handle_driver_ws)
    app.router.add_get("/rider-ws",                      self._handle_rider_ws)
    app.router.add_static("/public",                     str(Path(__file__).parent / "public"))
    app.router.add_get("/touch_assets/list",             self._handle_assets_list)
    app.router.add_get("/touch_assets/{type}/{name}",    self._handle_assets_file)
    return app

async def _start_http(self):
    app = self._build_app()
    # Ensure asset directories exist at startup
    for sub in ("anatomy", "tools"):
        (Path(__file__).parent / "touch_assets" / sub).mkdir(parents=True, exist_ok=True)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", self._cfg.ctrl_port)
    await site.start()
    self._log(
        f"Driver UI → http://localhost:{self._cfg.ctrl_port}"
        f"  |  share your LAN IP for remote access"
    )

async def _run_async_with_http(self):
    """Override _run_async to include HTTP server + state push loop for local mode."""
    self._loop    = asyncio.get_event_loop()
    self._stop_ev = asyncio.Event()

    if self._send_hook is None:
        # Local mode: start HTTP server and connect to ReStim directly
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
        await asyncio.gather(
            self._pattern_loop(), self._alpha_loop(), self._state_push_loop()
        )
    finally:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        self._log("Engine stopped.")

def _start_with_http(self):
    threading.Thread(
        target=lambda: asyncio.run(self._run_async()), daemon=True
    ).start()


# Attach HTTP/WS handler methods to DriveEngine for local (standalone) mode
DriveEngine._handle_index       = _handle_index
DriveEngine._handle_touch       = _handle_touch
DriveEngine._handle_assets_list = _handle_assets_list
DriveEngine._handle_assets_file = _handle_assets_file
DriveEngine._handle_command     = _handle_command
DriveEngine._handle_state       = _handle_state
DriveEngine._handle_rider_state = _handle_rider_state
DriveEngine._handle_driver_ws   = _handle_driver_ws
DriveEngine._handle_rider_ws    = _handle_rider_ws
DriveEngine._state_push_loop    = _state_push_loop
DriveEngine._build_app          = _build_app
DriveEngine._start_http         = _start_http
DriveEngine._run_async          = _run_async_with_http
DriveEngine.start               = _start_with_http


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
        self._copy_url_btn = ttk.Button(
            info, text="Copy", width=7,
            command=lambda: (
                self.root.clipboard_clear(),
                self.root.clipboard_append(f"http://localhost:{self.cfg.ctrl_port}"),
                self._copy_url_btn.configure(text="Copied"),
                self.root.after(1500, lambda: self._copy_url_btn.configure(text="Copy")),
            ))
        self._copy_url_btn.pack(side=tk.LEFT, padx=2)

        self._driver_status_lbl = ttk.Label(
            info, text="", font=("Arial", 8), foreground=FG2)
        self._driver_status_lbl.pack(side=tk.RIGHT, padx=4)

        self._poppers_lbl = ttk.Label(
            self.root, text="", font=("Arial", 10, "bold"),
            foreground=WARN)
        self._poppers_lbl.pack(fill=tk.X, padx=8)

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
        ttk.Label(sliders, text="Set max power limits in\nReStim Preferences",
                  font=("Arial", 9), foreground="#fbbf24", justify="left").grid(
            row=0, column=3, rowspan=2, sticky="nw", padx=(8, 0))

        ttk.Label(sliders, text="Speed (Hz)", width=12).grid(
            row=1, column=0, sticky="w", pady=2)
        self._hz_var = tk.DoubleVar(value=0.5)
        self._hz_lbl = ttk.Label(sliders, text="0.50 Hz", width=8)
        self._hz_lbl.grid(row=1, column=2, sticky="w")
        ttk.Scale(sliders, from_=0.05, to=8.0, variable=self._hz_var,
                  command=self._on_hz, length=200).grid(
            row=1, column=1, padx=4, sticky="w")

        ttk.Label(sliders, text="Depth", width=12).grid(
            row=2, column=0, sticky="w", pady=2)
        self._depth_var = tk.DoubleVar(value=1.0)
        self._depth_lbl = ttk.Label(sliders, text="100%", width=8)
        self._depth_lbl.grid(row=2, column=2, sticky="w")
        ttk.Scale(sliders, from_=0.0, to=1.0, variable=self._depth_var,
                  command=self._on_depth, length=200).grid(
            row=2, column=1, padx=4, sticky="w")
        ttk.Label(sliders, text="← flat · · · full swing →",
                  font=("Arial", 7), foreground=FG2).grid(
            row=2, column=3, sticky="w", padx=4)

        # ── Current pattern readout ────────────────────────────────────────
        self._state_lbl = ttk.Label(
            self.root,
            text="Pattern: Hold   Intensity: 0%   Hz: 0.50   Depth: 100%",
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

    def _on_depth(self, v):
        fv = float(v)
        self._depth_lbl.config(text=f"{int(fv * 100)}%")
        if self._engine:
            self._engine._pattern.set_command({"depth": fv})
            self._shared["__cmd_depth__"] = fv

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
        pat   = self._shared.get("__cmd_pattern__", "Hold")
        it    = int(self._shared.get("__cmd_intensity__", 0.0) * 100)
        hz    = self._shared.get("__cmd_hz__", 0.5)
        depth = int(self._shared.get("__cmd_depth__", 1.0) * 100)
        self._state_lbl.config(
            text=f"Pattern: {pat:<8}  Intensity: {it:3d}%  Hz: {hz:.2f}  Depth: {depth}%")

        # Driver name display
        name = self._shared.get("__driver_name__", "")
        if name:
            self._driver_status_lbl.config(text=f"Driver: {name}")
        elif self._running:
            self._driver_status_lbl.config(text="Driver: Anonymous")
        else:
            self._driver_status_lbl.config(text="")

        # Poppers countdown display
        import time as _time
        bottle_until = self._shared.get("__bottle_until__", 0)
        now = _time.monotonic()
        if now < bottle_until:
            remaining = int(bottle_until - now) + 1
            mode = self._shared.get("__bottle_mode__", "normal")
            mode_label = mode.replace("_", " ").title()
            self._poppers_lbl.config(text=f"  POPPERS ({mode_label}) - {remaining}s")
        else:
            self._poppers_lbl.config(text="")

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
