"""Tests for SimulationClock."""

from datetime import UTC, datetime

from ems.core.clock import SimulationClock


def test_clock_initialization() -> None:
    """Verify clock initializes at specified start time."""
    start = "2026-03-01T00:00:00Z"
    clock = SimulationClock(start_time=start, speed=60)

    assert clock.now() == datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    assert clock.speed == 60
    assert not clock.is_paused


def test_clock_advance() -> None:
    """Verify advance correctly increments simulation time."""
    start = "2026-03-01T00:00:00Z"
    clock = SimulationClock(start_time=start, speed=60)

    clock.advance(300.0)
    assert clock.now() == datetime(2026, 3, 1, 0, 5, 0, tzinfo=UTC)


def test_clock_pause_resume() -> None:
    """Verify pause prevents advance until resumed."""
    clock = SimulationClock(start_time="2026-03-01T00:00:00Z", speed=60)
    clock.pause()
    assert clock.is_paused

    clock.advance(100.0)
    assert clock.now() == datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)

    clock.resume()
    assert not clock.is_paused
    clock.advance(60.0)
    assert clock.now() == datetime(2026, 3, 1, 0, 1, 0, tzinfo=UTC)
