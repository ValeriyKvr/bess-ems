"""Battery degradation and State of Health (SoH) model (SPEC §5.2 Step 5).

Two ageing mechanisms are modelled, as in real LFP fleet data:

* **Cycle ageing** — proportional to equivalent full cycles (energy throughput).
* **Calendar ageing** — proportional to elapsed time, accelerated by temperature
  following an Arrhenius-like doubling rule (every ``temp_doubling_k`` kelvin
  above the reference temperature doubles the fade rate).
"""

from dataclasses import dataclass

SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0


@dataclass(frozen=True)
class DegradationState:
    """Immutable degradation state."""

    cycles_total: float
    throughput_kwh: float
    capacity_actual_kwh: float
    soh_pct: float
    calendar_fade_frac: float = 0.0
    cycle_fade_frac: float = 0.0


def step_degradation(
    state: DegradationState,
    delta_energy_kwh: float,
    capacity_nominal_kwh: float,
    cycle_life: float = 6000.0,
    dt_seconds: float = 0.0,
    temp_c: float = 25.0,
    calendar_fade_pct_per_year: float = 0.0,
    temp_ref_c: float = 25.0,
    temp_doubling_k: float = 10.0,
) -> DegradationState:
    """Compute updated degradation state following SPEC §5.2 Step 5:

    cycles_total += |ΔE| / (2 · capacity)
    cycle_fade    = 0.2 · cycles_total / cycle_life        (20% fade at end of life)
    calendar_fade += (rate/100) · (dt/year) · 2^((T − T_ref)/ΔT_double)
    capacity_actual = capacity · (1 − cycle_fade − calendar_fade)
    SoH = (capacity_actual / capacity) * 100
    """
    abs_delta_e = abs(delta_energy_kwh)
    new_throughput = state.throughput_kwh + abs_delta_e
    new_cycles = state.cycles_total + (abs_delta_e / (2.0 * capacity_nominal_kwh))

    cycle_fade = 0.2 * (new_cycles / cycle_life) if cycle_life > 0 else 0.0

    calendar_fade = state.calendar_fade_frac
    if calendar_fade_pct_per_year > 0.0 and dt_seconds > 0.0:
        accel = 2.0 ** ((temp_c - temp_ref_c) / max(1.0, temp_doubling_k))
        calendar_fade += (
            (calendar_fade_pct_per_year / 100.0) * (dt_seconds / SECONDS_PER_YEAR) * accel
        )

    capacity_actual = capacity_nominal_kwh * (1.0 - cycle_fade - calendar_fade)
    # Prevent negative capacity in extreme edge cases
    capacity_actual = max(0.0, capacity_actual)
    soh_pct = (capacity_actual / capacity_nominal_kwh) * 100.0

    return DegradationState(
        cycles_total=round(new_cycles, 6),
        throughput_kwh=round(new_throughput, 4),
        capacity_actual_kwh=round(capacity_actual, 4),
        soh_pct=round(soh_pct, 4),
        calendar_fade_frac=calendar_fade,
        cycle_fade_frac=cycle_fade,
    )


class DegradationModel:
    """Stateful wrapper around pure step_degradation."""

    def __init__(
        self,
        capacity_nominal_kwh: float,
        cycle_life: float = 6000.0,
        calendar_fade_pct_per_year: float = 0.0,
        temp_ref_c: float = 25.0,
        temp_doubling_k: float = 10.0,
    ) -> None:
        self.capacity_nominal_kwh = capacity_nominal_kwh
        self.cycle_life = cycle_life
        self.calendar_fade_pct_per_year = calendar_fade_pct_per_year
        self.temp_ref_c = temp_ref_c
        self.temp_doubling_k = temp_doubling_k
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

    def step(
        self,
        delta_energy_kwh: float,
        dt_seconds: float = 0.0,
        temp_c: float = 25.0,
    ) -> tuple[float, float]:
        """Process throughput energy and return (capacity_actual_kwh, soh_pct)."""
        self._state = step_degradation(
            state=self._state,
            delta_energy_kwh=delta_energy_kwh,
            capacity_nominal_kwh=self.capacity_nominal_kwh,
            cycle_life=self.cycle_life,
            dt_seconds=dt_seconds,
            temp_c=temp_c,
            calendar_fade_pct_per_year=self.calendar_fade_pct_per_year,
            temp_ref_c=self.temp_ref_c,
            temp_doubling_k=self.temp_doubling_k,
        )
        return self._state.capacity_actual_kwh, self._state.soh_pct

    def rescale_nominal(self, capacity_nominal_kwh: float) -> None:
        """Re-base the model on a new nominal capacity, preserving accumulated fade."""
        self.capacity_nominal_kwh = capacity_nominal_kwh
        fade = self._state.cycle_fade_frac + self._state.calendar_fade_frac
        capacity_actual = max(0.0, capacity_nominal_kwh * (1.0 - fade))
        self._state = DegradationState(
            cycles_total=self._state.cycles_total,
            throughput_kwh=self._state.throughput_kwh,
            capacity_actual_kwh=round(capacity_actual, 4),
            soh_pct=round((1.0 - fade) * 100.0, 4),
            calendar_fade_frac=self._state.calendar_fade_frac,
            cycle_fade_frac=self._state.cycle_fade_frac,
        )
