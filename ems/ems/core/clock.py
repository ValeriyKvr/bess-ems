"""SimulationClock: Master unified simulation clock (SPEC §4.2, §6.6, GEMINI.md)."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

SCENARIOS: dict[str, str] = {
    "default": "2026-03-01T00:00:00Z",
    "winter_week": "2025-01-13T00:00:00Z",
    "summer_month": "2025-07-01T00:00:00Z",
    "year_2025": "2025-01-01T00:00:00Z",
    "year_2026": "2026-03-01T00:00:00Z",
}


class SimulationClock:
    """Master simulation clock owned exclusively by EMS Core.

    CRITICAL RULE (GEMINI.md):
    Do not use datetime.now() for business logic — always use clock.now().
    """

    ALLOWED_SPEEDS = (0, 1, 10, 60, 600, 3600)

    def __init__(
        self,
        start_time: datetime | str | None = None,
        speed: int = 60,
    ) -> None:
        if isinstance(start_time, str):
            self._current_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        elif isinstance(start_time, datetime):
            self._current_time = start_time if start_time.tzinfo else start_time.replace(tzinfo=UTC)
        else:
            self._current_time = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)

        self._speed = speed if speed in self.ALLOWED_SPEEDS else 60
        self._is_paused = self._speed == 0
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

        # Listeners for clock events
        self._tick_callbacks: list[Callable[[datetime, float], Any]] = []
        self._hourly_callbacks: list[Callable[[datetime], Any]] = []
        self._daily_13h_callbacks: list[Callable[[datetime], Any]] = []

        self._last_hour = self._current_time.hour
        self._last_day = self._current_time.date()
        self._d13_triggered_for_date: set[str] = set()

    def now(self) -> datetime:
        """Get current simulation timestamp in UTC."""
        return self._current_time

    def now_iso(self) -> str:
        """Get current simulation timestamp formatted as ISO 8601 string."""
        return self._current_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    @property
    def speed(self) -> int:
        """Get current simulation speed factor."""
        return self._speed

    @property
    def is_paused(self) -> bool:
        """Check if clock is paused."""
        return self._is_paused

    def set_speed(self, speed: int) -> None:
        """Set simulation speed factor."""
        if speed not in self.ALLOWED_SPEEDS:
            raise ValueError(f"Speed {speed} not in allowed speeds {self.ALLOWED_SPEEDS}")
        self._speed = speed
        self._is_paused = speed == 0
        logger.info("Simulation clock speed set to %dx (paused=%s)", self._speed, self._is_paused)

    def pause(self) -> None:
        """Pause simulation time."""
        self._is_paused = True
        logger.info("Simulation clock paused at %s", self.now_iso())

    def resume(self, speed: int | None = None) -> None:
        """Resume simulation time."""
        self._is_paused = False
        if speed is not None:
            self.set_speed(speed)
        elif self._speed == 0:
            self._speed = 1
        logger.info("Simulation clock resumed at %s (speed=%dx)", self.now_iso(), self._speed)

    def jump_to(self, target: datetime | str) -> None:
        """Jump directly to a specific simulation time."""
        if isinstance(target, str):
            self._current_time = datetime.fromisoformat(target.replace("Z", "+00:00"))
        else:
            self._current_time = target if target.tzinfo else target.replace(tzinfo=UTC)
        self._last_hour = self._current_time.hour
        self._last_day = self._current_time.date()
        logger.info("Simulation clock jumped to %s", self.now_iso())

        # Notify tick callbacks of immediate jump
        for cb in self._tick_callbacks:
            try:
                res = cb(self._current_time, 0.0)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as e:
                logger.error("Error in clock tick callback on jump: %s", e)

    def reset(self, scenario: str = "default", custom_time: datetime | str | None = None) -> None:
        """Reset clock to scenario preset or custom timestamp."""
        if custom_time:
            self.jump_to(custom_time)
        elif scenario in SCENARIOS:
            self.jump_to(SCENARIOS[scenario])
        else:
            self.jump_to(SCENARIOS["default"])
        self._d13_triggered_for_date.clear()
        logger.info("Simulation clock reset to scenario '%s': %s", scenario, self.now_iso())

    def advance(self, delta_seconds: float, force: bool = False) -> datetime:
        """Advance the clock by delta_seconds in simulation time."""
        if delta_seconds <= 0 or (self._is_paused and not force):
            return self._current_time

        prev_time = self._current_time
        self._current_time += timedelta(seconds=delta_seconds)

        # Detect hour transition
        if self._current_time.hour != prev_time.hour:
            new_hour_start = self._current_time.replace(minute=0, second=0, microsecond=0)
            for cb in self._hourly_callbacks:
                try:
                    res = cb(new_hour_start)
                    if asyncio.iscoroutine(res):
                        asyncio.create_task(res)
                except Exception as e:
                    logger.error("Error in clock hourly callback: %s", e)

        # Detect 13:00 gate closure event for D+1 DAM prices (§3.2, §6.2)
        date_str = str(self._current_time.date())
        if self._current_time.hour >= 13 and date_str not in self._d13_triggered_for_date:
            self._d13_triggered_for_date.add(date_str)
            for cb in self._daily_13h_callbacks:
                try:
                    res = cb(self._current_time)
                    if asyncio.iscoroutine(res):
                        asyncio.create_task(res)
                except Exception as e:
                    logger.error("Error in clock 13h callback: %s", e)

        # Notify tick callbacks
        for cb in self._tick_callbacks:
            try:
                res = cb(self._current_time, delta_seconds)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as e:
                logger.error("Error in clock tick callback: %s", e)

        return self._current_time

    def step(self, step_seconds: float = 60.0) -> datetime:
        """Manually advance clock by step_seconds regardless of pause state."""
        return self.advance(step_seconds, force=True)

    def register_tick_callback(self, cb: Callable[[datetime, float], Any]) -> None:
        """Register callback for each clock tick."""
        self._tick_callbacks.append(cb)

    def register_hourly_callback(self, cb: Callable[[datetime], Any]) -> None:
        """Register callback invoked on each simulated hour transition."""
        self._hourly_callbacks.append(cb)

    def register_13h_callback(self, cb: Callable[[datetime], Any]) -> None:
        """Register callback invoked when simulation time reaches 13:00."""
        self._daily_13h_callbacks.append(cb)

    def to_dict(self) -> dict[str, Any]:
        """Serialize clock state for API and MQTT."""
        return {
            "ts_sim": self.now_iso(),
            "speed": self._speed,
            "is_paused": self._is_paused,
        }

    async def start_loop(
        self, mqtt_publish_fn: Callable[[dict[str, Any]], None] | None = None
    ) -> None:
        """Start async background worker running the simulation clock."""
        self._stop_event.clear()
        wall_interval_sec = 0.5  # wall clock stepping rate

        logger.info("SimulationClock background loop started.")
        while not self._stop_event.is_set():
            await asyncio.sleep(wall_interval_sec)

            if not self._is_paused and self._speed > 0:
                sim_delta_sec = wall_interval_sec * self._speed
                self.advance(sim_delta_sec)

                if mqtt_publish_fn:
                    try:
                        mqtt_publish_fn(self.to_dict())
                    except Exception as e:
                        logger.error("Failed to publish sim/clock: %s", e)

    def stop_loop(self) -> None:
        """Stop background worker."""
        self._stop_event.set()
        logger.info("SimulationClock background loop stopped.")
