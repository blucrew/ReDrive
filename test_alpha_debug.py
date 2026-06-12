"""Isolate the alpha loop: drive the engine directly with a capture hook."""
import asyncio
import queue
import sys

sys.path.insert(0, ".")
from engine import DriveEngine, DriveConfig

frames = []
logs = queue.Queue()


async def main():
    cfg = DriveConfig()
    eng = DriveEngine(cfg, {}, logs, send_hook=lambda c: frames.append(c))
    eng._loop = asyncio.get_event_loop()
    eng._stop_ev = asyncio.Event()

    loops = asyncio.gather(eng._pattern_loop(), eng._alpha_loop())

    async def phase(name, secs):
        frames.clear()
        await asyncio.sleep(secs)
        l0 = [f for f in frames if f.startswith(cfg.axis_alpha)]
        print(f"{name}: total={len(frames)} alpha_frames={len(l0)} "
              f"sample={l0[:2] or frames[:2]}")

    await eng._process_command({"intensity": 0.6, "alpha": True})
    await phase("1. oscillating (no override)", 1.0)

    await eng._process_command({"alpha_pos": 0.3})
    await phase("2. override 0.3", 1.0)

    await eng._process_command({"alpha_release": True})
    await phase("3. after alpha_release", 1.0)

    eng._stop_ev.set()
    try:
        await asyncio.wait_for(loops, 2)
    except Exception:
        pass
    while not logs.empty():
        print("LOG:", logs.get_nowait())


asyncio.run(main())
