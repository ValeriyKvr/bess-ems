"""Battery Management System (BMS) FSM and protective limit controller (SPEC §4.3, §5.2)."""

import logging
from enum import StrEnum

from bess_sim.config import BatteryConfig

logger = logging.getLogger(__name__)


class BessOperationalState(StrEnum):
    """Operational states according to finite state machine (SPEC §4.3)."""

    OFFLINE = "OFFLINE"
    STANDBY = "STANDBY"
    CHARGING = "CHARGING"
    DISCHARGING = "DISCHARGING"
    IDLE = "IDLE"
    FAULT = "FAULT"


class BmsManager:
    """Manages BMS protection, state transitions (FSM), and available power de-rating."""

    def __init__(self, config: BatteryConfig | None = None) -> None:
        self.config = config or BatteryConfig()
        self.state: BessOperationalState = BessOperationalState.STANDBY
        self.alarms: list[str] = []

    def calculate_available_power(
        self,
        soc_pct: float,
        power_max_kw: float,
    ) -> tuple[float, float]:
        """Calculate allowable charge and discharge power with linear derating near limits (SPEC §5.2).

        Returns:
            (available_charge_kw, available_discharge_kw)
        """
        if self.state in (BessOperationalState.FAULT, BessOperationalState.OFFLINE):
            return 0.0, 0.0

        # 1. Charge derating: decreases linearly when SoC > soc_derate_charge_start_pct towards soc_max_pct
        if soc_pct >= self.config.soc_max_pct:
            avail_charge = 0.0
        elif soc_pct <= self.config.soc_derate_charge_start_pct:
            avail_charge = power_max_kw
        else:
            span = self.config.soc_max_pct - self.config.soc_derate_charge_start_pct
            ratio = (self.config.soc_max_pct - soc_pct) / span if span > 0 else 0.0
            avail_charge = max(0.0, min(power_max_kw, power_max_kw * ratio))

        # 2. Discharge derating: decreases linearly when SoC < soc_derate_discharge_start_pct towards soc_min_pct
        if soc_pct <= self.config.soc_min_pct:
            avail_discharge = 0.0
        elif soc_pct >= self.config.soc_derate_discharge_start_pct:
            avail_discharge = power_max_kw
        else:
            span = self.config.soc_derate_discharge_start_pct - self.config.soc_min_pct
            ratio = (soc_pct - self.config.soc_min_pct) / span if span > 0 else 0.0
            avail_discharge = max(0.0, min(power_max_kw, power_max_kw * ratio))

        return round(avail_charge, 2), round(avail_discharge, 2)

    def check_protections(
        self,
        soc_pct: float,
        temp_c: float,
        power_kw: float,
    ) -> bool:
        """Evaluate protective thresholds and trip into FAULT if breached (SPEC §4.3, §5.2 Step 7).

        Returns True if a FAULT condition was triggered or already active.
        """
        new_alarms: list[str] = []

        # Overheat check
        if temp_c > self.config.temp_max_c:
            new_alarms.append(f"OVERHEAT: {temp_c:.1f}°C > {self.config.temp_max_c:.1f}°C")

        # Hard SoC limits
        if soc_pct < self.config.soc_hard_min_pct:
            new_alarms.append(
                f"UNDER_SOC_CRITICAL: {soc_pct:.1f}% < {self.config.soc_hard_min_pct:.1f}%"
            )
        elif soc_pct > self.config.soc_hard_max_pct:
            new_alarms.append(
                f"OVER_SOC_CRITICAL: {soc_pct:.1f}% > {self.config.soc_hard_max_pct:.1f}%"
            )

        # Hard overpower limit (with 5% margin)
        if abs(power_kw) > self.config.power_max_kw * 1.05:
            new_alarms.append(
                f"OVERPOWER: {abs(power_kw):.1f} kW > {self.config.power_max_kw * 1.05:.1f} kW"
            )

        if new_alarms:
            for alarm in new_alarms:
                if alarm not in self.alarms:
                    self.alarms.append(alarm)
            if self.state != BessOperationalState.FAULT:
                logger.error("BMS protective trip triggered: %s", new_alarms)
                self.state = BessOperationalState.FAULT
            return True

        return self.state == BessOperationalState.FAULT

    def update_fsm(self, actual_power_kw: float) -> BessOperationalState:
        """Update operational state machine based on power flow (when not tripped)."""
        if self.state in (BessOperationalState.FAULT, BessOperationalState.OFFLINE):
            return self.state

        if actual_power_kw > 0.05:
            self.state = BessOperationalState.CHARGING
        elif actual_power_kw < -0.05:
            self.state = BessOperationalState.DISCHARGING
        else:
            self.state = BessOperationalState.IDLE

        return self.state

    def handle_command(self, cmd: str, current_soc_pct: float, current_temp_c: float) -> bool:
        """Process supervisory command (SPEC §4.3).

        Commands: 'reset_alarm', 'standby', 'start', 'stop'
        """
        cmd_lower = cmd.lower()
        logger.info("BMS handling command: %s (current state: %s)", cmd, self.state)

        if cmd_lower == "reset_alarm":
            # Can only exit FAULT if physical condition returned to safe region
            safe_temp = current_temp_c <= self.config.temp_max_c
            safe_soc = (
                self.config.soc_hard_min_pct <= current_soc_pct <= self.config.soc_hard_max_pct
            )

            if safe_temp and safe_soc:
                self.alarms.clear()
                self.state = BessOperationalState.STANDBY
                logger.info("Fault cleared, BESS transitioned to STANDBY.")
                return True
            else:
                logger.warning(
                    "Cannot reset alarm: condition still unsafe (T=%.1f°C, SoC=%.1f%%)",
                    current_temp_c,
                    current_soc_pct,
                )
                return False

        elif cmd_lower == "start":
            if self.state == BessOperationalState.OFFLINE:
                self.state = BessOperationalState.STANDBY
                return True

        elif cmd_lower == "stop":
            if self.state != BessOperationalState.FAULT:
                self.state = BessOperationalState.OFFLINE
                return True

        elif cmd_lower == "standby":
            if self.state not in (BessOperationalState.FAULT, BessOperationalState.OFFLINE):
                self.state = BessOperationalState.STANDBY
                return True

        return False
