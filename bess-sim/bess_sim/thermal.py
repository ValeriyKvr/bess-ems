"""Thermal dynamics model for BESS battery cells (SPEC §5.2 Step 4)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThermalState:
    """Immutable thermal state of the battery pack."""

    temp_c: float


def step_thermal(
    state: ThermalState,
    power_kw: float,
    dt_seconds: float,
    temp_ambient_c: float = 25.0,
    r_internal: float = 0.00008,
    k_cooling: float = 0.8,
    c_thermal: float = 300.0,
    forced_temp_c: float | None = None,
) -> ThermalState:
    """Compute temperature after time step dt using formula:

    dT/dt = (P²·R_internal − k·(T − T_ambient)) / C_thermal
    """
    if forced_temp_c is not None:
        return ThermalState(temp_c=forced_temp_c)

    if dt_seconds <= 0.0:
        return state

    current_t = state.temp_c
    heat_gen_kw = (power_kw**2) * r_internal
    heat_dissipated_kw = k_cooling * (current_t - temp_ambient_c)
    net_heat_flow_kw = heat_gen_kw - heat_dissipated_kw

    # dT = (Q_net / C_thermal) * dt
    dt_temp = (net_heat_flow_kw / c_thermal) * dt_seconds
    new_temp = current_t + dt_temp

    return ThermalState(temp_c=round(new_temp, 4))


class ThermalModel:
    """Stateful wrapper around pure step_thermal function."""

    def __init__(
        self,
        temp_ambient_c: float = 25.0,
        r_internal: float = 0.00008,
        k_cooling: float = 0.8,
        c_thermal: float = 300.0,
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

    def step(self, power_kw: float, dt_seconds: float) -> float:
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
        )
        return self._state.temp_c

    def set_forced_temperature(self, temp_c: float | None) -> None:
        """Inject forced temperature for fault testing."""
        self.forced_temp_c = temp_c
        if temp_c is not None:
            self._state = ThermalState(temp_c=temp_c)
