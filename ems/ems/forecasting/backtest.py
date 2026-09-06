"""Economic backtesting pipeline: MILP with model forecasts vs Perfect Foresight (SPEC §8.4).

Demonstrates that higher ML forecast accuracy (LightGBM vs Naive) translates directly into
higher realized financial profit approaching theoretical perfect foresight.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from ems.forecasting.features import build_features_and_targets
from ems.forecasting.models.lightgbm_model import LightGbmModel
from ems.forecasting.models.naive import NaiveModel
from ems.ingestion.generator import SyntheticDataGenerator
from ems.market.financials import compute_hourly_financials
from ems.market.simulator import MarketTariffs, calculate_buy_price, calculate_sell_price
from ems.optimization.milp import OptimizationProblem, solve

logger = logging.getLogger("forecasting-backtest")


def simulate_schedule_financials(
    schedule_setpoints: list[float],
    timestamps: list[datetime],
    true_dam_prices: list[float],
    true_loads: list[float],
    true_pvs: list[float],
    tariffs: MarketTariffs,
    c_deg: float = 1.25,
) -> float:
    """Evaluate financial performance of planned schedule executed against TRUE actual market prices."""
    total_net = 0.0
    for t in range(len(timestamps)):
        sp = schedule_setpoints[t]
        ch = max(0.0, sp)
        dis = max(0.0, -sp)

        p_buy = calculate_buy_price(true_dam_prices[t], tariffs)
        p_sell = calculate_sell_price(true_dam_prices[t], tariffs)

        fin = compute_hourly_financials(
            ts=timestamps[t],
            load_kwh=true_loads[t],
            pv_kwh=true_pvs[t],
            charge_kwh=ch,
            discharge_kwh=dis,
            price_buy_uah_mwh=p_buy,
            price_sell_uah_mwh=p_sell,
            c_deg_uah_kwh=c_deg,
        )
        total_net += fin.net_uah

    return round(total_net, 2)


async def run_economic_backtest(
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Run backtest comparing Naive, LightGBM, and Perfect Foresight on test horizon."""
    if start_dt is None:
        start_dt = datetime(2025, 1, 13, 0, 0, 0, tzinfo=UTC)
    if end_dt is None:
        end_dt = start_dt + timedelta(days=7, hours=-1)  # 1 week = 168 hours

    # 1. Generate full dataset (1 year history for training + test week)
    train_start = start_dt - timedelta(days=90)
    gen = SyntheticDataGenerator(seed=seed)
    df_prices = gen.generate_dam_prices(train_start, end_dt)
    df_loads = gen.generate_site_load(train_start, end_dt)

    tariffs = MarketTariffs()

    # Build features & train models
    df_prices = df_prices.rename(columns={"price_uah_mwh": "price"})
    X, Y, _ = build_features_and_targets(df_prices, target_col="price", horizon_h=24)

    # Train cutoff before test week
    test_start_iso = start_dt.isoformat()
    train_mask = [ts.isoformat() < test_start_iso for ts in X.index]

    X_train, Y_train = X[train_mask], Y[train_mask]

    # Initialize and fit models
    model_naive = NaiveModel(target="price", horizon_h=24)
    model_lgb = LightGbmModel(target="price", horizon_h=24, n_estimators=60)

    model_naive.fit(X_train, Y_train)
    model_lgb.fit(X_train, Y_train)

    # 2. Daily simulation over test week (7 days)
    days_count = 7
    naive_setpoints: list[float] = []
    lgb_setpoints: list[float] = []
    perfect_setpoints: list[float] = []

    test_timestamps = []
    test_true_prices = []
    test_loads = []
    test_pvs = []

    for d in range(days_count):
        day_start = start_dt + timedelta(days=d)
        day_end = day_start + timedelta(hours=23)

        # Slice true values for this day
        mask_p = (df_prices["ts"] >= day_start) & (df_prices["ts"] <= day_end)
        mask_l = (df_loads["ts"] >= day_start) & (df_loads["ts"] <= day_end)

        day_prices_true = list(df_prices[mask_p]["price"])
        day_ts = list(df_prices[mask_p]["ts"])
        day_loads_true = list(df_loads[mask_l]["load_kw"])
        day_pvs_true = list(df_loads[mask_l]["pv_kw"])

        test_timestamps.extend(day_ts)
        test_true_prices.extend(day_prices_true)
        test_loads.extend(day_loads_true)
        test_pvs.extend(day_pvs_true)

        # History up to day_start (11:00 prior or day_start)
        hist_df = df_prices[df_prices["ts"] <= day_start]
        from ems.forecasting.features import build_inference_features

        x_infer = build_inference_features(hist_df, target_col="price")

        pred_naive = model_naive.predict(x_infer)["value"][0]
        pred_lgb = model_lgb.predict(x_infer)["value"][0]

        # A. Naive Schedule
        p_buy_naive = [calculate_buy_price(p, tariffs) / 1000.0 for p in pred_naive]
        p_sell_naive = [calculate_sell_price(p, tariffs) / 1000.0 for p in pred_naive]
        prob_naive = OptimizationProblem(
            timestamps=day_ts,
            price_buy_uah_kwh=p_buy_naive,
            price_sell_uah_kwh=p_sell_naive,
            load_kw=day_loads_true,
            pv_kw=day_pvs_true,
        )
        sch_naive = solve(prob_naive)
        naive_setpoints.extend([it.setpoint_kw for it in sch_naive.items])

        # B. LightGBM Schedule
        p_buy_lgb = [calculate_buy_price(p, tariffs) / 1000.0 for p in pred_lgb]
        p_sell_lgb = [calculate_sell_price(p, tariffs) / 1000.0 for p in pred_lgb]
        prob_lgb = OptimizationProblem(
            timestamps=day_ts,
            price_buy_uah_kwh=p_buy_lgb,
            price_sell_uah_kwh=p_sell_lgb,
            load_kw=day_loads_true,
            pv_kw=day_pvs_true,
        )
        sch_lgb = solve(prob_lgb)
        lgb_setpoints.extend([it.setpoint_kw for it in sch_lgb.items])

        # C. Perfect Foresight Schedule (true prices)
        p_buy_true = [calculate_buy_price(p, tariffs) / 1000.0 for p in day_prices_true]
        p_sell_true = [calculate_sell_price(p, tariffs) / 1000.0 for p in day_prices_true]
        prob_perf = OptimizationProblem(
            timestamps=day_ts,
            price_buy_uah_kwh=p_buy_true,
            price_sell_uah_kwh=p_sell_true,
            load_kw=day_loads_true,
            pv_kw=day_pvs_true,
        )
        sch_perf = solve(prob_perf)
        perfect_setpoints.extend([it.setpoint_kw for it in sch_perf.items])

    # 3. Evaluate Realized Profit for all 3 approaches against true actuals
    net_naive = simulate_schedule_financials(
        naive_setpoints, test_timestamps, test_true_prices, test_loads, test_pvs, tariffs
    )
    net_lgb = simulate_schedule_financials(
        lgb_setpoints, test_timestamps, test_true_prices, test_loads, test_pvs, tariffs
    )
    net_perfect = simulate_schedule_financials(
        perfect_setpoints, test_timestamps, test_true_prices, test_loads, test_pvs, tariffs
    )

    results = [
        {
            "model": "Naive (Вчора)",
            "net_uah": net_naive,
            "pct_of_ideal": round((net_naive / net_perfect * 100.0) if net_perfect > 0 else 0, 1),
            "description": "Baseline персистенція",
        },
        {
            "model": "LightGBM",
            "net_uah": net_lgb,
            "pct_of_ideal": round((net_lgb / net_perfect * 100.0) if net_perfect > 0 else 0, 1),
            "description": "24 Direct Models + Quantiles",
        },
        {
            "model": "Perfect Foresight (Ідеал)",
            "net_uah": net_perfect,
            "pct_of_ideal": 100.0,
            "description": "Теоретична верхня межа (істинні ціни)",
        },
    ]

    return results


def main() -> None:
    print("=" * 80)
    print(" ML Economic Backtest: Profit Realization vs Perfect Foresight (SPEC §8.4)")
    print("=" * 80)

    results = asyncio.run(run_economic_backtest())

    print("\n" + "-" * 75)
    print(f"{'Модель':<28} | {'Чистий прибуток (грн)':<22} | {'% від Ідеалу':<14}")
    print("-" * 75)
    for r in results:
        print(f"{r['model']:<28} | {r['net_uah']:>20,.2f} | {r['pct_of_ideal']:>12.1f}%")
    print("-" * 75)


if __name__ == "__main__":
    main()
