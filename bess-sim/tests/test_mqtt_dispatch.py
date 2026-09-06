"""Test suite verifying MQTT messaging, setpoint processing, clipping, and fault injection."""

import pytest

from bess_sim.battery import BessOperationalState
from bess_sim.config import BessConfig
from bess_sim.main import BessSimulatorApp


def test_setpoint_increases_soc_and_clips_out_of_bounds() -> None:
    """Test setpoint increases SoC and setpoint exceeding max power is clipped."""
    config = BessConfig()
    app = BessSimulatorApp(config=config)

    initial_soc = app.battery.soc_pct
    assert initial_soc == 50.0

    # 1. Normal charge command: 200 kW for 60 seconds
    app.on_setpoint({"setpoint_kw": 200.0, "reason": "TEST_CHARGE"})
    app.battery.pcs.ramp_rate_kw_s = 1000.0  # allow fast ramp for testing
    app._execute_step(dt_seconds=60.0)

    # SoC should increase
    assert app.battery.soc_pct > initial_soc
    assert app.battery.pcs.actual_power_kw == pytest.approx(200.0, abs=1.0)

    # 2. Out of bounds setpoint: 9999 kW (max power is 500 kW)
    app.on_setpoint({"setpoint_kw": 9999.0, "reason": "OVER_LIMIT"})
    app._execute_step(dt_seconds=60.0)

    # Should be clipped to power_max_kw (500 kW)
    assert app.battery.pcs.actual_power_kw <= 500.0


def test_forced_overheat_triggers_fault_and_alarm() -> None:
    """Test forced overheat command triggers FAULT state and alarm."""
    config = BessConfig()
    app = BessSimulatorApp(config=config)

    # Send forced overheat command
    app.on_command({"cmd": "fault_injection", "type": "force_overheat"})
    app._execute_step(dt_seconds=1.0)

    assert app.battery.bms.state == BessOperationalState.FAULT
    assert "FAULT" in app.last_published_state
    assert any("OVERHEAT" in alarm for alarm in app.last_known_alarms)


def test_comms_dropout_suppresses_telemetry() -> None:
    """Test simulated communication dropout prevents telemetry publication."""
    config = BessConfig()
    app = BessSimulatorApp(config=config)

    # Mock published messages
    published_topics = []

    def mock_publish_telemetry(data: dict) -> None:
        if not app.mqtt.is_comms_dropped():
            published_topics.append("telemetry")

    app.mqtt.publish_telemetry = mock_publish_telemetry

    # Under normal condition: published
    app._execute_step(dt_seconds=1.0)
    assert len(published_topics) == 1

    # Activate dropout for 5 seconds
    app.on_command({"cmd": "fault_injection", "type": "comms_dropout", "duration_s": 5.0})
    app._execute_step(dt_seconds=1.0)
    # Count should not increase
    assert len(published_topics) == 1
