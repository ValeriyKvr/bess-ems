"""Thermal dynamics model for BESS battery cells (SPEC §5.2 Step 4).

Realistic parameters for a 1 MWh / 500 kW LFP containerized BESS:
- Pack mass ~10 tonnes, effective thermal mass ~5000 kJ/K (c_thermal).
- Internal resistance scaled to pack level: ~0.00005 Ω·kW⁻² equivalent.
- Forced-air / liquid cooling coefficient: ~1.2 kW/K.
- At full power (500 kW) equilibrium temperature: ~35°C (well below 45°C trip).
"""

from dataclasses import dataclass

# Maximum internal sub-step to ensure Euler stability (seconds)
_MAX_SUBSTEP_S = 30.0


@dataclass(frozen=True)
class ThermalState:
    """Immutable thermal state of the battery pack."""

    temp_c: float


def step_thermal(
    state: ThermalState,
    power_kw: float,
    dt_seconds: float,
    temp_ambient_c: float = 25.0,
    r_internal: float = 0.00005,
    k_cooling: float = 1.2,
    c_thermal: float = 5000.0,
    forced_temp_c: float | None = None,
    heat_kw: float | None = None,
) -> ThermalState:
    """Compute temperature after time step dt using formula:

    dT/dt = (P²·R_internal − k·(T − T_ambient)) / C_thermal

    When ``heat_kw`` is supplied it replaces the P²·R_internal term — the caller
    has already computed the true ohmic loss I²·R from the terminal current,
    which is the physically correct heat source.

    Uses sub-stepping (max 30 s per Euler step) to prevent numerical
    instability at high simulation speeds (600×, 3600×).
    """
    if forced_temp_c is not None:
        return ThermalState(temp_c=forced_temp_c)

    if dt_seconds <= 0.0:
        return state

    current_t = state.temp_c
    heat_gen_kw = heat_kw if heat_kw is not None else (power_kw**2) * r_internal

    # Sub-step for numerical stability
    remaining = dt_seconds
    while remaining > 0.0:
        sub_dt = min(remaining, _MAX_SUBSTEP_S)
        heat_dissipated_kw = k_cooling * (current_t - temp_ambient_c)
        net_heat_flow_kw = heat_gen_kw - heat_dissipated_kw
        current_t += (net_heat_flow_kw / c_thermal) * sub_dt
        remaining -= sub_dt

    return ThermalState(temp_c=round(current_t, 4))


class ThermalModel:
    """Stateful wrapper around pure step_thermal function."""

    def __init__(
        self,
        temp_ambient_c: float = 25.0,
        r_internal: float = 0.00005,
        k_cooling: float = 1.2,
        c_thermal: float = 5000.0,
    ) -> None:
        self.temp_ambient_c = temp_ambient_c
        self.r_internal = r_internal
        self.k_cooling = k_cooling
        self.c_thermal = c_thermal
        self._state = ThermalState(temp_c=temp_ambient_c)
        self.forced_temp_c: float | None = None

    @property
    def temp_c(self) -> float:
        return self._state.temp_c

    def step(self, power_kw: float, dt_seconds: float, heat_kw: float | None = None) -> float:
        """Advance thermal model by dt_seconds."""
        self._state = step_thermal(
            state=self._state,
            power_kw=power_kw,
            dt_seconds=dt_seconds,
            temp_ambient_c=self.temp_ambient_c,
            r_internal=self.r_internal,
            k_cooling=self.k_cooling,
            c_thermal=self.c_thermal,
            forced_temp_c=self.forced_temp_c,
            heat_kw=heat_kw,
        )
        return self._state.temp_c

    def set_forced_temperature(self, temp_c: float | None) -> None:
        """Inject forced temperature for fault testing."""
        self.forced_temp_c = temp_c
        if temp_c is not None:
            self._state = ThermalState(temp_c=temp_c)
