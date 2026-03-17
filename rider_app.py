#!/usr/bin/env python3
"""ReDrive Rider — connects to a relay room and forwards T-code to local ReStim."""

import asyncio
import argparse
import sys
import threading
import tkinter as tk
from tkinter import ttk
import aiohttp

APP_VERSION = "0.1.0"
DEFAULT_RELAY  = "wss://redrive.estimstation.com"
DEFAULT_RESTIM = "ws://localhost:12346"

class RiderApp:
    def __init__(self, root: tk.Tk, room_code: str = ""):
        self.root = root
        self.root.title("ReDrive Rider")
        self.root.resizable(False, False)
        self.root.configure(bg="#111")

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_ev: asyncio.Event | None = None
        self._connected = False

        self._build_ui(room_code)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self, room_code: str):
        PAD = dict(padx=12, pady=6)
        BG, BG2, FG, FG2, ACC = "#111", "#1a1a1a", "#fff", "#999", "#5fa3ff"
        ENTRY_STYLE = dict(bg="#222", fg=FG, insertbackground=FG,
                           relief="flat", font=("Helvetica", 15),
                           highlightthickness=1, highlightbackground="#333",
                           highlightcolor=ACC)

        # Title
        tk.Label(self.root, text="ReDrive Rider", bg=BG, fg=FG,
                 font=("Helvetica", 18, "bold")).pack(pady=(16, 4))
        tk.Label(self.root, text=f"v{APP_VERSION}", bg=BG, fg=FG2,
                 font=("Helvetica", 10)).pack(pady=(0, 12))

        # Room code
        tk.Label(self.root, text="Room Code", bg=BG, fg=FG2,
                 font=("Helvetica", 11)).pack(anchor="w", padx=16)
        self._room_var = tk.StringVar(value=room_code.upper())
        room_entry = tk.Entry(self.root, textvariable=self._room_var,
                              width=18, justify="center", **ENTRY_STYLE)
        room_entry.pack(padx=16, pady=(2, 10), ipady=8, fill="x")

        # Advanced (collapsible)
        adv_frame = tk.Frame(self.root, bg=BG)
        adv_frame.pack(fill="x", padx=16)
        self._adv_open = False
        adv_toggle = tk.Label(adv_frame, text="▶ Advanced", bg=BG, fg=FG2,
                              font=("Helvetica", 10), cursor="hand2")
        adv_toggle.pack(anchor="w")
        self._adv_body = tk.Frame(self.root, bg=BG2, bd=0)

        for label, default, attr in [
            ("Relay Server", DEFAULT_RELAY,  "_relay_var"),
            ("ReStim URL",   DEFAULT_RESTIM, "_restim_var"),
        ]:
            tk.Label(self._adv_body, text=label, bg=BG2, fg=FG2,
                     font=("Helvetica", 10)).pack(anchor="w", padx=8, pady=(6,0))
            var = tk.StringVar(value=default)
            setattr(self, attr, var)
            tk.Entry(self._adv_body, textvariable=var, width=32,
                     bg="#2a2a2a", fg=FG, insertbackground=FG,
                     relief="flat", font=("Helvetica", 11)).pack(
                         padx=8, pady=(0,4), fill="x")

        def toggle_adv(_=None):
            self._adv_open = not self._adv_open
            adv_toggle.config(text=("▼ Advanced" if self._adv_open else "▶ Advanced"))
            if self._adv_open:
                self._adv_body.pack(fill="x", padx=16, pady=(2,8))
            else:
                self._adv_body.pack_forget()
        adv_toggle.bind("<Button-1>", toggle_adv)

        # Status row
        status_row = tk.Frame(self.root, bg=BG)
        status_row.pack(fill="x", padx=16, pady=(4,0))
        self._dot = tk.Label(status_row, text="●", bg=BG, fg="#444",
                             font=("Helvetica", 14))
        self._dot.pack(side="left")
        self._status_lbl = tk.Label(status_row, text="Not connected", bg=BG, fg=FG2,
                                    font=("Helvetica", 11))
        self._status_lbl.pack(side="left", padx=(6,0))

        # Connect button
        self._btn = tk.Button(self.root, text="Connect",
                              bg=ACC, fg="#000", activebackground="#4090ee",
                              font=("Helvetica", 13, "bold"),
                              relief="flat", cursor="hand2",
                              command=self._toggle_connect)
        self._btn.pack(padx=16, pady=10, fill="x", ipady=8)

        # Log
        log_frame = tk.Frame(self.root, bg="#000", bd=1, relief="sunken")
        log_frame.pack(padx=16, pady=(0,16), fill="both", expand=True)
        self._log = tk.Text(log_frame, bg="#000", fg="#888", font=("Courier", 9),
                            state="disabled", height=10, width=46,
                            relief="flat", wrap="word")
        sb = tk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log.pack(side="left", fill="both", expand=True)

        self.root.minsize(340, 460)

    def _log_line(self, msg: str):
        def _do():
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n")
            self._log.see("end")
            self._log.configure(state="disabled")
        self.root.after(0, _do)

    def _set_status(self, text: str, color: str):
        def _do():
            self._dot.config(fg=color)
            self._status_lbl.config(text=text)
        self.root.after(0, _do)

    def _set_btn(self, text: str, bg: str):
        def _do():
            self._btn.config(text=text, bg=bg)
        self.root.after(0, _do)

    def _toggle_connect(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        room = self._room_var.get().strip().upper()
        if not room:
            self._log_line("⚠ Enter a room code first.")
            return
        relay  = self._relay_var.get().strip().rstrip("/")
        restim = self._restim_var.get().strip()
        self._set_btn("Disconnect", "#c0392b")
        self._set_status("Connecting…", "#f39c12")
        self._loop = asyncio.new_event_loop()
        self._stop_ev = asyncio.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(room, relay, restim),
            daemon=True)
        self._thread.start()

    def _disconnect(self):
        if self._stop_ev:
            self._loop.call_soon_threadsafe(self._stop_ev.set)
        self._connected = False
        self._set_btn("Connect", "#5fa3ff")
        self._set_status("Disconnected", "#444")

    def _run_loop(self, room: str, relay: str, restim: str):
        self._loop.run_until_complete(self._rider_loop(room, relay, restim))

    async def _rider_loop(self, room: str, relay: str, restim: str):
        relay_url  = f"{relay}/ws/rider/{room}"
        RECONNECT_DELAY = 5.0
        while not self._stop_ev.is_set():
            # Connect to relay
            self._log_line(f"Connecting to relay…")
            self._set_status("Connecting to relay…", "#f39c12")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(relay_url) as relay_ws:
                        self._log_line("Connected to relay.  Connecting to ReStim…")
                        self._set_status("Connecting to ReStim…", "#f39c12")
                        try:
                            async with session.ws_connect(restim) as restim_ws:
                                self._connected = True
                                self._log_line("Connected to ReStim.  Forwarding T-code.")
                                self._set_status("Live", "#2ecc71")
                                self.root.after(0, lambda: self._btn.config(
                                    text="Disconnect", bg="#c0392b"))
                                async for msg in relay_ws:
                                    if self._stop_ev.is_set():
                                        break
                                    if msg.type == aiohttp.WSMsgType.TEXT:
                                        try:
                                            await restim_ws.send_str(msg.data)
                                        except Exception:
                                            break
                                    elif msg.type in (aiohttp.WSMsgType.CLOSE,
                                                      aiohttp.WSMsgType.ERROR):
                                        break
                        except Exception as e:
                            self._log_line(f"ReStim error: {e}")
            except Exception as e:
                self._log_line(f"Relay error: {e}")
            if self._stop_ev.is_set():
                break
            self._connected = False
            self._set_status(f"Reconnecting in {int(RECONNECT_DELAY)}s…", "#e74c3c")
            try:
                await asyncio.wait_for(self._stop_ev.wait(), timeout=RECONNECT_DELAY)
            except asyncio.TimeoutError:
                pass
        self._connected = False
        self._set_status("Disconnected", "#444")
        self.root.after(0, lambda: self._btn.config(text="Connect", bg="#5fa3ff"))

    def _on_close(self):
        self._disconnect()
        self.root.after(200, self.root.destroy)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("room", nargs="?", default="",
                        help="Room code (optional, can be typed in the app)")
    args = parser.parse_args()
    root = tk.Tk()
    app = RiderApp(root, room_code=args.room)
    root.mainloop()


if __name__ == "__main__":
    main()
