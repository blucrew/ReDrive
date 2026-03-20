"""Tests for --local mode of the unified server."""

import asyncio
import json
import pytest
from server import build_app, _rooms, Room


class TestLocalMode:
    @pytest.fixture
    async def local_client(self, aiohttp_client):
        """Create a test client with a local-mode room."""
        _rooms.clear()
        loop = asyncio.get_event_loop()
        code = "TESTLOCAL1"
        room = Room(code, loop, local_restim=True)
        _rooms[code] = room
        app = build_app(local_room=room)
        client = await aiohttp_client(app)
        yield client, code, room
        room.stop()
        _rooms.clear()

    @pytest.fixture
    async def relay_client(self, aiohttp_client):
        """Create a test client in relay mode (no local_room)."""
        _rooms.clear()
        app = build_app()
        client = await aiohttp_client(app)
        yield client
        _rooms.clear()

    async def test_local_index_redirects_to_driver(self, local_client):
        client, code, room = local_client
        resp = await client.get("/", allow_redirects=False)
        assert resp.status == 302
        location = resp.headers["Location"]
        assert f"/room/{code}" in location
        assert f"key={room.driver_key}" in location

    async def test_local_touch_redirects_to_rider(self, local_client):
        client, code, room = local_client
        resp = await client.get("/touch", allow_redirects=False)
        assert resp.status == 302
        assert f"/room/{code}/rider" in resp.headers["Location"]

    async def test_local_driver_page_loads(self, local_client):
        client, code, room = local_client
        resp = await client.get(f"/room/{code}?key={room.driver_key}")
        assert resp.status == 200
        text = await resp.text()
        assert "<html" in text.lower()

    async def test_local_rider_page_loads(self, local_client):
        client, code, room = local_client
        resp = await client.get(f"/room/{code}/rider")
        assert resp.status == 200
        text = await resp.text()
        assert "<html" in text.lower()

    async def test_local_room_has_engine(self, local_client):
        """Local mode room should have a running engine."""
        client, code, room = local_client
        assert room.engine is not None

    async def test_local_room_uses_loaded_config(self, local_client):
        """Local mode room should load DriveConfig from file."""
        client, code, room = local_client
        assert room.engine._cfg.restim_url  # should have a URL

    async def test_local_room_no_send_hook(self, local_client):
        """Local mode engine should have send_hook=None (direct ReStim)."""
        client, code, room = local_client
        assert room.engine._send_hook is None

    async def test_local_room_flagged(self, local_client):
        """Room should have local_restim=True."""
        client, code, room = local_client
        assert room.local_restim is True

    async def test_relay_index_serves_landing(self, relay_client):
        """In relay mode, / should serve the landing page (not redirect)."""
        client = relay_client
        resp = await client.get("/", allow_redirects=False)
        assert resp.status == 200

    async def test_relay_no_touch_route(self, relay_client):
        """In relay mode, /touch should 404 (it's not a valid route)."""
        client = relay_client
        resp = await client.get("/touch", allow_redirects=False)
        # /touch is not registered in relay mode
        assert resp.status == 404

    async def test_local_room_state_endpoint(self, local_client):
        """State endpoint should work for the local room."""
        client, code, room = local_client
        resp = await client.get(
            f"/room/{code}/state",
            headers={"X-Driver-Key": room.driver_key},
        )
        assert resp.status == 200
        d = await resp.json()
        assert "pattern" in d
        assert "intensity" in d

    async def test_local_rider_state_endpoint(self, local_client):
        """Rider state endpoint should work without auth."""
        client, code, room = local_client
        resp = await client.get(f"/room/{code}/rider-state")
        assert resp.status == 200
        d = await resp.json()
        assert "intensity" in d
        assert "bottle_active" in d
