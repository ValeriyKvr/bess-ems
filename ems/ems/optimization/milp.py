"""MILP optimization solver for BESS dispatch using PuLP and CBC (SPEC §9, docs/optimization.md).

Implements complete mathematical model with:
- Simultaneous charge/discharge prohibition via binary variable z[t]
- SoC dynamics with charge/discharge efficiencies and self-discharge
- Hard SoC bounds and terminal target
- Facility power balance (load, pv, import, export)
- Rigid and soft peak shaving
- Export limits / prohibition
- Emergency reserve penalty linearization via slack variable
- Variable time step delta_t (default 1h, optional 15m)
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime

import pulp

from ems.optimization.strategies import Schedule, ScheduleItem

logger = logging.getLogger(__name__)


@dataclass
class OptimizationProblem:
    """Inputs and parameters for the MILP BESS optimizer."""

    # Time series (all lists must have length = horizon_steps)
    timestamps: list[datetime]
    price_buy_uah_kwh: list[float]  # Buy price per kWh (including tariffs)
    price_sell_uah_kwh: list[float]  # Sell price per kWh (including export discount)
    load_kw: list[float]  # Facility load power in kW
    pv_kw: list[float]  # PV solar generation in kW

    # Time step
    dt_hours: float = 1.0  # Duration of each step in hours (1.0 = 1h, 0.25 = 15m)

    # Battery parameters
    capacity_kwh: float = 2000.0
    max_charge_kw: float = 500.0
    max_discharge_kw: float = 500.0
    eta_ch: float = 0.95
    eta_dis: float = 0.95
    soc_min_pct: float = 10.0
    soc_max_pct: float = 90.0
    initial_soc_pct: float = 50.0
    soc_end_target_pct: float | None = None  # Defaults to initial_soc_pct
    c_deg_uah_kwh: float = 1.25
    self_discharge_rate_per_day: float = 0.0005  # 0.05% per day

    # Strategy & grid parameters
    peak_limit_kw: float | None = None  # Rigid peak limit if set
    c_peak_uah_kw: float = 100.0  # Capacity fee / penalty
    reserve_soc_pct: float = 20.0  # Target reserve SoC for BACKUP_RESERVE
    reserve_penalty_uah_kwh: float = 50.0  # Penalty for falling below reserve
    export_allowed: bool = True
    export_limit_kw: float = 500.0

    # Weights for multi-objective optimization (SPEC §6.7, §9.2)
    w_arb: float = 1.0
    w_peak: float = 0.0
    w_reserve: float = 0.0
    w_self: float = 0.0

    # Metadata
    strategy_name: str = "ARBITRAGE"
    solver_time_limit_sec: int = 10

    @property
    def horizon_steps(self) -> int:
        return len(self.timestamps)


def solve(problem: OptimizationProblem) -> Schedule:
    """Solve the MILP dispatch problem using PuLP and CBC solver (SPEC §9).

    Returns an optimized Schedule object.
    """
    t_start = time.monotonic()
    T = problem.horizon_steps
    if T == 0:
        logger.warning("Empty optimization problem provided.")
        return Schedule(
            strategy=problem.strategy_name,
            capacity_kwh=problem.capacity_kwh,
            solver_status="NO_DATA",
            solve_time_ms=0,
        )

    dt = problem.dt_hours
    capacity = problem.capacity_kwh
    soc_min_kwh = capacity * (problem.soc_min_pct / 100.0)
    soc_max_kwh = capacity * (problem.soc_max_pct / 100.0)
    soc_0_kwh = capacity * (problem.initial_soc_pct / 100.0)

    # End target: default to initial SoC if not specified
    target_pct = (
        problem.soc_end_target_pct
        if problem.soc_end_target_pct is not None
        else problem.initial_soc_pct
    )
    soc_end_target_kwh = capacity * (target_pct / 100.0)

    reserve_kwh = capacity * (problem.reserve_soc_pct / 100.0)
    self_discharge_kwh = capacity * problem.self_discharge_rate_per_day * (dt / 24.0)

    # ──────────────────────────────── 1. Initialize PuLP Model ────────────────────────────────
    prob = pulp.LpProblem("BESS_Dispatch_Optimization", pulp.LpMinimize)

    # ──────────────────────────────── 2. Decision Variables ────────────────────────────────
    # Power variables
    p_ch = [
        pulp.LpVariable(f"p_ch_{t}", lowBound=0, upBound=problem.max_charge_kw) for t in range(T)
    ]
    p_dis = [
        pulp.LpVariable(f"p_dis_{t}", lowBound=0, upBound=problem.max_discharge_kw)
        for t in range(T)
    ]
    # Binary variable to forbid simultaneous charge & discharge: 1 = charge, 0 = discharge
    z = [pulp.LpVariable(f"z_{t}", cat=pulp.LpBinary) for t in range(T)]

    # Battery stored energy (kWh) at end of interval t
    soc = [pulp.LpVariable(f"soc_{t}", lowBound=soc_min_kwh, upBound=soc_max_kwh) for t in range(T)]

    # Grid import and export (kWh per interval)
    g_imp = [pulp.LpVariable(f"g_imp_{t}", lowBound=0) for t in range(T)]
    max_exp_kwh = (problem.export_limit_kw * dt) if problem.export_allowed else 0.0
    g_exp = [pulp.LpVariable(f"g_exp_{t}", lowBound=0, upBound=max_exp_kwh) for t in range(T)]

    # Peak import power variable (kW) across horizon
    peak = pulp.LpVariable("peak", lowBound=0)

    # Slack variable for emergency reserve violation
    slack_reserve = [pulp.LpVariable(f"slack_res_{t}", lowBound=0) for t in range(T)]

    # ──────────────────────────────── 3. Objective Function (SPEC §9.2) ────────────────────────────────
    obj_terms: list[pulp.LpAffineExpression] = []

    # Energy purchasing cost, export revenue, and battery degradation cost
    for t in range(T):
        p_buy = problem.price_buy_uah_kwh[t]
        p_sell = problem.price_sell_uah_kwh[t] if problem.export_allowed else 0.0

        # Arbitrage / energy cost: buy - sell
        obj_terms.append(problem.w_arb * (p_buy * g_imp[t] - p_sell * g_exp[t]))

        # Self consumption bonus: penalize grid import heavily if w_self > 0
        if problem.w_self > 0:
            obj_terms.append(problem.w_self * p_buy * g_imp[t])

        # Battery degradation cost: c_deg * throughput_kwh
        # Note: Throughput energy at inverter is (p_ch + p_dis) * dt
        obj_terms.append(problem.c_deg_uah_kwh * (p_ch[t] + p_dis[t]) * dt)

        # Backup reserve penalty: slack_reserve * penalty
        if problem.w_reserve > 0:
            obj_terms.append(problem.w_reserve * problem.reserve_penalty_uah_kwh * slack_reserve[t])

    # Peak shaving fee: w_peak * c_peak * peak
    if problem.w_peak > 0:
        obj_terms.append(problem.w_peak * problem.c_peak_uah_kw * peak)

    prob += pulp.lpSum(obj_terms), "Total_Operational_Cost"

    # ──────────────────────────────── 4. Constraints (SPEC §9.3) ────────────────────────────────
    for t in range(T):
        # (4.1) Battery Energy Balance
        prev_soc = soc_0_kwh if t == 0 else soc[t - 1]
        prob += (
            soc[t]
            == prev_soc
            + problem.eta_ch * p_ch[t] * dt
            - (p_dis[t] * dt) / problem.eta_dis
            - self_discharge_kwh,
            f"Battery_Energy_Balance_{t}",
        )

        # (4.2) Non-simultaneous Charge / Discharge (Inverter limits)
        prob += p_ch[t] <= problem.max_charge_kw * z[t], f"Charge_Binary_Limit_{t}"
        prob += p_dis[t] <= problem.max_discharge_kw * (1 - z[t]), f"Discharge_Binary_Limit_{t}"

        # (4.3) Facility Energy Balance
        # g_imp - g_exp = (load + p_ch - p_dis - pv) * dt
        load_kwh = problem.load_kw[t] * dt
        pv_kwh = problem.pv_kw[t] * dt
        prob += (
            g_imp[t] - g_exp[t] == load_kwh + p_ch[t] * dt - p_dis[t] * dt - pv_kwh,
            f"Facility_Energy_Balance_{t}",
        )

        # (4.4) Peak Power Definition: peak >= g_imp[t] / dt
        prob += g_imp[t] <= peak * dt, f"Peak_Definition_{t}"

        # (4.5) Rigid Peak Limit if configured
        if problem.peak_limit_kw is not None and problem.w_peak > 0:
            prob += peak <= problem.peak_limit_kw, f"Rigid_Peak_Limit_{t}"

        # (4.6) Reserve Slack: slack_reserve >= reserve_kwh - soc[t]
        if problem.w_reserve > 0:
            prob += slack_reserve[t] >= reserve_kwh - soc[t], f"Reserve_Slack_{t}"

    # (4.7) Terminal Target: soc[T-1] >= soc_end_target
    prob += soc[T - 1] >= soc_end_target_kwh, "Terminal_Target_SoC"

    # ──────────────────────────────── 5. Solve Problem ────────────────────────────────
    solver = pulp.PULP_CBC_CMD(
        msg=False,
        timeLimit=problem.solver_time_limit_sec,
    )
    prob.solve(solver)
    status_str = pulp.LpStatus[prob.status]

    solve_time_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "MILP solver finished: status=%s, T=%d, solve_time=%dms",
        status_str,
        T,
        solve_time_ms,
    )

    if prob.status != pulp.constants.LpStatusOptimal:
        logger.warning("MILP optimization did not reach optimal solution (status: %s).", status_str)
        return Schedule(
            strategy=problem.strategy_name,
            capacity_kwh=problem.capacity_kwh,
            created_at_sim=problem.timestamps[0],
            horizon_start=problem.timestamps[0],
            horizon_end=problem.timestamps[-1],
            solver_status=status_str,
            solve_time_ms=solve_time_ms,
        )

    # ──────────────────────────────── 6. Extract Schedule Results ────────────────────────────────
    items: list[ScheduleItem] = []
    total_cost_actual = 0.0
    total_cost_baseline = 0.0
    total_throughput_kwh = 0.0

    for t in range(T):
        ch_val = float(pulp.value(p_ch[t]) or 0.0)
        dis_val = float(pulp.value(p_dis[t]) or 0.0)
        imp_val = float(pulp.value(g_imp[t]) or 0.0)
        exp_val = float(pulp.value(g_exp[t]) or 0.0)
        soc_val = float(pulp.value(soc[t]) or 0.0)

        # Conventional sign: >0 charge, <0 discharge (SPEC §4.3)
        net_setpoint = ch_val if ch_val > 0.1 else (-dis_val if dis_val > 0.1 else 0.0)

        p_buy = problem.price_buy_uah_kwh[t]
        p_sell = problem.price_sell_uah_kwh[t]

        # Reason string
        soc_pct = (soc_val / capacity) * 100.0
        if net_setpoint > 0:
            reason = (
                f"MILP charge (+{net_setpoint:.0f}kW, SoC={soc_pct:.1f}%, price={p_buy * 1000:.0f})"
            )
        elif net_setpoint < 0:
            reason = f"MILP discharge ({net_setpoint:.0f}kW, SoC={soc_pct:.1f}%, price={p_sell * 1000:.0f})"
        else:
            reason = f"MILP idle (SoC={soc_pct:.1f}%)"

        items.append(
            ScheduleItem(
                ts=problem.timestamps[t],
                setpoint_kw=round(net_setpoint, 2),
                reason=reason,
            )
        )

        # Baseline cost (without battery)
        base_net = max(0.0, (problem.load_kw[t] - problem.pv_kw[t]) * dt)
        total_cost_baseline += base_net * p_buy

        # Actual cost (with battery)
        deg_cost = problem.c_deg_uah_kwh * (ch_val + dis_val) * dt
        total_cost_actual += imp_val * p_buy - exp_val * p_sell + deg_cost
        total_throughput_kwh += (ch_val + dis_val) * dt

    expected_profit = total_cost_baseline - total_cost_actual
    cycles_equiv = total_throughput_kwh / (2.0 * capacity)

    schedule = Schedule(
        strategy=problem.strategy_name,
        capacity_kwh=problem.capacity_kwh,
        created_at_sim=problem.timestamps[0],
        horizon_start=problem.timestamps[0],
        horizon_end=problem.timestamps[-1],
        items=items,
        expected_profit_uah=round(expected_profit, 2),
        solver_status="OPTIMAL",
        solve_time_ms=solve_time_ms,
    )

    logger.info(
        "MILP Schedule created: %d items, profit=%.2f UAH, cycles=%.3f, solve_time=%dms",
        len(items),
        expected_profit,
        cycles_equiv,
        solve_time_ms,
    )
    return schedule
