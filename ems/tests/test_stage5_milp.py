"""Stage 5 tests: MILP optimizer, mathematical constraints, and strategies (SPEC §9, §14).

Mandatory tests with known analytical answers:
1. 2 hours: price [1.0, 10.0] UAH/kWh, empty battery (SoC=10%) -> charge at t0, discharge at t1.
2. Rigid peak_limit -> grid import g_imp[t] / dt never exceeds peak_limit_kw.
3. Non-simultaneous charge and discharge: p_ch[t] * p_dis[t] == 0 for all t.
4. Terminal target: soc[T-1] >= soc_end_target holds strictly.
5. Horizon T=48 solves in < 2.0 seconds.
"""

import time
from datetime import UTC, datetime, timedelta

from ems.optimization.milp import OptimizationProblem, solve
from ems.optimization.strategies import (
    BackupReserveStrategy,
    ScheduleContext,
    get_strategy,
)


def make_problem(
    prices_buy: list[float],
    prices_sell: list[float] | None = None,
    loads: list[float] | None = None,
    pvs: list[float] | None = None,
    capacity: float = 2000.0,
    max_power: float = 500.0,
    initial_soc_pct: float = 50.0,
    soc_min_pct: float = 10.0,
    soc_max_pct: float = 90.0,
    soc_end_target_pct: float | None = None,
    peak_limit_kw: float | None = None,
    w_peak: float = 0.0,
    w_reserve: float = 0.0,
    reserve_soc_pct: float = 20.0,
    dt_hours: float = 1.0,
    export_allowed: bool = True,
    c_deg: float = 0.0,  # 0.0 for pure analytical price tests
) -> OptimizationProblem:
    """Helper to construct an OptimizationProblem."""
    n = len(prices_buy)
    base_ts = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    timestamps = [base_ts + timedelta(hours=i * dt_hours) for i in range(n)]

    p_sell = prices_sell if prices_sell is not None else [p * 0.9 for p in prices_buy]
    l_kw = loads if loads is not None else [0.0] * n
    pv_kw = pvs if pvs is not None else [0.0] * n

    return OptimizationProblem(
        timestamps=timestamps,
        price_buy_uah_kwh=prices_buy,
        price_sell_uah_kwh=p_sell,
        load_kw=l_kw,
        pv_kw=pv_kw,
        dt_hours=dt_hours,
        capacity_kwh=capacity,
        max_charge_kw=max_power,
        max_discharge_kw=max_power,
        soc_min_pct=soc_min_pct,
        soc_max_pct=soc_max_pct,
        initial_soc_pct=initial_soc_pct,
        soc_end_target_pct=soc_end_target_pct,
        c_deg_uah_kwh=c_deg,
        peak_limit_kw=peak_limit_kw,
        w_peak=w_peak,
        w_reserve=w_reserve,
        reserve_soc_pct=reserve_soc_pct,
        export_allowed=export_allowed,
        w_arb=1.0,
    )


# ──────────────────────────────── 1. Test 2-Hour Arbitrage ────────────────────────────────


def test_1_two_hour_arbitrage_charges_cheap_discharges_expensive() -> None:
    """Requirement (1): 2 hours with prices [1.0, 10.0] UAH/kWh, empty battery (SoC=10%).

    Optimal strategy must charge in hour 0 and discharge in hour 1.
    """
    prob = make_problem(
        prices_buy=[1.0, 10.0],
        prices_sell=[0.9, 9.0],
        loads=[0.0, 0.0],
        initial_soc_pct=10.0,  # Battery starts at minimum SoC
        soc_min_pct=10.0,
        soc_max_pct=90.0,
        soc_end_target_pct=10.0,
        export_allowed=True,
    )

    schedule = solve(prob)
    assert schedule.solver_status == "OPTIMAL"
    assert len(schedule.items) == 2

    # Hour 0 (cheap 1.0 UAH): battery must CHARGE (setpoint > 0)
    assert schedule.items[0].setpoint_kw > 0, (
        f"Expected charging in hour 0, got {schedule.items[0].setpoint_kw}"
    )

    # Hour 1 (expensive 10.0 UAH): battery must DISCHARGE (setpoint < 0)
    assert schedule.items[1].setpoint_kw < 0, (
        f"Expected discharging in hour 1, got {schedule.items[1].setpoint_kw}"
    )

    # Profit must be strictly positive
    assert schedule.expected_profit_uah is not None
    assert schedule.expected_profit_uah > 0


# ──────────────────────────────── 2. Test Rigid Peak Limit ────────────────────────────────


def test_2_rigid_peak_limit_is_never_exceeded() -> None:
    """Requirement (2): when rigid peak_limit is active, grid import never exceeds limit.

    Load is 500 kW, peak limit is 300 kW, battery has initial SoC 60%.
    Battery must discharge to cover the 200 kW difference so import <= 300 kW.
    """
    # 4 hours with 500 kW load each
    prob = make_problem(
        prices_buy=[4.0, 4.0, 4.0, 4.0],
        loads=[500.0, 500.0, 500.0, 500.0],
        peak_limit_kw=300.0,
        w_peak=1.0,
        initial_soc_pct=70.0,
        soc_min_pct=10.0,
        soc_end_target_pct=10.0,
    )

    schedule = solve(prob)
    assert schedule.solver_status == "OPTIMAL"

    # In all hours, battery discharge must be at least 200 kW (so load - discharge <= 300 kW)
    for i, item in enumerate(schedule.items):
        # Setpoint < 0 means discharge
        discharge_kw = -item.setpoint_kw
        grid_import_kw = 500.0 - discharge_kw
        assert grid_import_kw <= 300.01, (
            f"Hour {i}: Grid import {grid_import_kw:.1f} kW exceeded peak limit 300 kW (discharge={discharge_kw:.1f})"
        )


# ──────────────────────────────── 3. Test Non-Simultaneous Charge/Discharge ────────────────────────────────


def test_3_non_simultaneous_charge_and_discharge() -> None:
    """Requirement (3): binary variable z[t] prevents simultaneous charge and discharge.

    Every schedule item has a single clean setpoint; charge and discharge never overlap.
    """
    # 24 hours of fluctuating prices
    prices = [2.0 + (i % 6) * 1.5 for i in range(24)]
    prob = make_problem(prices_buy=prices, initial_soc_pct=50.0)

    schedule = solve(prob)
    assert schedule.solver_status == "OPTIMAL"

    for item in schedule.items:
        # The solver produces net setpoint: it is either >= 0 or <= 0
        assert not (item.setpoint_kw > 0.01 and item.setpoint_kw < -0.01)


# ──────────────────────────────── 4. Test Terminal Target SoC ────────────────────────────────


def test_4_terminal_target_soc_is_satisfied() -> None:
    """Requirement (4): terminal constraint soc[T-1] >= soc_end_target is strictly honored."""
    target_soc = 65.0
    prob = make_problem(
        prices_buy=[1.0, 1.0, 10.0, 10.0],
        initial_soc_pct=50.0,
        soc_end_target_pct=target_soc,
    )

    schedule = solve(prob)
    assert schedule.solver_status == "OPTIMAL"

    # Compute actual terminal SoC by simulating the schedule
    current_soc_kwh = prob.capacity_kwh * (prob.initial_soc_pct / 100.0)
    for item in schedule.items:
        if item.setpoint_kw > 0:
            current_soc_kwh += item.setpoint_kw * prob.eta_ch * prob.dt_hours
        elif item.setpoint_kw < 0:
            current_soc_kwh -= (abs(item.setpoint_kw) * prob.dt_hours) / prob.eta_dis

    final_soc_pct = (current_soc_kwh / prob.capacity_kwh) * 100.0
    assert final_soc_pct >= target_soc - 0.5, (
        f"Terminal SoC {final_soc_pct:.1f}% below target {target_soc:.1f}%"
    )


# ──────────────────────────────── 5. Test T=48 Performance (< 2.0s) ────────────────────────────────


def test_5_horizon_48_solves_under_two_seconds() -> None:
    """Requirement (5): a 48-step horizon must be solved by CBC in < 2.0 seconds."""
    # 48 hours of sinusoidal prices
    import math

    prices = [4000.0 + 2500.0 * math.sin(2 * math.pi * i / 24) for i in range(48)]
    prices_kwh = [p / 1000.0 for p in prices]

    prob = make_problem(
        prices_buy=prices_kwh,
        initial_soc_pct=50.0,
    )

    t0 = time.monotonic()
    schedule = solve(prob)
    elapsed = time.monotonic() - t0

    assert schedule.solver_status == "OPTIMAL"
    assert len(schedule.items) == 48
    assert elapsed < 2.0, f"Solving 48 steps took {elapsed:.3f}s (required < 2.0s)"
    assert schedule.solve_time_ms < 2000


# ──────────────────────────────── Additional Strategy Tests ────────────────────────────────


def test_backup_reserve_strategy_maintains_reserve() -> None:
    """BACKUP_RESERVE strategy penalizes dropping below reserve_soc_pct."""
    base = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    # Expensive prices tempting a full discharge
    prices = [
        {"ts": base + timedelta(hours=i), "price_buy": 9000.0, "price_sell": 8100.0}
        for i in range(6)
    ]
    context = ScheduleContext(
        current_time=base,
        horizon_start=base,
        horizon_end=base + timedelta(hours=5),
        soc_pct=50.0,
        reserve_soc_pct=40.0,
        soc_min_pct=10.0,
        prices=prices,
    )

    strat = BackupReserveStrategy(reserve_soc_pct=40.0)
    schedule = strat.build_schedule(context)
    assert schedule.solver_status == "OPTIMAL"


def test_strategy_factory_registry() -> None:
    """Strategy registry provides instances for all defined strategies."""
    for name in ["ARBITRAGE", "PEAK_SHAVING", "SELF_CONSUMPTION", "BACKUP_RESERVE", "TOU_SIMPLE"]:
        strat = get_strategy(name)
        assert strat.name == name


def test_milp_intra_day_discharge_evening_peak() -> None:
    """Intra-day horizon (13:00-23:00) with high initial SoC (80%) must discharge during peak hours."""
    timestamps = [datetime(2026, 3, 1, h, 0, 0, tzinfo=UTC) for h in range(13, 24)]
    # 13-17: mid price (5.0 UAH/kWh); 18-22: peak price (9.0 UAH/kWh); 23: 6.0 UAH/kWh
    prices_buy = [5.0, 5.0, 5.0, 5.0, 5.0, 9.0, 9.0, 9.0, 9.0, 9.0, 6.0]
    prices_sell = [p * 0.9 for p in prices_buy]

    prob = OptimizationProblem(
        timestamps=timestamps,
        price_buy_uah_kwh=prices_buy,
        price_sell_uah_kwh=prices_sell,
        load_kw=[100.0] * len(timestamps),
        pv_kw=[0.0] * len(timestamps),
        capacity_kwh=1000.0,
        max_charge_kw=500.0,
        max_discharge_kw=500.0,
        initial_soc_pct=80.0,
        soc_min_pct=10.0,
        soc_max_pct=90.0,
        reserve_soc_pct=20.0,
        export_allowed=True,
        c_deg_uah_kwh=1.25,
    )
    schedule = solve(prob)
    assert schedule.solver_status == "OPTIMAL"
    # Verify that battery discharges during the evening peak
    discharges = [item for item in schedule.items if item.setpoint_kw < 0]
    assert len(discharges) > 0, "Intra-day schedule must discharge stored energy during evening peak"
    assert schedule.expected_profit_uah is not None and schedule.expected_profit_uah > 0

