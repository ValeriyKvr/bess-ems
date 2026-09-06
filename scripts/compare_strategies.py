"""Compare BESS operational strategies on a 1-week test scenario (SPEC §14, §15).

Verifies the acceptance criterion:
  net_uah(ARBITRAGE + MILP) >= net_uah(TOU_SIMPLE)
for a 1-week simulation with seed=42.
"""

# ruff: noqa: E402
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Ensure ems is discoverable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMS_DIR = PROJECT_ROOT / "ems"
if str(EMS_DIR) not in sys.path:
    sys.path.insert(0, str(EMS_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ems.ingestion.generator import SyntheticDataGenerator
from ems.market.financials import compute_hourly_financials
from ems.market.simulator import MarketTariffs, calculate_buy_price, calculate_sell_price
from ems.optimization.strategies import ScheduleContext, get_strategy


def run_strategy_simulation(
    strategy_name: str,
    timestamps: list[datetime],
    dam_prices: list[float],
    loads: list[float],
    pvs: list[float],
    tariffs: MarketTariffs,
    capacity_kwh: float = 2000.0,
    max_power_kw: float = 500.0,
    c_deg_uah_kwh: float = 1.25,
) -> dict:
    """Simulate a strategy over the horizon and compute cumulative financial metrics."""
    # Prepare tariff list
    tariffs_data = []
    for ts, dam in zip(timestamps, dam_prices, strict=True):
        p_buy = calculate_buy_price(dam, tariffs)
        p_sell = calculate_sell_price(dam, tariffs)
        tariffs_data.append(
            {
                "ts": ts,
                "price_dam": dam,
                "price_buy": p_buy,
                "price_sell": p_sell,
            }
        )

    # Build schedule day by day (24-hour rolling blocks)
    total_hours = len(timestamps)
    days_count = total_hours // 24

    all_setpoints: list[float] = []

    current_soc = 50.0

    for day in range(days_count):
        idx_start = day * 24
        idx_end = idx_start + 24
        day_tariffs = tariffs_data[idx_start:idx_end]
        day_loads = loads[idx_start:idx_end]
        day_pvs = pvs[idx_start:idx_end]

        context = ScheduleContext(
            current_time=timestamps[idx_start],
            horizon_start=timestamps[idx_start],
            horizon_end=timestamps[idx_end - 1],
            soc_pct=current_soc,
            capacity_kwh=capacity_kwh,
            max_charge_kw=max_power_kw,
            max_discharge_kw=max_power_kw,
            soc_min_pct=10.0,
            soc_max_pct=90.0,
            prices=day_tariffs,
            load_series=day_loads,
            pv_series=day_pvs,
            export_allowed=tariffs.export_allowed,
        )

        strat = get_strategy(strategy_name)
        schedule = strat.build_schedule(context)

        for item in schedule.items:
            all_setpoints.append(item.setpoint_kw)
            # Track SoC roughly for next day context
            if item.setpoint_kw > 0:
                current_soc += (item.setpoint_kw * 0.95 / capacity_kwh) * 100.0
            elif item.setpoint_kw < 0:
                current_soc -= (abs(item.setpoint_kw) / (0.95 * capacity_kwh)) * 100.0
            current_soc = max(10.0, min(90.0, current_soc))

    # Evaluate financials hour by hour
    total_baseline_cost = 0.0
    total_actual_cost = 0.0
    total_revenue = 0.0
    total_degradation = 0.0
    total_net = 0.0
    total_throughput = 0.0

    for t in range(total_hours):
        sp = all_setpoints[t]
        ch = max(0.0, sp)
        dis = max(0.0, -sp)
        load = loads[t]
        pv = pvs[t]
        p_buy = tariffs_data[t]["price_buy"]
        p_sell = tariffs_data[t]["price_sell"]

        fin = compute_hourly_financials(
            ts=timestamps[t],
            load_kwh=load,
            pv_kwh=pv,
            charge_kwh=ch,
            discharge_kwh=dis,
            price_buy_uah_mwh=p_buy,
            price_sell_uah_mwh=p_sell,
            c_deg_uah_kwh=c_deg_uah_kwh,
        )

        total_baseline_cost += fin.cost_baseline_uah
        total_actual_cost += fin.cost_actual_uah
        total_revenue += fin.revenue_uah
        total_degradation += fin.degradation_uah
        total_net += fin.net_uah
        total_throughput += ch + dis

    cycles = total_throughput / (2.0 * capacity_kwh)

    return {
        "strategy": strategy_name,
        "cost_baseline_uah": round(total_baseline_cost, 2),
        "cost_actual_uah": round(total_actual_cost, 2),
        "revenue_uah": round(total_revenue, 2),
        "degradation_uah": round(total_degradation, 2),
        "net_uah": round(total_net, 2),
        "cycles": round(cycles, 2),
    }


def main() -> None:
    print("=" * 80)
    print(" BESS Strategy Benchmark: 1-Week Test Scenario (seed=42)")
    print("=" * 80)

    # 1. Generate 1 week of synthetic data (168 hours)
    start_dt = datetime(2025, 1, 13, 0, 0, 0, tzinfo=UTC)
    end_dt = start_dt + timedelta(hours=167)
    gen = SyntheticDataGenerator(seed=42)

    df_prices = gen.generate_dam_prices(start_dt, end_dt)
    df_loads = gen.generate_site_load(start_dt, end_dt)

    timestamps = list(df_prices["ts"])
    dam_prices = list(df_prices["price_uah_mwh"])
    loads = list(df_loads["load_kw"])
    pvs = list(df_loads["pv_kw"])

    tariffs = MarketTariffs()

    # 2. Run benchmark on TOU_SIMPLE and ARBITRAGE (MILP)
    strategies_to_test = ["TOU_SIMPLE", "ARBITRAGE"]
    results = []

    for strat_name in strategies_to_test:
        print(f"Running simulation for {strat_name}...")
        res = run_strategy_simulation(
            strategy_name=strat_name,
            timestamps=timestamps,
            dam_prices=dam_prices,
            loads=loads,
            pvs=pvs,
            tariffs=tariffs,
        )
        results.append(res)

    # 3. Print Results Table
    print("\n" + "-" * 88)
    print(
        f"{'Стратегія':<18} | {'Базові (грн)':<14} | {'Фактичні (грн)':<14} | {'Деградація':<12} | {'Net Ефект':<12} | {'Цикли':<6}"
    )
    print("-" * 88)

    for r in results:
        print(
            f"{r['strategy']:<18} | "
            f"{r['cost_baseline_uah']:>12,.2f} | "
            f"{r['cost_actual_uah']:>12,.2f} | "
            f"{r['degradation_uah']:>10,.2f} | "
            f"{r['net_uah']:>10,.2f} | "
            f"{r['cycles']:>6.2f}"
        )
    print("-" * 88)

    # 4. Check acceptance criterion
    res_tou = next(r for r in results if r["strategy"] == "TOU_SIMPLE")
    res_milp = next(r for r in results if r["strategy"] == "ARBITRAGE")

    diff = res_milp["net_uah"] - res_tou["net_uah"]
    pct = (diff / abs(res_tou["net_uah"])) * 100.0 if res_tou["net_uah"] != 0 else 0.0

    print(f"\nПеревага MILP ARBITRAGE над TOU_SIMPLE: +{diff:,.2f} грн (+{pct:.1f}%)")

    if res_milp["net_uah"] >= res_tou["net_uah"]:
        print(
            "\n[SUCCESS] Критерій готовності Етапу 5 виконано: net_uah(ARBITRAGE) >= net_uah(TOU_SIMPLE)"
        )
        sys.exit(0)
    else:
        print("\n[FAIL] Критерій не виконано: net_uah(ARBITRAGE) < net_uah(TOU_SIMPLE)")
        sys.exit(1)


if __name__ == "__main__":
    main()
