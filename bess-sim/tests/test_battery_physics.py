"""Comprehensive unit tests for BESS physical model and FSM (SPEC §4.3, §5)."""

import pytest

from bess_sim.battery import Battery
from bess_sim.bms import BessOperationalState
from bess_sim.config import BatteryConfig


def test_1_charge_efficiency_yields_expected_energy() -> None:
    """Requirement 1: Заряд 1 год на 100 кВт при eff 0.95 дає +95 кВт·год."""
    config = BatteryConfig(
        capacity_kwh=1000.0,
        eff_charge=0.95,
        initial_soc_pct=50.0,
        ramp_rate_kw_s=1000.0,  # Fast ramp to reach 100 kW immediately
    )
    battery = Battery(config=config)
    initial_soe = battery.soe_kwh

    # Step: 1 hour (3600 seconds) at 100 kW
    battery.step(
        setpoint_kw=100.0,
        dt_seconds=3600.0,
        include_aux=False,
        include_self_discharge=False,
    )

    delta_soe = battery.soe_kwh - initial_soe
    assert pytest.approx(delta_soe, rel=1e-3) == 95.0


def test_2_discharge_below_hard_min_triggers_fault() -> None:
    """Requirement 2: Розряд нижче soc_hard_min → FAULT."""
    config = BatteryConfig(
        capacity_kwh=1000.0,
        initial_soc_pct=5.5,
        soc_hard_min_pct=5.0,
        soc_min_pct=0.0,  # Allow discharging below 10% to test hard emergency limit
        ramp_rate_kw_s=1000.0,
    )
    battery = Battery(config=config)

    # Discharge with 200 kW for 300 s (approx 16.67 kWh removed, reducing SoC from 5.5% to ~3.8%)
    telemetry = battery.step(
        setpoint_kw=-200.0,
        dt_seconds=300.0,
        include_aux=False,
        include_self_discharge=False,
    )

    assert battery.soc_pct < 5.0
    assert battery.bms.state == BessOperationalState.FAULT
    assert telemetry.state == "FAULT"
    assert any("UNDER_SOC_CRITICAL" in alarm for alarm in battery.bms.alarms)
    # In FAULT, power must be cut to zero
    assert battery.pcs.actual_power_kw == 0.0


def test_3_ramp_rate_limits_power_jump() -> None:
    """Requirement 3: Ramp rate обмежує стрибок setpoint."""
    config = BatteryConfig(
        power_max_kw=500.0,
        ramp_rate_kw_s=50.0,
        initial_soc_pct=50.0,
    )
    battery = Battery(config=config)

    # Command jumps from 0 to 500 kW, dt = 1.0 second
    telemetry = battery.step(
        setpoint_kw=500.0,
        dt_seconds=1.0,
        include_aux=False,
        include_self_discharge=False,
    )

    # In 1 second with ramp_rate = 50 kW/s, power must not exceed 50.0 kW
    assert telemetry.power_kw == pytest.approx(50.0, abs=0.1)

    # Next second: power rises to 100 kW
    telemetry2 = battery.step(
        setpoint_kw=500.0,
        dt_seconds=1.0,
        include_aux=False,
        include_self_discharge=False,
    )
    assert telemetry2.power_kw == pytest.approx(100.0, abs=0.1)


def test_4_full_cycle_increments_cycles_total_by_one() -> None:
    """Requirement 4: 1 повний цикл збільшує cycles_total на 1.0."""
    config = BatteryConfig(
        capacity_kwh=1000.0,
        eff_charge=1.0,
        eff_discharge=1.0,
        soc_min_pct=0.0,
        soc_max_pct=100.0,
        soc_hard_min_pct=0.0,
        soc_hard_max_pct=100.0,
        temp_max_c=1000.0,
        ramp_rate_kw_s=1000.0,
        initial_soc_pct=0.0,
    )
    battery = Battery(config=config)

    # Full charge: 1000 kWh throughput (500 kW for 2 hours = 7200 s)
    battery.step(
        setpoint_kw=500.0,
        dt_seconds=7200.0,
        include_aux=False,
        include_self_discharge=False,
    )
    assert pytest.approx(battery.degradation.cycles_total, abs=1e-3) == 0.5

    # Full discharge: 1000 kWh throughput (-500 kW for 2 hours = 7200 s)
    battery.step(
        setpoint_kw=-500.0,
        dt_seconds=7200.0,
        include_aux=False,
        include_self_discharge=False,
    )
    # Total throughput 2000 kWh / (2 * 1000 kWh) = 1.0 equivalent cycle
    assert pytest.approx(battery.degradation.cycles_total, abs=1e-3) == 1.0


def test_5_deterministic_execution_with_seed() -> None:
    """Requirement 5: З seed результат детермінований."""
    config1 = BatteryConfig(seed=999)
    b1 = Battery(config=config1)
    b1.set_fault_injection("soc_noise", enabled=True)
    res1 = [b1.step(setpoint_kw=50.0, dt_seconds=60.0).soc_pct for _ in range(10)]

    config2 = BatteryConfig(seed=999)
    b2 = Battery(config=config2)
    b2.set_fault_injection("soc_noise", enabled=True)
    res2 = [b2.step(setpoint_kw=50.0, dt_seconds=60.0).soc_pct for _ in range(10)]

    assert res1 == res2


def test_linear_power_derating_near_soc_limits() -> None:
    """Test linear derating near upper (85-90%) and lower (10-15%) SoC limits (SPEC §5.2)."""
    config = BatteryConfig(
        power_max_kw=500.0,
        soc_min_pct=10.0,
        soc_max_pct=90.0,
        soc_derate_charge_start_pct=85.0,
        soc_derate_discharge_start_pct=15.0,
    )
    bms = Battery(config=config).bms

    # Normal region (50% SoC): full power
    ch, dis = bms.calculate_available_power(50.0, 500.0)
    assert ch == 500.0
    assert dis == 500.0

    # Charge derating midpoint (87.5% SoC): 50% derated charge
    ch_mid, _ = bms.calculate_available_power(87.5, 500.0)
    assert pytest.approx(ch_mid, abs=1.0) == 250.0

    # Charge limit reached (90% SoC): 0 kW charge
    ch_max, _ = bms.calculate_available_power(90.0, 500.0)
    assert ch_max == 0.0

    # Discharge derating midpoint (12.5% SoC): 50% derated discharge
    _, dis_mid = bms.calculate_available_power(12.5, 500.0)
    assert pytest.approx(dis_mid, abs=1.0) == 250.0

    # Discharge limit reached (10% SoC): 0 kW discharge
    _, dis_min = bms.calculate_available_power(10.0, 500.0)
    assert dis_min == 0.0


def test_overheat_protection_and_reset_alarm() -> None:
    """Test overheat trip into FAULT and reset_alarm recovery."""
    config = BatteryConfig(temp_max_c=45.0)
    battery = Battery(config=config)

    # Force temperature above threshold
    battery.set_fault_injection("force_overheat", enabled=True)
    telemetry = battery.step(setpoint_kw=0.0, dt_seconds=1.0)

    assert telemetry.state == "FAULT"
    assert any("OVERHEAT" in a for a in telemetry.alarms)

    # Cannot reset while still overheating
    assert not battery.handle_command("reset_alarm")
    assert battery.bms.state == BessOperationalState.FAULT

    # Clear forced overheat condition
    battery.set_fault_injection("clear_all")
    battery.thermal.temp_ambient_c = 25.0
    battery.thermal._state = type(battery.thermal._state)(temp_c=25.0)

    # Now reset succeeds
    assert battery.handle_command("reset_alarm")
    assert battery.bms.state == BessOperationalState.STANDBY
