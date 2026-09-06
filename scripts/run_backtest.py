"""1-Month ML + Optimization Backtest Benchmark (SPEC §8.4, §12, §15.3).

Evaluates the key acceptance criterion from SPEC §15.3:
  Over a 1-month synthetic scenario (seed=42), the system reports:
  - Costs without BESS
  - Costs with BESS
  - Net economic effect (savings)
  - Battery equivalent cycle count
  And verifies that:
  net_savings(MILP + LightGBM) > net_savings(TOU_SIMPLE)
  and approaches Perfect Foresight.
"""

# ruff: noqa: E402
import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure ems package is discoverable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMS_DIR = PROJECT_ROOT / "ems"
if str(EMS_DIR) not in sys.path:
    sys.path.insert(0, str(EMS_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ems.forecasting.features import build_features_and_targets, build_inference_features
from ems.forecasting.models.lightgbm_model import LightGbmModel
from ems.ingestion.generator import SyntheticDataGenerator
from ems.market.financials import compute_hourly_financials
from ems.market.simulator import MarketTariffs, calculate_buy_price, calculate_sell_price
from ems.optimization.milp import OptimizationProblem, solve
from ems.optimization.strategies import ScheduleContext, get_strategy

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run-backtest")


def simulate_schedule_execution(
    setpoints: list[float],
    timestamps: list[datetime],
    dam_prices: list[float],
    loads: list[float],
    pvs: list[float],
    tariffs: MarketTariffs,
    capacity_kwh: float = 2000.0,
    c_deg_uah_kwh: float = 1.25,
) -> dict[str, float]:
    """Simulate battery operation against actual market prices and facility consumption."""
    cost_baseline = 0.0
    cost_actual = 0.0
    revenue = 0.0
    degradation = 0.0
    net_savings = 0.0
    throughput_kwh = 0.0

    soc_min_kwh = capacity_kwh * 0.10
    soc_max_kwh = capacity_kwh * 0.90
    current_kwh = capacity_kwh * 0.50  # Starting at 50% SoC

    for t in range(len(timestamps)):
        sp = setpoints[t] if setpoints else 0.0
        load = loads[t]
        pv = pvs[t]
        dam = dam_prices[t]

        # Enforce physical battery SoC and inverter limits
        if sp > 0:
            # Charging: cannot exceed soc_max_kwh
            max_ch = max(0.0, (soc_max_kwh - current_kwh) / 0.95)
            ch = min(sp, max_ch)
            dis = 0.0
            current_kwh += ch * 0.95
        elif sp < 0:
            # Discharging: cannot drop below soc_min_kwh
            max_dis = max(0.0, (current_kwh - soc_min_kwh) * 0.95)
            dis = min(abs(sp), max_dis)
            ch = 0.0
            current_kwh -= dis / 0.95
        else:
            ch = 0.0
            dis = 0.0

        p_buy = calculate_buy_price(dam, tariffs)
        p_sell = calculate_sell_price(dam, tariffs)

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

        cost_baseline += fin.cost_baseline_uah
        cost_actual += fin.cost_actual_uah
        revenue += fin.revenue_uah
        degradation += fin.degradation_uah
        net_savings += fin.net_uah
        throughput_kwh += ch + dis

    cycles = throughput_kwh / (2.0 * capacity_kwh)

    return {
        "cost_baseline_uah": round(cost_baseline, 2),
        "cost_actual_uah": round(cost_actual - revenue, 2),
        "net_savings_uah": round(net_savings, 2),
        "cycles": round(cycles, 2),
        "throughput_kwh": round(throughput_kwh, 1),
    }


async def run_benchmark(
    days: int = 30,
    seed: int = 42,
    capacity_kwh: float = 2000.0,
    max_power_kw: float = 500.0,
) -> list[dict[str, Any]]:
    """Execute the multi-strategy 1-month benchmark."""
    print("=" * 86)
    print(
        f" BESS + EMS Benchmark: {days}-Day Simulation (seed={seed}, Capacity={capacity_kwh:.0f} kWh)"
    )
    print("=" * 86)

    # 1. Generate full dataset (90 days history for ML training + test period)
    start_dt = datetime(2025, 1, 13, 0, 0, 0, tzinfo=UTC)
    end_dt = start_dt + timedelta(days=days, hours=-1)
    train_start = start_dt - timedelta(days=90)

    print(
        f"\n1. Generating synthetic data (train: {train_start.date()} to {start_dt.date()}, test: {days} days)..."
    )
    gen = SyntheticDataGenerator(seed=seed)
    df_prices = gen.generate_dam_prices(train_start, end_dt)
    df_loads = gen.generate_site_load(train_start, end_dt)

    tariffs = MarketTariffs()

    # 2. Train LightGBM 24h forecasting models on historical data prior to test window
    print("2. Training LightGBM multi-horizon forecasting models (no future leakage)...")
    df_p = df_prices.rename(columns={"price_uah_mwh": "price"})
    X, Y, _ = build_features_and_targets(df_p, target_col="price", horizon_h=24)

    test_start_iso = start_dt.isoformat()
    train_mask = [ts.isoformat() < test_start_iso for ts in X.index]
    X_train, Y_train = X[train_mask], Y[train_mask]

    model_lgb = LightGbmModel(target="price", horizon_h=24, n_estimators=60)
    model_lgb.fit(X_train, Y_train)
    print("   LightGBM training complete.")

    # 3. Simulate day by day across test window
    print(f"3. Simulating daily schedules across {days} days...")
    test_timestamps: list[datetime] = []
    test_dam_prices: list[float] = []
    test_loads: list[float] = []
    test_pvs: list[float] = []

    setpoints_tou: list[float] = []
    setpoints_lgb: list[float] = []
    setpoints_perf: list[float] = []

    current_soc_tou = 50.0
    current_soc_lgb = 50.0
    current_soc_perf = 50.0

    for d in range(days):
        day_start = start_dt + timedelta(days=d)
        day_end = day_start + timedelta(hours=23)

        mask_p = (df_prices["ts"] >= day_start) & (df_prices["ts"] <= day_end)
        mask_l = (df_loads["ts"] >= day_start) & (df_loads["ts"] <= day_end)

        day_ts = list(df_prices[mask_p]["ts"])
        day_dam = list(df_prices[mask_p]["price_uah_mwh"])
        day_load = list(df_loads[mask_l]["load_kw"])
        day_pv = list(df_loads[mask_l]["pv_kw"])

        test_timestamps.extend(day_ts)
        test_dam_prices.extend(day_dam)
        test_loads.extend(day_load)
        test_pvs.extend(day_pv)

        # Prepare tariffs data for day
        day_tariffs = []
        for ts, dam in zip(day_ts, day_dam, strict=True):
            day_tariffs.append(
                {
                    "ts": ts,
                    "price_dam": dam,
                    "price_buy": calculate_buy_price(dam, tariffs),
                    "price_sell": calculate_sell_price(dam, tariffs),
                }
            )

        # --- A. TOU_SIMPLE Strategy ---
        ctx_tou = ScheduleContext(
            current_time=day_start,
            horizon_start=day_start,
            horizon_end=day_end,
            soc_pct=current_soc_tou,
            capacity_kwh=capacity_kwh,
            max_charge_kw=max_power_kw,
            max_discharge_kw=max_power_kw,
            soc_min_pct=10.0,
            soc_max_pct=90.0,
            prices=day_tariffs,
            load_series=day_load,
            pv_series=day_pv,
            export_allowed=tariffs.export_allowed,
        )
        strat_tou = get_strategy("TOU_SIMPLE")
        sch_tou = strat_tou.build_schedule(ctx_tou)
        for item in sch_tou.items:
            setpoints_tou.append(item.setpoint_kw)
            if item.setpoint_kw > 0:
                current_soc_tou += (item.setpoint_kw * 0.95 / capacity_kwh) * 100.0
            elif item.setpoint_kw < 0:
                current_soc_tou -= (abs(item.setpoint_kw) / (0.95 * capacity_kwh)) * 100.0
            current_soc_tou = max(10.0, min(90.0, current_soc_tou))

        # --- B. MILP + LightGBM Forecast ---
        # Generate 24h forecast available at gate closure
        hist_df = df_p[df_p["ts"] <= day_start]
        x_infer = build_inference_features(hist_df, target_col="price")
        pred_prices = model_lgb.predict(x_infer)["value"][0]

        p_buy_lgb = [calculate_buy_price(p, tariffs) / 1000.0 for p in pred_prices]
        p_sell_lgb = [calculate_sell_price(p, tariffs) / 1000.0 for p in pred_prices]

        prob_lgb = OptimizationProblem(
            timestamps=day_ts,
            price_buy_uah_kwh=p_buy_lgb,
            price_sell_uah_kwh=p_sell_lgb,
            load_kw=day_load,
            pv_kw=day_pv,
            capacity_kwh=capacity_kwh,
            max_charge_kw=max_power_kw,
            max_discharge_kw=max_power_kw,
            initial_soc_pct=current_soc_lgb,
            soc_end_target_pct=15.0,
            c_deg_uah_kwh=1.25,
            export_allowed=tariffs.export_allowed,
        )
        sch_lgb = solve(prob_lgb)
        for it in sch_lgb.items:
            setpoints_lgb.append(it.setpoint_kw)
            if it.setpoint_kw > 0:
                current_soc_lgb += (it.setpoint_kw * 0.95 / capacity_kwh) * 100.0
            elif it.setpoint_kw < 0:
                current_soc_lgb -= (abs(it.setpoint_kw) / (0.95 * capacity_kwh)) * 100.0
            current_soc_lgb = max(10.0, min(90.0, current_soc_lgb))

        # --- C. Perfect Foresight (Theoretical Ceiling) ---
        p_buy_true = [calculate_buy_price(p, tariffs) / 1000.0 for p in day_dam]
        p_sell_true = [calculate_sell_price(p, tariffs) / 1000.0 for p in day_dam]

        prob_perf = OptimizationProblem(
            timestamps=day_ts,
            price_buy_uah_kwh=p_buy_true,
            price_sell_uah_kwh=p_sell_true,
            load_kw=day_load,
            pv_kw=day_pv,
            capacity_kwh=capacity_kwh,
            max_charge_kw=max_power_kw,
            max_discharge_kw=max_power_kw,
            initial_soc_pct=current_soc_perf,
            soc_end_target_pct=15.0,
            c_deg_uah_kwh=1.25,
            export_allowed=tariffs.export_allowed,
        )
        sch_perf = solve(prob_perf)
        for it in sch_perf.items:
            setpoints_perf.append(it.setpoint_kw)
            if it.setpoint_kw > 0:
                current_soc_perf += (it.setpoint_kw * 0.95 / capacity_kwh) * 100.0
            elif it.setpoint_kw < 0:
                current_soc_perf -= (abs(it.setpoint_kw) / (0.95 * capacity_kwh)) * 100.0
            current_soc_perf = max(10.0, min(90.0, current_soc_perf))

    # 4. Evaluate Financials
    print("\n4. Evaluating economic performance against true market prices...")
    res_nobess = simulate_schedule_execution(
        [], test_timestamps, test_dam_prices, test_loads, test_pvs, tariffs, capacity_kwh
    )
    res_tou = simulate_schedule_execution(
        setpoints_tou, test_timestamps, test_dam_prices, test_loads, test_pvs, tariffs, capacity_kwh
    )
    res_lgb = simulate_schedule_execution(
        setpoints_lgb, test_timestamps, test_dam_prices, test_loads, test_pvs, tariffs, capacity_kwh
    )
    res_perf = simulate_schedule_execution(
        setpoints_perf,
        test_timestamps,
        test_dam_prices,
        test_loads,
        test_pvs,
        tariffs,
        capacity_kwh,
    )

    baseline_cost = res_nobess["cost_baseline_uah"]
    perf_savings = res_perf["net_savings_uah"]

    results = [
        {
            "strategy": "Без BESS (Baseline)",
            "cost_without_bess": baseline_cost,
            "cost_with_bess": baseline_cost,
            "net_savings_uah": 0.0,
            "cycles": 0.0,
            "pct_ideal": 0.0,
        },
        {
            "strategy": "TOU_SIMPLE (Rule)",
            "cost_without_bess": baseline_cost,
            "cost_with_bess": res_tou["cost_actual_uah"],
            "net_savings_uah": res_tou["net_savings_uah"],
            "cycles": res_tou["cycles"],
            "pct_ideal": round(
                (res_tou["net_savings_uah"] / perf_savings * 100.0) if perf_savings > 0 else 0, 1
            ),
        },
        {
            "strategy": "MILP + LightGBM",
            "cost_without_bess": baseline_cost,
            "cost_with_bess": res_lgb["cost_actual_uah"],
            "net_savings_uah": res_lgb["net_savings_uah"],
            "cycles": res_lgb["cycles"],
            "pct_ideal": round(
                (res_lgb["net_savings_uah"] / perf_savings * 100.0) if perf_savings > 0 else 0, 1
            ),
        },
        {
            "strategy": "Perfect Foresight",
            "cost_without_bess": baseline_cost,
            "cost_with_bess": res_perf["cost_actual_uah"],
            "net_savings_uah": perf_savings,
            "cycles": res_perf["cycles"],
            "pct_ideal": 100.0,
        },
    ]

    # 5. Print Results Table
    print("\n" + "=" * 96)
    print(
        f"{'Стратегія':<20} | {'Без BESS (грн)':<15} | {'З BESS (грн)':<15} | {'Чистий ефект':<14} | {'Цикли':<6} | {'% Ідеалу':<8}"
    )
    print("-" * 96)
    for r in results:
        print(
            f"{r['strategy']:<20} | "
            f"{r['cost_without_bess']:>13,.2f} | "
            f"{r['cost_with_bess']:>13,.2f} | "
            f"{r['net_savings_uah']:>12,.2f} | "
            f"{r['cycles']:>6.2f} | "
            f"{r['pct_ideal']:>7.1f}%"
        )
    print("=" * 96)

    # 6. Verify DoD Criterion #3
    savings_lgb = res_lgb["net_savings_uah"]
    savings_tou = res_tou["net_savings_uah"]
    diff = savings_lgb - savings_tou
    pct_gain = (diff / abs(savings_tou) * 100.0) if savings_tou != 0 else 0.0

    print(
        f"\nЕкономічна перевага MILP+LightGBM над TOU_SIMPLE: +{diff:,.2f} грн (+{pct_gain:.1f}%)"
    )
    print(
        f"Досягнуто {results[2]['pct_ideal']:.1f}% від теоретичної верхньої межі (Perfect Foresight)."
    )

    if savings_lgb >= savings_tou:
        print("\n[PASS] Критерій приймання SPEC §15.3 успішно виконано:")
        print("       net_savings(MILP + LightGBM) >= net_savings(TOU_SIMPLE)")
    else:
        print("\n[FAIL] Критерій SPEC §15.3 не виконано!")
        sys.exit(1)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="1-Month BESS Backtest Benchmark (SPEC §15.3)")
    parser.add_argument(
        "--days", type=int, default=30, help="Simulation duration in days (default: 30)"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducibility (default: 42)"
    )
    args = parser.parse_args()

    asyncio.run(run_benchmark(days=args.days, seed=args.seed))


if __name__ == "__main__":
    main()
