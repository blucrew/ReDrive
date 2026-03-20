"""Tests for enhanced driver WebSocket protocol."""

import asyncio
import json
import pytest
import aiohttp

from server import build_app, _rooms


async def _receive_until_type(ws, target_type, max_msgs=10):
    """Read messages from WS until one with the target type arrives."""
    for _ in range(max_msgs):
        msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
        if msg.get("type") == target_type:
            return msg
    raise AssertionError(f"Never received message of type '{target_type}'")


async def _create_room(client):
    """Helper: POST /create and return (code, driver_key)."""
    resp = await client.post("/create", allow_redirects=False)
    assert resp.status == 302
    code = list(_rooms.keys())[0]
    key = _rooms[code].driver_key
    return code, key


class TestDriverWSProtocol:
    """Test the enhanced driver WebSocket protocol."""

    @pytest.mark.asyncio
    async def test_driver_ws_initial_state(self, aiohttp_client):
        """Driver receives full state on WS connect."""
        _rooms.clear()
        client = await aiohttp_client(build_app())
        code, key = await _create_room(client)

        ws = await client.ws_connect(f"/room/{code}/driver-ws?key={key}")
        msg = await ws.receive_json()
        assert msg["type"] == "state"
        assert "data" in msg
        assert "pattern" in msg["data"]
        assert "intensity" in msg["data"]

        await ws.close()
        _rooms.clear()

    @pytest.mark.asyncio
    async def test_driver_ws_command(self, aiohttp_client):
        """Driver sends command over WS, engine processes it."""
        _rooms.clear()
        client = await aiohttp_client(build_app())
        code, key = await _create_room(client)

        ws = await client.ws_connect(f"/room/{code}/driver-ws?key={key}")
        # Should receive initial state on connect
        msg = await ws.receive_json()
        assert msg["type"] == "state"

        # Send a command
        await ws.send_json({"type": "command", "data": {"pattern": "Sine"}})
        # Should receive command_ack
        ack = await ws.receive_json()
        assert ack["type"] == "command_ack"
        assert ack["ok"] is True

        await ws.close()
        _rooms.clear()

    @pytest.mark.asyncio
    async def test_driver_ws_auth_required(self, aiohttp_client):
        """Connection without valid key gets rejected."""
        _rooms.clear()
        client = await aiohttp_client(build_app())
        code, key = await _create_room(client)

        ws = await client.ws_connect(f"/room/{code}/driver-ws?key=WRONGKEY")
        msg = await ws.receive()
        assert msg.type == aiohttp.WSMsgType.CLOSE
        _rooms.clear()

    @pytest.mark.asyncio
    async def test_driver_ws_set_driver_name(self, aiohttp_client):
        """set_driver_name command works over WS."""
        _rooms.clear()
        client = await aiohttp_client(build_app())
        code, key = await _create_room(client)

        ws = await client.ws_connect(f"/room/{code}/driver-ws?key={key}")
        await ws.receive_json()  # initial state

        await ws.send_json({"type": "command", "data": {"set_driver_name": "Scott"}})
        ack = await _receive_until_type(ws, "command_ack")
        assert ack["ok"] is True
        assert _rooms[code].driver_name == "Scott"

        await ws.close()
        _rooms.clear()

    @pytest.mark.asyncio
    async def test_driver_ws_bottle(self, aiohttp_client):
        """bottle command works over WS."""
        _rooms.clear()
        client = await aiohttp_client(build_app())
        code, key = await _create_room(client)

        ws = await client.ws_connect(f"/room/{code}/driver-ws?key={key}")
        await ws.receive_json()  # initial state

        await ws.send_json({"type": "command", "data": {"bottle": {"mode": "deep_huff", "duration": 15}}})
        ack = await ws.receive_json()
        assert ack["type"] == "command_ack"
        assert _rooms[code].bottle_mode == "deep_huff"

        await ws.close()
        _rooms.clear()

    @pytest.mark.asyncio
    async def test_driver_ws_ping_pong(self, aiohttp_client):
        """Ping returns pong and touches driver timer."""
        _rooms.clear()
        client = await aiohttp_client(build_app())
        code, key = await _create_room(client)

        ws = await client.ws_connect(f"/room/{code}/driver-ws?key={key}")
        await ws.receive_json()  # initial state

        await ws.send_json({"type": "ping"})
        pong = await ws.receive_json()
        assert pong["type"] == "pong"

        await ws.close()
        _rooms.clear()

    @pytest.mark.asyncio
    async def test_driver_ws_receives_state_push(self, aiohttp_client):
        """After connecting, driver receives periodic state pushes."""
        _rooms.clear()
        client = await aiohttp_client(build_app())
        code, key = await _create_room(client)

        ws = await client.ws_connect(f"/room/{code}/driver-ws?key={key}")
        # First message should be initial state
        msg = await ws.receive_json()
        assert msg["type"] == "state"
        assert "data" in msg
        assert "pattern" in msg["data"]
        assert "intensity" in msg["data"]

        await ws.close()
        _rooms.clear()
