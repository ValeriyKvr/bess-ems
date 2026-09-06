"""Physical realism tests for the BESS model (SPEC §5.1, §5.2).

These cover the behaviours that make the simulation match a real containerised
LFP system: thermal sizing that does not trip at rated power, ohmic terminal
voltage, AC-fed auxiliaries, calendar ageing and live re-configuration.
"""

import pytest

from bess_sim.battery import Battery
from bess_sim.bms import BessOperationalState
from bess_sim.config import BatteryConfig


def test_derived_thermal_coefficients_scale_with_rating() -> None:
    """Thermal coefficients follow the pack rating instead of being hard-coded."""
    small = BatteryConfig(capacity_kwh=1000.0, power_max_kw=500.0)
    big = BatteryConfig(capacity_kwh=4000.0, power_max_kw=2000.0)

    # Heat generated at rated power is always thermal_loss_frac_rated of the rating
    assert (500.0**2) * small.r_internal == pytest.approx(0.025 * 500.0)
    assert (2000.0**2) * big.r_internal == pytest.approx(0.025 * 2000.0)

    # Steady-state rise at rated power equals the design delta-T for both sizes
    assert (0.025 * 500.0) / small.k_cooling == pytest.approx(10.0)
    assert (0.025 * 2000.0) / big.k_cooling == pytest.approx(10.0)

    assert big.c_thermal == pytest.approx(4.0 * small.c_thermal)


def test_rated_power_does_not_trip_overheat_protection() -> None:
    """Sustained full-power operation settles well below the 45 °C trip."""
    config = BatteryConfig(
        soc_max_pct=100.0,
        soc_derate_charge_start_pct=100.0,
        soc_hard_max_pct=100.0,
        ramp_rate_kw_s=1000.0,
    )
    battery = Battery(config=config)

    telemetry = None
    for _ in range(120):  # two simulated hours at one-minute steps
        telemetry = battery.step(setpoint_kw=500.0, dt_seconds=60.0)

    assert telemetry is not None
    assert battery.bms.state != BessOperationalState.FAULT
    assert telemetry.temp_c < config.temp_max_c
    # Ambient + design rise (25 + 10 K), with margin for the transient
    assert 25.0 < telemetry.temp_c < 38.0


def test_terminal_voltage_follows_ohmic_drop() -> None:
    """V_terminal = OCV + I·R: above OCV when charging, below it when discharging."""
    config = BatteryConfig(ramp_rate_kw_s=1000.0, initial_soc_pct=50.0)
    battery = Battery(config=config)
    ocv = battery._calculate_ocv(50.0)

    charging = battery.step(setpoint_kw=400.0, dt_seconds=1.0)
    assert charging.voltage_v > ocv
    assert charging.current_a > 0.0

    discharging = battery.step(setpoint_kw=-400.0, dt_seconds=1.0)
    assert discharging.voltage_v < battery._calculate_ocv(battery.soc_pct)
    assert discharging.current_a < 0.0

    # Reported ohmic heat matches I²R
    assert discharging.heat_kw == pytest.approx(
        (discharging.current_a**2) * (config.r_pack_ohm or 0.0) / 1000.0, rel=1e-6
    )


def test_ac_fed_auxiliaries_do_not_drain_the_pack() -> None:
    """With aux_from_ac the auxiliary load is reported but never discharges the pack."""
    ac_cfg = BatteryConfig(aux_from_ac=True, aux_load_kw=5.0, self_discharge_pct_day=0.0)
    dc_cfg = BatteryConfig(aux_from_ac=False, aux_load_kw=5.0, self_discharge_pct_day=0.0)

    ac_battery = Battery(config=ac_cfg)
    dc_battery = Battery(config=dc_cfg)
    start_soe = ac_battery.soe_kwh

    ac_tel = ac_battery.step(setpoint_kw=0.0, dt_seconds=3600.0)
    dc_battery.step(setpoint_kw=0.0, dt_seconds=3600.0)

    assert ac_tel.aux_kw == pytest.approx(5.0)
    assert ac_battery.soe_kwh == pytest.approx(start_soe)
    assert dc_battery.soe_kwh == pytest.approx(start_soe - 5.0)


def test_calendar_ageing_reduces_soh_without_throughput() -> None:
    """An idle pack still ages, and ages faster when it is hot."""
    cool = Battery(config=BatteryConfig(calendar_fade_pct_per_year=2.0, temp_ambient_c=25.0))
    hot = Battery(config=BatteryConfig(calendar_fade_pct_per_year=2.0, temp_ambient_c=35.0))

    cool_tel = None
    hot_tel = None
    for _ in range(24):  # one simulated day, one-hour steps
        cool_tel = cool.step(setpoint_kw=0.0, dt_seconds=3600.0)
        hot_tel = hot.step(setpoint_kw=0.0, dt_seconds=3600.0)

    assert cool_tel is not None and hot_tel is not None
    assert cool_tel.soh_pct < 100.0
    # +10 K doubles the fade rate, so the hot pack must have lost more capacity
    assert hot_tel.soh_pct < cool_tel.soh_pct


def test_apply_config_conserves_stored_energy() -> None:
    """A live capacity change conserves stored kWh and rescales SoC accordingly."""
    battery = Battery(config=BatteryConfig(capacity_kwh=1000.0, initial_soc_pct=50.0))
    battery.step(setpoint_kw=0.0, dt_seconds=60.0)
    stored = battery.soe_kwh

    changed = battery.apply_config({"capacity_kwh": 2000.0, "power_max_kw": 800.0})

    assert "capacity_kwh" in changed and "power_max_kw" in changed
    assert battery.soe_kwh == pytest.approx(stored)
    assert battery.soc_pct == pytest.approx(stored / 2000.0 * 100.0, rel=1e-3)
    assert battery.pcs.power_max_kw == 800.0
    # Derived thermal coefficients follow the new rating
    assert (800.0**2) * (battery.config.r_internal or 0.0) == pytest.approx(0.025 * 800.0)


def test_apply_config_ignores_unknown_and_unchanged_fields() -> None:
    """Unknown keys are dropped and a no-op update reports no changes."""
    battery = Battery(config=BatteryConfig())
    assert battery.apply_config({"not_a_field": 1}) == []
    assert battery.apply_config({"capacity_kwh": 1000.0}) == []
    assert battery.apply_config({"eff_charge": 0.9}) == ["eff_charge"]
    assert battery.config.eff_charge == 0.9
