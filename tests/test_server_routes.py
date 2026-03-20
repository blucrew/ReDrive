"""Tests for server HTTP routes using aiohttp test client."""

import json
import pytest
from server import _rooms
from engine import PRESETS


async def _create_room(client):
    """Helper: POST /create and extract room code + driver key from redirect."""
    resp = await client.post("/create", allow_redirects=False)
    assert resp.status == 302
    location = resp.headers["Location"]
    # Location looks like /room/XXXXXXXXXX?key=...
    parts = location.split("?key=")
    code = parts[0].split("/room/")[1]
    key = parts[1]
    return code, key


class TestCreateRoom:
    @pytest.mark.asyncio
    async def test_create_room(self, aiohttp_client, aiohttp_app):
        client = await aiohttp_client(aiohttp_app)
        code, key = await _create_room(client)
        assert code in _rooms
        assert len(code) == 10
        assert len(key) > 0


class TestDriverPage:
    @pytest.mark.asyncio
    async def test_driver_page_requires_key(self, aiohttp_client, aiohttp_app):
        client = await aiohttp_client(aiohttp_app)
        code, key = await _create_room(client)
        resp = await client.get(f"/room/{code}")
        assert resp.status == 403

    @pytest.mark.asyncio
    async def test_driver_page_with_key(self, aiohttp_client, aiohttp_app):
        client = await aiohttp_client(aiohttp_app)
        code, key = await _create_room(client)
        resp = await client.get(f"/room/{code}?key={key}")
        assert resp.status == 200
        text = await resp.text()
        assert "<html" in text.lower()


class TestCommandAuth:
    @pytest.mark.asyncio
    async def test_command_requires_auth(self, aiohttp_client, aiohttp_app):
        client = await aiohttp_client(aiohttp_app)
        code, key = await _create_room(client)
        resp = await client.post(
            f"/room/{code}/command",
            json={"pattern": "Sine"},
        )
        assert resp.status == 403

    @pytest.mark.asyncio
    async def test_command_sets_pattern(self, aiohttp_client, aiohttp_app):
        client = await aiohttp_client(aiohttp_app)
        code, key = await _create_room(client)
        resp = await client.post(
            f"/room/{code}/command",
            json={"pattern": "Sine"},
            headers={"X-Driver-Key": key},
        )
        assert resp.status == 200


class TestStateAuth:
    @pytest.mark.asyncio
    async def test_state_requires_auth(self, aiohttp_client, aiohttp_app):
        client = await aiohttp_client(aiohttp_app)
        code, key = await _create_room(client)
        resp = await client.get(f"/room/{code}/state")
        assert resp.status == 403

    @pytest.mark.asyncio
    async def test_state_returns_json(self, aiohttp_client, aiohttp_app):
        client = await aiohttp_client(aiohttp_app)
        code, key = await _create_room(client)
        resp = await client.get(
            f"/room/{code}/state",
            headers={"X-Driver-Key": key},
        )
        assert resp.status == 200
        d = await resp.json()
        assert "pattern" in d
        assert "intensity" in d
        assert "ramp_active" in d


class TestRiderState:
    @pytest.mark.asyncio
    async def test_rider_state_no_auth(self, aiohttp_client, aiohttp_app):
        client = await aiohttp_client(aiohttp_app)
        code, key = await _create_room(client)
        resp = await client.get(f"/room/{code}/rider-state")
        assert resp.status == 200
        d = await resp.json()
        assert "intensity" in d
        assert "bottle_active" in d


class TestRoomNotFound:
    @pytest.mark.asyncio
    async def test_room_not_found(self, aiohttp_client, aiohttp_app):
        client = await aiohttp_client(aiohttp_app)
        resp = await client.get(
            "/room/BADCODE000/state",
            headers={"X-Driver-Key": "fake"},
        )
        assert resp.status == 404


class TestCommandRoundTrips:
    @pytest.mark.asyncio
    async def test_command_stop(self, aiohttp_client, aiohttp_app):
        client = await aiohttp_client(aiohttp_app)
        code, key = await _create_room(client)
        headers = {"X-Driver-Key": key}
        # Set intensity first
        await client.post(
            f"/room/{code}/command",
            json={"intensity": 0.8},
            headers=headers,
        )
        # Stop
        await client.post(
            f"/room/{code}/command",
            json={"stop": True},
            headers=headers,
        )
        # Check state
        resp = await client.get(f"/room/{code}/state", headers=headers)
        d = await resp.json()
        assert d["intensity"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_preset_load_roundtrip(self, aiohttp_client, aiohttp_app):
        client = await aiohttp_client(aiohttp_app)
        code, key = await _create_room(client)
        headers = {"X-Driver-Key": key}
        await client.post(
            f"/room/{code}/command",
            json={"load_preset": "Milking"},
            headers=headers,
        )
        resp = await client.get(f"/room/{code}/state", headers=headers)
        d = await resp.json()
        p = PRESETS["Milking"]
        assert d["pattern"] == p["pattern"]
        assert d["intensity"] == pytest.approx(p["intensity"])
        assert d["beta_mode"] == p["beta_mode"]
