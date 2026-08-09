#!/usr/bin/env python3
"""
redrive_bridge.py — headless ReDrive rider

Connects to a ReDrive room and forwards its live signal (T-code) straight to
your local ReStim, so you can ride without keeping a browser tab open.
Runs on Windows, macOS, and Linux.

    ReDrive room  ──(internet)─▶  this bridge  ──▶  your ReStim  ──▶  your box
                                                     (Audio / FOC-Stim / NeoStim)

Quick start
-----------
  1. In ReStim: turn on the T-code WebSocket server (default port 12346) and
     pick your device under  Setup ▸ Device Selection.
  2. Install the one dependency:   pip install websockets
  3. Run it with your room code:   python redrive_bridge.py YOURCODE

Options
-------
  --server URL   ReDrive server origin   (default: wss://redrive.estimstation.com)
  --restim URL   local ReStim T-code URL (default: ws://localhost:12346/tcode)
  --verbose      print every T-code frame (for debugging)

Safety
------
The driver only shapes the *pattern*. You still own your ReStim power dial /
maximum intensity — keep a hand on it.
"""
import argparse
import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    sys.exit("Missing dependency.  Install it with:  pip install websockets")


async def _run(room_url: str, restim_url: str, verbose: bool) -> None:
    # Bounded hand-off queue. If ReStim stalls we drop the oldest frames rather
    # than grow memory — the newest signal is the one worth keeping. (Mirrors
    # the server's own back-pressure policy.)
    queue: "asyncio.Queue[str]" = asyncio.Queue(maxsize=64)

    async def pump_room() -> None:
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(room_url, max_size=2 ** 20) as ws:
                    print(f"[room]   connected  ·  {room_url}")
                    backoff = 1.0
                    async for raw in ws:
                        msg = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else raw
                        if not msg:
                            continue
                        if msg[0] == "{":
                            # Control frame. Only ping needs a reply; the rest
                            # (rider_state, bottle_status, …) drives the browser UI.
                            try:
                                if json.loads(msg).get("type") == "ping":
                                    await ws.send('{"type":"pong"}')
                            except ValueError:
                                pass
                            continue
                        # Raw T-code → hand off to the ReStim sender.
                        if verbose:
                            print("   ", msg)
                        if queue.full():
                            queue.get_nowait()          # drop oldest
                        queue.put_nowait(msg)
            except Exception as e:
                print(f"[room]   disconnected ({e}); retrying in {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 15.0)

    async def pump_restim() -> None:
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(restim_url) as ws:
                    print(f"[restim] connected  ·  {restim_url}")
                    backoff = 1.0
                    while True:
                        await ws.send(await queue.get())
            except Exception as e:
                print(f"[restim] not reachable ({e}); retrying in {backoff:.0f}s")
                print("         → is ReStim running with its WebSocket server enabled?")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)

    await asyncio.gather(pump_room(), pump_restim())


def main() -> None:
    p = argparse.ArgumentParser(
        description="Headless ReDrive rider — forward a room's signal to your local ReStim.")
    p.add_argument("room", help="ReDrive room code (e.g. ABCD1234)")
    p.add_argument("--server", default="wss://redrive.estimstation.com",
                   help="ReDrive server origin (default: %(default)s)")
    p.add_argument("--restim", default="ws://localhost:12346/tcode",
                   help="local ReStim T-code socket (default: %(default)s)")
    p.add_argument("--verbose", action="store_true", help="print every T-code frame")
    a = p.parse_args()

    code = a.room.strip().upper()
    server = a.server.rstrip("/")
    room_url = f"{server}/room/{code}/rider-ws"

    bar = "─" * 62
    print(bar)
    print(f"  ReDrive bridge  ·  room {code}")
    print(f"    {server}  →  this bridge  →  {a.restim}")
    print("  Keep a hand on your ReStim power dial.   Ctrl-C to stop.")
    print(bar)
    try:
        asyncio.run(_run(room_url, a.restim, a.verbose))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
