"""Tests for DriveEngine (redrive.py lines 2440-2964).

Uses _handle_command_data(cmd) directly (async) and _handle_state(None)
to inspect engine state.
"""

import json
import pytest
from redrive import PRESETS


class TestDriveEngineCommands:
    @pytest.mark.asyncio
    async def test_pattern_command(self, drive_engine):
        await drive_engine._handle_command_data({"pattern": "Sine"})
        assert drive_engine._pattern.pattern == "Sine"

    @pytest.mark.asyncio
    async def test_intensity_command(self, drive_engine):
        await drive_engine._handle_command_data({"intensity": 0.75})
        assert drive_engine._pattern.intensity == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_hz_command(self, drive_engine):
        await drive_engine._handle_command_data({"hz": 2.0})
        assert drive_engine._pattern.hz == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_depth_command(self, drive_engine):
        await drive_engine._handle_command_data({"depth": 0.5})
        assert drive_engine._pattern.depth == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_stop_command(self, drive_engine):
        await drive_engine._handle_command_data({"intensity": 0.8})
        await drive_engine._handle_command_data({"stop": True})
        assert drive_engine._pattern.intensity == 0.0
        assert drive_engine._ramp_active is False
        assert drive_engine._gesture_active is False

    @pytest.mark.asyncio
    async def test_ramp_start(self, drive_engine):
        await drive_engine._handle_command_data({"intensity": 0.2})
        await drive_engine._handle_command_data({
            "ramp": {"target": 1.0, "duration": 60}
        })
        assert drive_engine._ramp_active is True
        assert drive_engine._ramp_target == pytest.approx(1.0)
        assert drive_engine._ramp_duration == pytest.approx(60.0)

    @pytest.mark.asyncio
    async def test_ramp_stop(self, drive_engine):
        await drive_engine._handle_command_data({
            "ramp": {"target": 1.0, "duration": 60}
        })
        assert drive_engine._ramp_active is True
        await drive_engine._handle_command_data({"ramp_stop": True})
        assert drive_engine._ramp_active is False

    @pytest.mark.asyncio
    async def test_beta_mode_command(self, drive_engine):
        await drive_engine._handle_command_data({"beta_mode": "sweep"})
        assert drive_engine._beta_mode == "sweep"

    @pytest.mark.asyncio
    async def test_beta_sweep_params(self, drive_engine):
        await drive_engine._handle_command_data({
            "beta_sweep": {
                "hz": 1.0,
                "centre": 5000,
                "width": 2000,
                "skew": 0.5,
            }
        })
        assert drive_engine._beta_sweep_hz == pytest.approx(1.0)
        assert drive_engine._beta_sweep_centre == 5000
        assert drive_engine._beta_sweep_width == 2000
        assert drive_engine._beta_sweep_skew == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_preset_load(self, drive_engine):
        await drive_engine._handle_command_data({"load_preset": "Milking"})
        p = PRESETS["Milking"]
        assert drive_engine._pattern.pattern == p["pattern"]
        assert drive_engine._pattern.intensity == pytest.approx(p["intensity"])
        assert drive_engine._beta_mode == p["beta_mode"]
        assert drive_engine._alpha_on == p.get("alpha", True)

    @pytest.mark.asyncio
    async def test_preset_load_unknown(self, drive_engine):
        # Should be a no-op - no crash
        await drive_engine._handle_command_data({"load_preset": "Nonexistent"})
        # Engine defaults are unchanged
        assert drive_engine._pattern.pattern == "Hold"


class TestDriveEngineState:
    @pytest.mark.asyncio
    async def test_state_endpoint_fields(self, drive_engine):
        resp = await drive_engine._handle_state(None)
        d = json.loads(resp.text)
        expected_keys = {
            "pattern", "intensity", "ramp_active", "ramp_progress",
            "ramp_target", "ramp_duration", "beta_mode", "sweep_hz",
            "sweep_centre", "sweep_width", "sweep_skew", "alpha_on",
            "vol", "beta", "alpha", "spiral_amp", "spiral_tighten",
            "gesture_active", "gesture_dur", "presets",
        }
        for key in expected_keys:
            assert key in d, f"Missing key '{key}' in state response"

    @pytest.mark.asyncio
    async def test_state_after_preset(self, drive_engine):
        await drive_engine._handle_command_data({"load_preset": "Milking"})
        resp = await drive_engine._handle_state(None)
        d = json.loads(resp.text)
        p = PRESETS["Milking"]
        assert d["pattern"] == p["pattern"]
        assert d["intensity"] == pytest.approx(p["intensity"])
        assert d["beta_mode"] == p["beta_mode"]
        assert d["alpha_on"] == p.get("alpha", True)
        assert d["ramp_target"] == pytest.approx(p["ramp_target"])
        assert d["ramp_duration"] == pytest.approx(p["ramp_duration"])
        bs = p["beta_sweep"]
        assert d["sweep_centre"] == bs["centre"]
        assert d["sweep_width"] == bs["width"]

    @pytest.mark.asyncio
    async def test_sweep_hz_envelope_after_preset(self, drive_engine):
        """After loading Milking (which has sweep_hz_envelope), verify the
        envelope was activated."""
        await drive_engine._handle_command_data({"load_preset": "Milking"})
        env = drive_engine._sweep_hz_env
        assert env is not None, "sweep_hz_envelope should be activated"
        assert env["base"] == pytest.approx(0.34)
        assert env["peak"] == pytest.approx(5.0)
