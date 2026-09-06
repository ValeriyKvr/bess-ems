"""Realtime Dispatcher for BESS control (SPEC §6.5).

Each simulation tick:
1. Reads active schedule → determines planned setpoint.
2. Applies reactive rules (a, b, c) which override the schedule.
3. Publishes setpoint to MQTT and logs the decision with reason.

Reactive rules (higher priority than schedule):
  (a) SoC ≤ soc_min → forbid discharge (setpoint ≥ 0).
  (b) Peak-shaving: if load − p_dis > peak_limit_kw → raise discharge.
  (c) BESS in FAULT or no telemetry > 3 sim-min → SAFE_MODE (setpoint = 0, raise alarm).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ems.optimization.strategies import Schedule

logger = logging.getLogger(__name__)


# Dispatcher state enum
DISPATCHING = "DISPATCHING"
SAFE_MODE = "SAFE_MODE"
NO_SCHEDULE = "NO_SCHEDULE"


@dataclass
class DispatchDecision:
    """Single dispatcher decision for logging and explainability."""

    ts: datetime
    setpoint_kw: float
    reason: str
    schedule_id: str | None = None
    override: bool = False
    state: str = DISPATCHING


@dataclass
class DispatcherConfig:
    """Dispatcher tuning parameters."""

    soc_min_pct: float = 10.0
    soc_max_pct: float = 90.0
    soc_tolerance_pct: float = 3.0
    peak_limit_kw: float = 800.0
    telemetry_timeout_sim_minutes: float = 3.0
    safe_mode_setpoint_kw: float = 0.0


class Dispatcher:
    """Realtime BESS dispatch engine with reactive overrides (SPEC §6.5).

    Owns the active schedule and produces setpoints each simulation tick.
    """

    def __init__(self, config: DispatcherConfig | None = None) -> None:
        self.config = config or DispatcherConfig()
        self._active_schedule: Schedule | None = None
        self._state: str = NO_SCHEDULE
        self._last_telemetry_time: datetime | None = None
        self._decision_log: list[DispatchDecision] = []
        self._event_log: list[dict[str, Any]] = []

        # Live BESS telemetry cache (updated externally on each MQTT message)
        self._bess_soc_pct: float = 50.0
        self._bess_state: str = "STANDBY"
        self._bess_power_kw: float = 0.0
        self._bess_temp_c: float = 25.0
        self._site_load_kw: float = 0.0

        # Closed-loop rolling re-optimization callback (SPEC §6.5)
        self._reopt_callbacks: list[Any] = []
        self._last_reopt_time: datetime | None = None

    @property
    def state(self) -> str:
        """Current dispatcher state."""
        return self._state

    @property
    def active_schedule(self) -> Schedule | None:
        """Currently active dispatch schedule."""
        return self._active_schedule

    @property
    def decision_log(self) -> list[DispatchDecision]:
        """History of dispatch decisions."""
        return self._decision_log

    @property
    def event_log(self) -> list[dict[str, Any]]:
        """History of dispatcher events (alarms, mode changes)."""
        return self._event_log

    def register_reopt_callback(self, cb: Any) -> None:
        """Register callback invoked when closed-loop rolling re-optimization is needed."""
        self._reopt_callbacks.append(cb)

    def set_schedule(self, schedule: Schedule) -> None:
        """Activate a new dispatch schedule."""
        self._active_schedule = schedule
        if self._state != SAFE_MODE:
            self._state = DISPATCHING
        logger.info(
            "Dispatcher: new schedule activated (%s, %d items, horizon %s → %s)",
            schedule.strategy,
            len(schedule.items),
            schedule.horizon_start,
            schedule.horizon_end,
        )

    def update_telemetry(
        self,
        sim_time: datetime,
        soc_pct: float,
        state: str,
        power_kw: float,
        temp_c: float = 25.0,
    ) -> None:
        """Update cached BESS telemetry from MQTT. Called on every telemetry message."""
        self._bess_soc_pct = soc_pct
        self._bess_state = state
        self._bess_power_kw = power_kw
        self._bess_temp_c = temp_c
        self._last_telemetry_time = sim_time

    def update_site_load(self, load_kw: float) -> None:
        """Update current site load for peak-shaving calculations."""
        self._site_load_kw = load_kw

    def tick(self, sim_time: datetime) -> DispatchDecision:
        """Process a single simulation tick and produce a dispatch decision.

        Returns the decision (setpoint + reason) to be published via MQTT and logged.
        """
        # ─── Rule (c): FAULT or telemetry timeout → SAFE_MODE ───
        safe_mode_reason = self._check_safe_mode(sim_time)
        if safe_mode_reason:
            decision = DispatchDecision(
                ts=sim_time,
                setpoint_kw=self.config.safe_mode_setpoint_kw,
                reason=safe_mode_reason,
                schedule_id=self._active_schedule.id if self._active_schedule else None,
                override=True,
                state=SAFE_MODE,
            )
            if self._state != SAFE_MODE:
                self._enter_safe_mode(sim_time, safe_mode_reason)
            self._state = SAFE_MODE
            self._log_decision(decision)
            return decision

        # Exit SAFE_MODE if conditions cleared
        if self._state == SAFE_MODE:
            self._exit_safe_mode(sim_time)

        # ─── Base setpoint from schedule ───
        setpoint_kw = 0.0
        reason = "no_schedule"
        schedule_id: str | None = None

        if self._active_schedule:
            scheduled = self._active_schedule.get_setpoint_for(sim_time)
            if scheduled is not None:
                setpoint_kw = scheduled
                reason = "schedule"
                schedule_id = self._active_schedule.id
                self._state = DISPATCHING
            else:
                reason = "schedule_gap"
                self._state = DISPATCHING
        else:
            self._state = NO_SCHEDULE

        override = False

        # ─── Rule (a): SoC ≤ soc_min → forbid discharge ───
        if self._bess_soc_pct <= self.config.soc_min_pct and setpoint_kw < 0:
            setpoint_kw = 0.0
            reason = f"rule_a: SoC ({self._bess_soc_pct:.1f}%) ≤ soc_min ({self.config.soc_min_pct:.1f}%) — discharge forbidden"
            override = True

        # ─── Rule (a-bis): SoC ≥ soc_max → forbid charge ───
        if self._bess_soc_pct >= self.config.soc_max_pct and setpoint_kw > 0:
            setpoint_kw = 0.0
            reason = f"rule_a_max: SoC ({self._bess_soc_pct:.1f}%) ≥ soc_max ({self.config.soc_max_pct:.1f}%) — charge forbidden"
            override = True

        # ─── Rule (b): Peak-shaving override ───
        if self._site_load_kw > self.config.peak_limit_kw:
            excess_kw = self._site_load_kw - self.config.peak_limit_kw
            # We want discharge (negative setpoint) to cover the excess
            desired_discharge = -excess_kw
            if setpoint_kw > desired_discharge:
                # Only override if schedule isn't already discharging enough
                setpoint_kw = desired_discharge
                reason = f"rule_b: peak-shaving (load={self._site_load_kw:.0f}kW > limit={self.config.peak_limit_kw:.0f}kW, discharge {excess_kw:.0f}kW)"
                override = True

        decision = DispatchDecision(
            ts=sim_time,
            setpoint_kw=round(setpoint_kw, 2),
            reason=reason,
            schedule_id=schedule_id,
            override=override,
            state=self._state,
        )
        self._log_decision(decision)
        return decision

    def _check_safe_mode(self, sim_time: datetime) -> str | None:
        """Check if SAFE_MODE should be activated — returns reason string or None."""
        # BESS in FAULT state
        if self._bess_state == "FAULT":
            return "rule_c: BESS in FAULT state"

        # No telemetry received for > telemetry_timeout_sim_minutes
        if self._last_telemetry_time is not None:
            elapsed = sim_time - self._last_telemetry_time
            timeout = timedelta(minutes=self.config.telemetry_timeout_sim_minutes)
            if elapsed > timeout:
                return (
                    f"rule_c: no telemetry for {elapsed.total_seconds() / 60:.1f} sim-min "
                    f"(timeout={self.config.telemetry_timeout_sim_minutes:.0f} min)"
                )

        return None

    def _enter_safe_mode(self, sim_time: datetime, reason: str) -> None:
        """Transition into SAFE_MODE and emit alarm event."""
        event = {
            "ts": sim_time.isoformat(),
            "type": "event",
            "event": "SAFE_MODE_ENTER",
            "reason": reason,
            "severity": "ALARM",
        }
        self._event_log.append(event)
        logger.warning("Dispatcher: entering SAFE_MODE — %s", reason)

    def _exit_safe_mode(self, sim_time: datetime) -> None:
        """Transition out of SAFE_MODE."""
        event = {
            "ts": sim_time.isoformat(),
            "type": "event",
            "event": "SAFE_MODE_EXIT",
            "reason": "BESS telemetry restored, state normal",
            "severity": "INFO",
        }
        self._event_log.append(event)
        self._state = DISPATCHING
        logger.info("Dispatcher: exiting SAFE_MODE, returning to normal dispatch")

    def _log_decision(self, decision: DispatchDecision) -> None:
        """Append decision to in-memory log (capped to prevent unbounded growth)."""
        self._decision_log.append(decision)
        # Keep last 10000 decisions in memory
        if len(self._decision_log) > 10000:
            self._decision_log = self._decision_log[-5000:]

    def check_reoptimization_needed(
        self,
        sim_time: datetime,
        current_soc_pct: float,
        scheduled_soc_pct: float,
    ) -> bool:
        """Check if deviation between actual and scheduled SoC exceeds tolerance (SPEC §6.5)."""
        dev = abs(current_soc_pct - scheduled_soc_pct)
        if dev > self.config.soc_tolerance_pct:
            # Avoid re-triggering repeatedly within 30 sim-minutes
            if self._last_reopt_time is None or (sim_time - self._last_reopt_time) > timedelta(
                minutes=30
            ):
                self._last_reopt_time = sim_time
                event = {
                    "ts": sim_time.isoformat(),
                    "type": "event",
                    "event": "REOPTIMIZATION_TRIGGERED",
                    "reason": f"SoC deviation {dev:.1f}% > tolerance {self.config.soc_tolerance_pct:.1f}%",
                    "severity": "WARNING",
                }
                self._event_log.append(event)
                logger.warning(
                    "Dispatcher: triggering rolling re-optimization (deviation=%.1f%%)", dev
                )
                for cb in self._reopt_callbacks:
                    try:
                        res = cb(sim_time, current_soc_pct)
                        if asyncio.iscoroutine(res):
                            asyncio.create_task(res)
                    except Exception as e:
                        logger.error("Error in re-opt callback: %s", e)
                return True
        return False

    def get_ws_ems_state(self) -> dict[str, Any]:
        """Get EMS state fragment for WebSocket tick payload (SPEC §10.2)."""
        last = self._decision_log[-1] if self._decision_log else None
        return {
            "setpoint_kw": last.setpoint_kw if last else 0.0,
            "reason": last.reason if last else "",
            "schedule_id": last.schedule_id if last else None,
            "state": self._state,
        }
