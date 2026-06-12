"""E2E repro: does funscript playback produce T-code at the rider WS?

Starts the relay app in-process, opens driver + rider WSs, replays the exact
command stream driver.js's funscript player emits, and reports what T-code
the rider receives in each scenario.
"""
import asyncio
import json
import re
import sys

sys.path.insert(0, ".")
import server as srv
from aiohttp import web, ClientSession, WSMsgType


async def run_test():
    app = srv.build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8899)
    await site.start()

    loop = asyncio.get_event_loop()
    code = srv._new_code()
    room = srv.Room(code, loop)
    srv._rooms[code] = room
    key = room.driver_key
    base = "http://127.0.0.1:8899"

    async with ClientSession() as sess:
        rider_ws = await sess.ws_connect(f"{base}/room/{code}/rider-ws")
        driver_ws = await sess.ws_connect(f"{base}/room/{code}/driver-ws?key={key}")

        tcodes = []

        async def rider_reader():
            async for msg in rider_ws:
                if msg.type == WSMsgType.TEXT:
                    d = msg.data
                    if not d.startswith("{"):
                        tcodes.append(d)

        reader = asyncio.create_task(rider_reader())

        async def drain_driver():
            # discard acks/state pushes so the WS buffer never backs up
            while True:
                try:
                    await asyncio.wait_for(driver_ws.receive(), timeout=0.05)
                except asyncio.TimeoutError:
                    return

        async def send_cmd(cmd):
            await driver_ws.send_str(json.dumps({"type": "command", "data": cmd}))

        async def scenario(name, setup_cmds, tick_cmd_fn, seconds=1.5):
            """Replay a 20 Hz funscript tick stream; report rider-side tcode."""
            tcodes.clear()
            for c in setup_cmds:
                await send_cmd(c)
            await drain_driver()
            n_ticks = int(seconds * 20)
            for i in range(n_ticks):
                await send_cmd(tick_cmd_fn(i / n_ticks))
                await asyncio.sleep(0.05)
                if i % 5 == 0:
                    await drain_driver()
            await asyncio.sleep(0.3)
            await drain_driver()
            # Analyse
            total = len(tcodes)
            nonzero_v = [t for t in tcodes if re.search(r"V0(?!000)\d{3}", t)]
            has_l1 = [t for t in tcodes if "L1" in t]
            has_e = [t for t in tcodes if re.search(r"e[1-4]", t)]
            nonzero_e = [t for t in tcodes
                         if re.search(r"e[1-4](?!0000)\d{4}", t)]
            print(f"\n== {name} ==")
            print(f"  frames received       : {total}")
            print(f"  frames w/ V0 nonzero  : {len(nonzero_v)}")
            print(f"  frames w/ L1          : {len(has_l1)}")
            print(f"  frames w/ e1-e4       : {len(has_e)}")
            print(f"  frames w/ e1-e4 != 0  : {len(nonzero_e)}")
            for t in tcodes[:3]:
                print(f"  first: {t}")
            for t in tcodes[-3:]:
                print(f"  last : {t}")

        # Scenario 1: plain intensity funscript (most common case).
        # driver.js: cmd.intensity = interp/100, sent at 20 Hz.
        await scenario(
            "S1: intensity script only (ramps 0->100%)",
            [],
            lambda f: {"intensity": round(f, 3)},
        )

        # Scenario 2: intensity + beta scripts, default sweep beta mode.
        await scenario(
            "S2: intensity+beta scripts, beta_mode=sweep (default)",
            [],
            lambda f: {"intensity": 0.8, "beta": int(f * 9999)},
        )

        # Scenario 3: intensity + beta scripts after switching to hold mode.
        await scenario(
            "S3: intensity+beta scripts, beta_mode=hold",
            [{"beta_mode": "hold"}],
            lambda f: {"intensity": 0.8, "beta": int(f * 9999)},
        )

        # Scenario 4: 4-phase, e1-e4 scripts only, master intensity untouched (0).
        await scenario(
            "S4: 4-phase ON, e1-e4 scripts only, master intensity 0",
            [{"four_phase": True}, {"stop": True}],
            lambda f: {"e1": f, "e2": 1 - f, "e3": 0.5, "e4": 0.2},
        )

        # Scenario 5: 4-phase, e1-e4 scripts + volume script driving intensity.
        await scenario(
            "S5: 4-phase ON, e1-e4 + volume scripts",
            [{"four_phase": True}],
            lambda f: {"intensity": 0.7, "e1": f, "e2": 1 - f, "e3": 0.5, "e4": 0.2},
        )

        # Scenario 6: rider-state reports four_phase + live electrodes while an
        # e1-e4 funscript streams, even with the 4-phase toggle off.
        await send_cmd({"four_phase": False})
        for i in range(8):
            await send_cmd({"e1": 0.9, "e2": 0.1, "e3": 0.0, "e4": 0.0})
            await asyncio.sleep(0.05)
        async with sess.get(f"{base}/room/{code}/rider-state") as r:
            rs = await r.json()
        print("\n== S6: rider-state during e1-e4 script (4-phase toggle OFF) ==")
        print(f"  four_phase    : {rs.get('four_phase')}   (want True)")
        print(f"  fp_electrodes : {rs.get('fp_electrodes')}   (want [0.9, 0.1, 0, 0])")
        await drain_driver()

        # Scenario 7: alpha oscillation must resume after an alpha script stops.
        await send_cmd({"intensity": 0.6, "alpha": True})
        for i in range(10):                       # alpha script playing
            await send_cmd({"alpha_pos": 0.3})
            await asyncio.sleep(0.05)
        await send_cmd({"alpha_release": True})   # fsStop()
        await drain_driver()
        tcodes.clear()
        await asyncio.sleep(1.0)                  # collect post-stop frames
        await drain_driver()
        l0_vals = {m.group(1) for t in tcodes
                   for m in [re.match(r"^L0(\d{4})I", t)] if m}
        print("\n== S7: alpha released after script stop ==")
        print(f"  total frames in 1s       : {len(tcodes)}")
        for t in tcodes[:6]:
            print(f"  frame: {t}")
        print(f"  distinct L0 values in 1s : {len(l0_vals)}   (>3 = oscillating)")

        reader.cancel()
        await rider_ws.close()
        await driver_ws.close()

    room.stop()
    await runner.cleanup()


asyncio.run(run_test())
