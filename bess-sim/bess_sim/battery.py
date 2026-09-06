"""Battery cell, pack physics and telemetry generator (SPEC §5.1, §5.2)."""

import logging
import random
from dataclasses import dataclass
from typing import Any

from bess_sim.bms import BessOperationalState, BmsManager
from bess_sim.config import BatteryConfig
from bess_sim.degradation import DegradationModel
from bess_sim.pcs import PcsModel
from bess_sim.thermal import ThermalModel

logger = logging.getLogger(__name__)


@dataclass
class BatteryTelemetryData:
    """Telemetry data structure matching SPEC §4.3 schema."""

    ts_sim: str
    ts_wall: str
    bess_id: str
    soc_pct: float
    soh_pct: float
    soe_kwh: float
    power_kw: float
    voltage_v: float
    current_a: float
    temp_c: float
    cycles_total: float
    throughput_kwh: float
    state: str
    available_charge_kw: float
    available_discharge_kw: float
    alarms: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON MQTT publication."""
        return {
            "ts_sim": self.ts_sim,
            "ts_wall": self.ts_wall,
            "bess_id": self.bess_id,
            "soc_pct": round(self.soc_pct, 2),
            "soh_pct": round(self.soh_pct, 2),
            "soe_kwh": round(self.soe_kwh, 2),
            "power_kw": round(self.power_kw, 2),
            "voltage_v": round(self.voltage_v, 2),
            "current_a": round(self.current_a, 2),
            "temp_c": round(self.temp_c, 2),
            "cycles_total": round(self.cycles_total, 3),
            "throughput_kwh": round(self.throughput_kwh, 2),
            "state": self.state,
            "available_charge_kw": round(self.available_charge_kw, 2),
            "available_discharge_kw": round(self.available_discharge_kw, 2),
            "alarms": list(self.alarms),
        }


class Battery:
    """Core BESS simulator executing the complete 8-step physical model (SPEC §5.2)."""

    def __init__(self, config: BatteryConfig | None = None, bess_id: str = "bess-01") -> None:
        self.config = config or BatteryConfig()
        self.bess_id = bess_id
        self._rng = random.Random(self.config.seed)

        # Internal sub-models
        self.bms = BmsManager(self.config)
        self.pcs = PcsModel(self.config.power_max_kw, self.config.ramp_rate_kw_s)
        self.thermal = ThermalModel(
            temp_ambient_c=self.config.temp_ambient_c,
            r_internal=self.config.r_internal,
            k_cooling=self.config.k_cooling,
            c_thermal=self.config.c_thermal,
        )
        self.degradation = DegradationModel(
            capacity_nominal_kwh=self.config.capacity_kwh,
            cycle_life=self.config.cycle_life,
        )

        # Dynamic state
        self.capacity_actual_kwh: float = self.config.capacity_kwh
        self.soc_pct: float = self.config.initial_soc_pct
        self.soe_kwh: float = self.capacity_actual_kwh * (self.soc_pct / 100.0)
        self.voltage_v: float = self._calculate_ocv(self.soc_pct)
        self.current_a: float = 0.0

        # Fault injection toggles (§5.3)
        self.soc_noise_active: bool = False
        self.soc_noise_std_pct: float = 0.5

    def _calculate_ocv(self, soc_pct: float) -> float:
        """Interpolate Open Circuit Voltage from 10-point LFP curve (Step 6)."""
        soc = max(0.0, min(100.0, soc_pct))
        table = self.config.ocv_table

        if soc <= table[0][0]:
            return table[0][1]
        if soc >= table[-1][0]:
            return table[-1][1]

        for i in range(len(table) - 1):
            soc_lo, v_lo = table[i]
            soc_hi, v_hi = table[i + 1]
            if soc_lo <= soc <= soc_hi:
                span = soc_hi - soc_lo
                ratio = (soc - soc_lo) / span if span > 0 else 0.0
                return v_lo + ratio * (v_hi - v_lo)

        return 750.0

    def step(
        self,
        setpoint_kw: float,
        dt_seconds: float,
        ts_sim: str = "",
        ts_wall: str = "",
        include_aux: bool = True,
        include_self_discharge: bool = True,
    ) -> BatteryTelemetryData:
        """Execute one simulation discrete step of duration dt_seconds (SPEC §5.2).

        Follows the exact 8-step physics pipeline:
        1. Calculate BMS available limits & apply PCS ramp-rate and clipping.
        2. Compute energy delta ΔE using charge/discharge efficiencies.
        3. Update SoE and SoC taking into account self-discharge and aux load.
        4. Update temperature using thermodynamic balance.
        5. Update degradation (cycles_total, capacity_actual, SoH).
        6. Compute voltage (OCV curve) and electrical current.
        7. Check protective alarms and FSM state transitions.
        8. Return telemetry payload.
        """
        # Step 1: Limits & PCS Setpoint Clipping
        avail_ch, avail_dis = self.bms.calculate_available_power(
            self.soc_pct, self.config.power_max_kw
        )

        if self.bms.state == BessOperationalState.FAULT:
            self.pcs.reset_power()
            actual_power_kw = 0.0
        else:
            actual_power_kw = self.pcs.apply_setpoint(
                setpoint_kw=setpoint_kw,
                dt_seconds=dt_seconds,
                available_charge_kw=avail_ch,
                available_discharge_kw=avail_dis,
            )

        # Step 2: Energy Exchange ΔE (power_kw > 0 is charge, power_kw < 0 is discharge)
        dt_hours = dt_seconds / 3600.0
        if actual_power_kw > 0.0:
            # Charging: energy stored = P * dt * eff_charge
            delta_e_kwh = actual_power_kw * dt_hours * self.config.eff_charge
        elif actual_power_kw < 0.0:
            # Discharging: energy withdrawn = P * dt / eff_discharge (delta_e_kwh is negative)
            delta_e_kwh = actual_power_kw * dt_hours / self.config.eff_discharge
        else:
            delta_e_kwh = 0.0

        # Step 3: Self-discharge & Aux Load -> Update SoE & SoC
        self_discharge_kwh = 0.0
        if include_self_discharge and self.config.self_discharge_pct_day > 0.0:
            # (pct_per_day / 100) * capacity * (dt / 86400)
            self_discharge_kwh = (
                (self.config.self_discharge_pct_day / 100.0)
                * self.capacity_actual_kwh
                * (dt_seconds / 86400.0)
            )

        aux_load_kwh = 0.0
        if include_aux and self.config.aux_load_kw > 0.0:
            aux_load_kwh = self.config.aux_load_kw * dt_hours

        # Net SoE update
        self.soe_kwh = self.soe_kwh + delta_e_kwh - self_discharge_kwh - aux_load_kwh
        self.soe_kwh = max(0.0, min(self.capacity_actual_kwh, self.soe_kwh))
        self.soc_pct = (
            (self.soe_kwh / self.capacity_actual_kwh) * 100.0
            if self.capacity_actual_kwh > 0
            else 0.0
        )

        # Step 4: Thermal Dynamics
        temp_c = self.thermal.step(actual_power_kw, dt_seconds)

        # Step 5: Degradation Update
        # Energy throughput across battery terminals: |P| * dt
        energy_throughput_step = abs(actual_power_kw) * dt_hours
        self.capacity_actual_kwh, soh_pct = self.degradation.step(energy_throughput_step)

        # Step 6: Voltage & Current calculation
        self.voltage_v = self._calculate_ocv(self.soc_pct)
        if self.voltage_v > 0.0:
            # I = (P * 1000) / V (sign preserved: I > 0 charge, I < 0 discharge)
            self.current_a = (actual_power_kw * 1000.0) / self.voltage_v
        else:
            self.current_a = 0.0

        # Step 7: Check Protective Alarms & Update FSM
        self.bms.check_protections(
            soc_pct=self.soc_pct,
            temp_c=temp_c,
            power_kw=actual_power_kw,
        )
        self.bms.update_fsm(actual_power_kw)

        # If tripped into FAULT, immediately force PCS power to 0
        if self.bms.state == BessOperationalState.FAULT:
            self.pcs.reset_power()
            actual_power_kw = 0.0
            self.current_a = 0.0

        # Step 8: Telemetry Generation
        reported_soc = self.soc_pct
        if self.soc_noise_active:
            noise = self._rng.gauss(0.0, self.soc_noise_std_pct)
            reported_soc = max(0.0, min(100.0, self.soc_pct + noise))

        return BatteryTelemetryData(
            ts_sim=ts_sim,
            ts_wall=ts_wall,
            bess_id=self.bess_id,
            soc_pct=reported_soc,
            soh_pct=soh_pct,
            soe_kwh=self.soe_kwh,
            power_kw=actual_power_kw,
            voltage_v=self.voltage_v,
            current_a=self.current_a,
            temp_c=temp_c,
            cycles_total=self.degradation.cycles_total,
            throughput_kwh=self.degradation.throughput_kwh,
            state=str(self.bms.state),
            available_charge_kw=avail_ch,
            available_discharge_kw=avail_dis,
            alarms=list(self.bms.alarms),
        )

    def handle_command(self, cmd: str) -> bool:
        """Handle control commands from EMS."""
        return self.bms.handle_command(cmd, self.soc_pct, self.thermal.temp_c)

    def set_fault_injection(self, fault_type: str, enabled: bool = True, value: Any = None) -> None:
        """Apply or clear fault injections (§5.3)."""
        logger.info("Fault injection update: %s -> %s (val=%s)", fault_type, enabled, value)
        if fault_type == "force_overheat":
            self.thermal.set_forced_temperature(55.0 if enabled else None)
        elif fault_type == "soc_noise":
            self.soc_noise_active = enabled
        elif fault_type == "power_limit_50":
            self.pcs.power_limit_factor = 0.5 if enabled else 1.0
        elif fault_type == "clear_all":
            self.thermal.set_forced_temperature(None)
            self.soc_noise_active = False
            self.pcs.power_limit_factor = 1.0
