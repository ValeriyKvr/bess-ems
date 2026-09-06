"""Optimization strategies for BESS scheduling (SPEC §6.5, §6.7).

Strategy interface and implementations.
TOU_SIMPLE is the baseline rule-based strategy — no ML, no MILP.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ScheduleItem:
    """Single hourly slot in a BESS dispatch schedule."""

    ts: datetime
    setpoint_kw: float  # >0 = charge, <0 = discharge (SPEC §4.3 convention)
    reason: str = ""


@dataclass
class Schedule:
    """Full optimization schedule for a time horizon."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    strategy: str = ""
    capacity_kwh: float = 1000.0
    params: dict[str, Any] = field(default_factory=dict)
    created_at_sim: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    horizon_start: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    horizon_end: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    items: list[ScheduleItem] = field(default_factory=list)
    expected_profit_uah: float | None = None
    solver_status: str = "OK"
    solve_time_ms: int = 0

    def get_setpoint_for(self, ts: datetime) -> float | None:
        """Get scheduled setpoint_kw for a given simulation time.

        Matches the schedule item whose hour contains `ts`.
        """
        for item in self.items:
            item_hour_end = item.ts + timedelta(hours=1)
            if item.ts <= ts < item_hour_end:
                return item.setpoint_kw
        return None

    def to_db_dict(self) -> dict[str, Any]:
        """Serialize schedule for persistence in the schedules DB table."""
        strat_dict = {"name": self.strategy, "capacity_kwh": self.capacity_kwh}
        if self.params:
            strat_dict.update(self.params)
        return {
            "id": self.id,
            "created_at_sim": self.created_at_sim,
            "strategy": strat_dict,
            "horizon_start": self.horizon_start,
            "horizon_end": self.horizon_end,
            "expected_profit_uah": self.expected_profit_uah,
            "solver_status": self.solver_status,
            "solve_time_ms": self.solve_time_ms,
            "items": [
                {
                    "ts": item.ts.isoformat(),
                    "setpoint_kw": item.setpoint_kw,
                    "reason": item.reason,
                }
                for item in self.items
            ],
        }


@dataclass
class ScheduleContext:
    """Context data passed to a strategy for schedule building."""

    current_time: datetime
    horizon_start: datetime
    horizon_end: datetime
    soc_pct: float = 50.0
    soh_pct: float = 100.0
    capacity_kwh: float = 2000.0
    max_charge_kw: float = 500.0
    max_discharge_kw: float = 500.0
    soc_min_pct: float = 10.0
    soc_max_pct: float = 90.0
    prices: list[dict[str, Any]] = field(default_factory=list)
    # prices: list of {"ts": datetime, "price_dam": float, "price_buy": float, "price_sell": float}
    load_series: list[float] | None = None
    pv_series: list[float] | None = None
    dt_hours: float = 1.0
    peak_limit_kw: float | None = None
    reserve_soc_pct: float = 20.0
    export_allowed: bool = True
    c_deg_uah_kwh: float | None = None
    eff_charge: float = 0.95
    eff_discharge: float = 0.95


class Strategy(ABC):
    """Abstract base class for BESS optimization strategies."""

    name: str = "base"

    @abstractmethod
    def build_schedule(self, context: ScheduleContext) -> Schedule:
        """Build an optimized dispatch schedule given context data.

        Returns a Schedule with hourly setpoint assignments.
        """
        ...


class TouSimpleStrategy(Strategy):
    """Time-of-Use Simple baseline strategy (SPEC §6.7 — TOU_SIMPLE).

    Rule-based: charge in N cheapest hours, discharge in N most expensive hours.
    No ML, no MILP. Respects SoC min/max and capacity constraints.
    """

    name = "TOU_SIMPLE"

    def __init__(
        self,
        n_charge_hours: int = 4,
        n_discharge_hours: int = 4,
    ) -> None:
        self.n_charge_hours = n_charge_hours
        self.n_discharge_hours = n_discharge_hours

    def build_schedule(self, context: ScheduleContext) -> Schedule:
        """Build TOU_SIMPLE schedule: charge cheap, discharge expensive.

        Algorithm:
        1. Sort hourly prices by price_buy ascending.
        2. Select N cheapest hours for charging.
        3. Select N most expensive hours for discharging.
        4. Remaining hours → idle (setpoint = 0).
        5. Limit total energy transferred to SoC bounds.
        """
        import time

        t0 = time.monotonic()

        prices = context.prices
        if not prices:
            logger.warning("TOU_SIMPLE: No price data available — empty schedule.")
            return Schedule(
                strategy=self.name,
                capacity_kwh=context.capacity_kwh,
                created_at_sim=context.current_time,
                horizon_start=context.horizon_start,
                horizon_end=context.horizon_end,
                solver_status="NO_DATA",
            )

        # Sort prices ascending for charge selection, descending for discharge
        sorted_by_buy = sorted(prices, key=lambda p: p["price_buy"])

        current_energy_kwh = context.capacity_kwh * (context.soc_pct / 100.0)
        min_energy_kwh = context.capacity_kwh * (context.soc_min_pct / 100.0)
        max_energy_kwh = context.capacity_kwh * (context.soc_max_pct / 100.0)

        # Max energy we can charge or discharge in total
        charge_headroom_kwh = max_energy_kwh - current_energy_kwh
        discharge_headroom_kwh = current_energy_kwh - min_energy_kwh

        # Build charge/discharge hour sets
        charge_hours: set[str] = set()
        discharge_hours: set[str] = set()
        remaining_charge_kwh = charge_headroom_kwh
        remaining_discharge_kwh = discharge_headroom_kwh

        # Select cheapest hours for charging
        for p in sorted_by_buy[: self.n_charge_hours]:
            if remaining_charge_kwh <= 0:
                break
            ts_key = p["ts"].isoformat() if isinstance(p["ts"], datetime) else str(p["ts"])
            charge_hours.add(ts_key)
            remaining_charge_kwh -= min(context.max_charge_kw, remaining_charge_kwh)

        # Select most expensive hours for discharging
        sorted_by_sell_desc = sorted(
            prices, key=lambda p: p.get("price_sell", p["price_buy"]), reverse=True
        )
        for p in sorted_by_sell_desc[: self.n_discharge_hours]:
            ts_key = p["ts"].isoformat() if isinstance(p["ts"], datetime) else str(p["ts"])
            if ts_key in charge_hours:
                continue  # Don't charge and discharge in same hour
            if remaining_discharge_kwh <= 0:
                break
            discharge_hours.add(ts_key)
            remaining_discharge_kwh -= min(context.max_discharge_kw, remaining_discharge_kwh)

        # Build schedule items
        items: list[ScheduleItem] = []
        total_charge_energy = 0.0
        total_discharge_energy = 0.0

        for p in sorted(prices, key=lambda x: x["ts"]):
            ts = p["ts"] if isinstance(p["ts"], datetime) else datetime.fromisoformat(str(p["ts"]))
            ts_key = ts.isoformat()

            if ts_key in charge_hours:
                # Clamp charge to remaining headroom
                available = max_energy_kwh - (
                    current_energy_kwh + total_charge_energy - total_discharge_energy
                )
                power = min(context.max_charge_kw, max(0.0, available))
                total_charge_energy += power  # 1 hour * power_kw = energy_kwh
                items.append(
                    ScheduleItem(
                        ts=ts,
                        setpoint_kw=power,
                        reason=f"TOU charge (price_buy={p['price_buy']:.0f})",
                    )
                )
            elif ts_key in discharge_hours:
                # Clamp discharge to remaining headroom
                available = (
                    current_energy_kwh + total_charge_energy - total_discharge_energy
                ) - min_energy_kwh
                power = min(context.max_discharge_kw, max(0.0, available))
                total_discharge_energy += power
                items.append(
                    ScheduleItem(
                        ts=ts,
                        setpoint_kw=-power,  # Negative = discharge (SPEC §4.3)
                        reason=f"TOU discharge (price_sell={p.get('price_sell', p['price_buy']):.0f})",
                    )
                )
            else:
                items.append(
                    ScheduleItem(
                        ts=ts,
                        setpoint_kw=0.0,
                        reason="TOU idle",
                    )
                )

        # Estimate profit
        price_map = {
            (p["ts"].isoformat() if isinstance(p["ts"], datetime) else str(p["ts"])): p
            for p in prices
        }
        total_discharge_revenue = 0.0
        total_charge_cost = 0.0
        for item in items:
            item_price = price_map.get(item.ts.isoformat())
            if not item_price:
                continue
            if item.setpoint_kw < 0:
                total_discharge_revenue += (
                    abs(item.setpoint_kw)
                    * item_price.get("price_sell", item_price["price_buy"])
                    / 1000.0
                )
            elif item.setpoint_kw > 0:
                total_charge_cost += item.setpoint_kw * item_price["price_buy"] / 1000.0

        expected_profit = total_discharge_revenue - total_charge_cost

        solve_time_ms = int((time.monotonic() - t0) * 1000)

        schedule = Schedule(
            strategy=self.name,
            capacity_kwh=context.capacity_kwh,
            created_at_sim=context.current_time,
            horizon_start=context.horizon_start,
            horizon_end=context.horizon_end,
            items=items,
            expected_profit_uah=round(expected_profit, 2),
            solver_status="OPTIMAL",
            solve_time_ms=solve_time_ms,
        )

        logger.info(
            "TOU_SIMPLE schedule built: %d items, charge_hours=%d, discharge_hours=%d, "
            "expected_profit=%.2f UAH, solve_time=%dms",
            len(items),
            len(charge_hours),
            len(discharge_hours),
            expected_profit,
            solve_time_ms,
        )
        return schedule


class MilpStrategy(Strategy):
    """MILP-based mathematical optimization strategy (SPEC §6.7, §9)."""

    name = "ARBITRAGE"

    def __init__(
        self,
        strategy_name: str = "ARBITRAGE",
        w_arb: float = 1.0,
        w_peak: float = 0.0,
        w_reserve: float = 0.0,
        w_self: float = 0.0,
        peak_limit_kw: float | None = None,
        reserve_soc_pct: float = 20.0,
        dt_hours: float = 1.0,
        **kwargs: Any,
    ) -> None:
        self.strategy_name = strategy_name
        self.w_arb = w_arb
        self.w_peak = w_peak
        self.w_reserve = w_reserve
        self.w_self = w_self
        self.peak_limit_kw = peak_limit_kw
        self.reserve_soc_pct = reserve_soc_pct
        self.dt_hours = dt_hours

    def build_schedule(self, context: ScheduleContext) -> Schedule:
        from ems.optimization.milp import OptimizationProblem, solve

        prices = context.prices
        if not prices:
            logger.warning("MILP strategy: No price data available — empty schedule.")
            return Schedule(
                strategy=self.strategy_name,
                capacity_kwh=context.capacity_kwh,
                created_at_sim=context.current_time,
                horizon_start=context.horizon_start,
                horizon_end=context.horizon_end,
                solver_status="NO_DATA",
            )

        # Parse timestamps & prices
        timestamps = [
            p["ts"] if isinstance(p["ts"], datetime) else datetime.fromisoformat(str(p["ts"]))
            for p in prices
        ]
        price_buy_kwh = [p["price_buy"] / 1000.0 for p in prices]
        price_sell_kwh = [p.get("price_sell", p["price_buy"] * 0.9) / 1000.0 for p in prices]

        n = len(timestamps)
        load_kw = (
            context.load_series
            if context.load_series and len(context.load_series) == n
            else [100.0] * n
        )
        pv_kw = (
            context.pv_series if context.pv_series and len(context.pv_series) == n else [0.0] * n
        )

        peak_lim = self.peak_limit_kw or context.peak_limit_kw
        reserve_pct = context.reserve_soc_pct or self.reserve_soc_pct

        problem = OptimizationProblem(
            timestamps=timestamps,
            price_buy_uah_kwh=price_buy_kwh,
            price_sell_uah_kwh=price_sell_kwh,
            load_kw=load_kw,
            pv_kw=pv_kw,
            dt_hours=context.dt_hours or self.dt_hours,
            capacity_kwh=context.capacity_kwh,
            max_charge_kw=context.max_charge_kw,
            max_discharge_kw=context.max_discharge_kw,
            soc_min_pct=context.soc_min_pct,
            soc_max_pct=context.soc_max_pct,
            initial_soc_pct=context.soc_pct,
            peak_limit_kw=peak_lim,
            reserve_soc_pct=reserve_pct,
            export_allowed=context.export_allowed,
            w_arb=self.w_arb,
            w_peak=self.w_peak,
            w_reserve=self.w_reserve,
            w_self=self.w_self,
            strategy_name=self.strategy_name,
            c_deg_uah_kwh=context.c_deg_uah_kwh if context.c_deg_uah_kwh is not None else 1.25,
            eta_ch=context.eff_charge,
            eta_dis=context.eff_discharge,
        )

        return solve(problem)


class ArbitrageStrategy(MilpStrategy):
    """Arbitrage strategy: buy cheap / sell expensive to maximize net profit (SPEC §6.7)."""

    name = "ARBITRAGE"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            strategy_name="ARBITRAGE",
            w_arb=1.0,
            w_peak=0.0,
            w_reserve=0.0,
            w_self=0.0,
            **kwargs,
        )


class PeakShavingStrategy(MilpStrategy):
    """Peak shaving strategy: do not exceed peak_limit_kw import from grid (SPEC §6.7)."""

    name = "PEAK_SHAVING"

    def __init__(self, peak_limit_kw: float = 600.0, **kwargs: Any) -> None:
        super().__init__(
            strategy_name="PEAK_SHAVING",
            w_arb=0.2,
            w_peak=1.0,
            w_reserve=0.0,
            w_self=0.0,
            peak_limit_kw=peak_limit_kw,
            **kwargs,
        )


class SelfConsumptionStrategy(MilpStrategy):
    """Self consumption strategy: maximize absorption of PV surplus, minimize grid import (SPEC §6.7)."""

    name = "SELF_CONSUMPTION"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            strategy_name="SELF_CONSUMPTION",
            w_arb=0.5,
            w_peak=0.0,
            w_reserve=0.0,
            w_self=1.0,
            **kwargs,
        )


class BackupReserveStrategy(MilpStrategy):
    """Backup reserve strategy: always maintain reserve_soc_pct in case of blackout (SPEC §6.7)."""

    name = "BACKUP_RESERVE"

    def __init__(self, reserve_soc_pct: float = 30.0, **kwargs: Any) -> None:
        super().__init__(
            strategy_name="BACKUP_RESERVE",
            w_arb=0.5,
            w_peak=0.0,
            w_reserve=1.0,
            w_self=0.0,
            reserve_soc_pct=reserve_soc_pct,
            **kwargs,
        )


# Strategy registry
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "TOU_SIMPLE": TouSimpleStrategy,
    "ARBITRAGE": ArbitrageStrategy,
    "PEAK_SHAVING": PeakShavingStrategy,
    "SELF_CONSUMPTION": SelfConsumptionStrategy,
    "BACKUP_RESERVE": BackupReserveStrategy,
    "MILP": MilpStrategy,
}


def get_strategy(name: str, **kwargs: Any) -> Strategy:
    """Get a strategy instance by name from registry."""
    cls = STRATEGY_REGISTRY.get(name.upper())
    if cls is None:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(STRATEGY_REGISTRY.keys())}")
    return cls(**kwargs)
