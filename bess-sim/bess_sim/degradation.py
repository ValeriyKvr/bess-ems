"""Battery degradation and State of Health (SoH) model (SPEC §5.2 Step 5)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DegradationState:
    """Immutable degradation state."""

    cycles_total: float
    throughput_kwh: float
    capacity_actual_kwh: float
    soh_pct: float


def step_degradation(
    state: DegradationState,
    delta_energy_kwh: float,
    capacity_nominal_kwh: float,
    cycle_life: float = 6000.0,
) -> DegradationState:
    """Compute updated degradation state following SPEC §5.2 Step 5:

    cycles_total += |ΔE| / (2 · capacity)
    capacity_actual = capacity · (1 − 0.2 · cycles_total / cycle_life)
    SoH = (capacity_actual / capacity) * 100
    """
    abs_delta_e = abs(delta_energy_kwh)
    new_throughput = state.throughput_kwh + abs_delta_e
    new_cycles = state.cycles_total + (abs_delta_e / (2.0 * capacity_nominal_kwh))

    capacity_actual = capacity_nominal_kwh * (1.0 - 0.2 * (new_cycles / cycle_life))
    # Prevent negative capacity in extreme edge cases
    capacity_actual = max(0.0, capacity_actual)
    soh_pct = (capacity_actual / capacity_nominal_kwh) * 100.0

    return DegradationState(
        cycles_total=round(new_cycles, 6),
        throughput_kwh=round(new_throughput, 4),
        capacity_actual_kwh=round(capacity_actual, 4),
        soh_pct=round(soh_pct, 4),
    )


class DegradationModel:
    """Stateful wrapper around pure step_degradation."""

    def __init__(self, capacity_nominal_kwh: float, cycle_life: float = 6000.0) -> None:
        self.capacity_nominal_kwh = capacity_nominal_kwh
        self.cycle_life = cycle_life
        self._state = DegradationState(
            cycles_total=0.0,
            throughput_kwh=0.0,
            capacity_actual_kwh=capacity_nominal_kwh,
            soh_pct=100.0,
        )

    @property
    def cycles_total(self) -> float:
        return self._state.cycles_total

    @property
    def throughput_kwh(self) -> float:
        return self._state.throughput_kwh

    @property
    def capacity_actual_kwh(self) -> float:
        return self._state.capacity_actual_kwh

    @property
    def soh_pct(self) -> float:
        return self._state.soh_pct

    def step(self, delta_energy_kwh: float) -> tuple[float, float]:
        """Process throughput energy and return (capacity_actual_kwh, soh_pct)."""
        self._state = step_degradation(
            state=self._state,
            delta_energy_kwh=delta_energy_kwh,
            capacity_nominal_kwh=self.capacity_nominal_kwh,
            cycle_life=self.cycle_life,
        )
        return self._state.capacity_actual_kwh, self._state.soh_pct
