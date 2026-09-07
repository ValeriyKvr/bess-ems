"""Power Conversion System (PCS / Inverter) model (SPEC §5.2 Step 1)."""

import logging

logger = logging.getLogger(__name__)


class PcsModel:
    """Models bidirectional inverter response, clipping, and ramp-rate limiting."""

    def __init__(self, power_max_kw: float = 500.0, ramp_rate_kw_s: float = 50.0) -> None:
        self.power_max_kw = power_max_kw
        self.ramp_rate_kw_s = ramp_rate_kw_s
        self.actual_power_kw: float = 0.0
        self.power_limit_factor: float = 1.0  # Used for fault injection (e.g., 0.5)

    def apply_setpoint(
        self,
        setpoint_kw: float,
        dt_seconds: float,
        available_charge_kw: float,
        available_discharge_kw: float,
    ) -> float:
        """Apply active power limits and ramp rate constraint.

        power_kw > 0 is charge; power_kw < 0 is discharge.
        """
        # Effective maximum bounds incorporating fault factor and BMS available limits
        eff_max_ch = min(self.power_max_kw * self.power_limit_factor, available_charge_kw)
        eff_max_dis = min(self.power_max_kw * self.power_limit_factor, available_discharge_kw)

        # Target power clipped by allowable bounds
        # Note: discharge is negative, so min allowed power is -eff_max_dis
        clipped_target_kw = max(-eff_max_dis, min(eff_max_ch, setpoint_kw))

        if dt_seconds <= 0.0:
            return self.actual_power_kw

        # Ramp rate constraint: |dP/dt| <= ramp_rate_kw_s
        max_delta_p = self.ramp_rate_kw_s * dt_seconds
        power_delta = clipped_target_kw - self.actual_power_kw

        if power_delta > max_delta_p:
            self.actual_power_kw += max_delta_p
        elif power_delta < -max_delta_p:
            self.actual_power_kw -= max_delta_p
        else:
            self.actual_power_kw = clipped_target_kw

        # Hard clamp against allowable BMS envelope: ramp rate can never override BMS limits
        self.actual_power_kw = max(-eff_max_dis, min(eff_max_ch, self.actual_power_kw))

        return round(self.actual_power_kw, 4)

    def reset_power(self) -> None:
        """Immediately force power to zero (e.g., on trip/fault)."""
        self.actual_power_kw = 0.0
