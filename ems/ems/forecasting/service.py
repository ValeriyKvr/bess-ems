"""Online forecasting service for preliminary schedule generation and accuracy evaluation (SPEC §6.3, §8)."""

import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ems.core.config import EmsSettings
from ems.db.models import DamPrice, DispatchLog, Forecast, MlModel
from ems.forecasting.features import build_inference_features
from ems.forecasting.models.base import ForecastModel
from ems.forecasting.models.naive import NaiveModel
from ems.forecasting.train import get_model_instance
from ems.ingestion.generator import SyntheticDataGenerator

logger = logging.getLogger(__name__)


async def load_active_model(target: str = "price", session: Any = None) -> ForecastModel:
    """Load the currently active model from the ML model registry or fallback to NaiveModel."""
    if session is not None:
        stmt = (
            select(MlModel)
            .where(MlModel.target == target, MlModel.is_active.is_(True))
            .order_by(desc(MlModel.trained_at))
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row and row.artifact_path:
            artifact_dir = Path(row.artifact_path)
            if artifact_dir.exists():
                try:
                    model = get_model_instance(row.name, target=target, horizon_h=24)
                    model.load(artifact_dir)
                    model.version = row.version
                    logger.info(
                        "Loaded active model %s:%s from %s", row.name, row.version, artifact_dir
                    )
                    return model
                except Exception as e:
                    logger.warning("Failed to load active model artifact %s: %s", artifact_dir, e)

    # Fallback to NaiveModel
    logger.info("Using baseline NaiveModel for %s forecasting", target)
    return NaiveModel(target=target, horizon_h=24)


async def generate_day_ahead_forecast(
    target_date: date,
    sim_dt: datetime,
    session: Any,
) -> list[dict[str, Any]]:
    """Generate 24h forecast for D+1 at 11:00 and persist to forecasts table (SPEC §6.3)."""
    horizon_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=UTC)

    # 1. Load active model
    model = await load_active_model(target="price", session=session)

    # 2. Get past 350 hours of price data before horizon_start
    hist_start = horizon_start - timedelta(hours=350)
    stmt = (
        select(DamPrice)
        .where(DamPrice.ts >= hist_start, DamPrice.ts < horizon_start)
        .order_by(DamPrice.ts)
    )
    rows = (await session.execute(stmt)).scalars().all()

    if len(rows) >= 336:
        df_hist = pd.DataFrame([{"ts": r.ts, "price": r.price_uah_mwh} for r in rows])
    else:
        # Generate synthetic history up to cutoff_ts to ensure sufficient lag windows
        gen = SyntheticDataGenerator(seed=42)
        df_synth = gen.generate_dam_prices(hist_start, horizon_start - timedelta(hours=1))
        df_hist = df_synth.rename(columns={"price_uah_mwh": "price"})

    # 3. Construct inference features
    X_inf = build_inference_features(df_hist, target_col="price")

    # 4. Predict
    preds = model.predict(X_inf)
    val_arr = preds["value"][0]
    p10_arr = preds["p10"][0] if preds.get("p10") is not None else val_arr * 0.85
    p90_arr = preds["p90"][0] if preds.get("p90") is not None else val_arr * 1.15

    results: list[dict[str, Any]] = []

    # 5. Persist to forecasts table
    for h in range(24):
        step_ts = horizon_start + timedelta(hours=h)
        val = float(val_arr[h])
        p10_val = float(p10_arr[h])
        p90_val = float(p90_arr[h])

        stmt = (
            pg_insert(Forecast)
            .values(
                ts=step_ts,
                target="price",
                model_name=model.name,
                model_version=getattr(model, "version", "v1.0.0"),
                created_at_sim=sim_dt,
                horizon_h=h + 1,
                value=val,
                p10=p10_val,
                p90=p90_val,
            )
            .on_conflict_do_update(
                index_elements=["ts", "target", "model_name", "model_version", "created_at_sim"],
                set_={
                    "value": val,
                    "p10": p10_val,
                    "p90": p90_val,
                    "horizon_h": h + 1,
                },
            )
        )
        await session.execute(stmt)

        results.append(
            {
                "ts": step_ts,
                "price_dam": val,
                "p10": p10_val,
                "p90": p90_val,
                "model": model.name,
                "version": getattr(model, "version", "v1.0.0"),
            }
        )

    await session.commit()
    logger.info("Persisted 24 forecasts for %s generated by %s", target_date, model.name)
    return results


async def evaluate_d_plus_one_forecast(
    target_date: date,
    sim_dt: datetime,
    session: Any,
    settings: EmsSettings | None = None,
) -> dict[str, float] | None:
    """Evaluate 11:00 forecast accuracy vs actual published DAM prices at 13:00 (SPEC §6.3)."""
    horizon_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=UTC)
    horizon_end = horizon_start + timedelta(hours=23)

    # 1. Fetch latest forecasts for target_date
    stmt_f = (
        select(Forecast)
        .where(
            Forecast.target == "price",
            Forecast.ts >= horizon_start,
            Forecast.ts <= horizon_end,
        )
        .order_by(Forecast.ts, desc(Forecast.created_at_sim))
    )
    f_rows = (await session.execute(stmt_f)).scalars().all()

    # Deduplicate keeping latest created_at_sim per hour
    latest_forecasts: dict[int, float] = {}
    for r in f_rows:
        h = r.ts.hour
        if h not in latest_forecasts:
            latest_forecasts[h] = r.value

    # 2. Fetch actual DAM prices
    stmt_p = (
        select(DamPrice)
        .where(
            DamPrice.ts >= horizon_start,
            DamPrice.ts <= horizon_end,
        )
        .order_by(DamPrice.ts)
    )
    p_rows = (await session.execute(stmt_p)).scalars().all()
    actual_prices: dict[int, float] = {r.ts.hour: r.price_uah_mwh for r in p_rows}

    if len(latest_forecasts) < 24 or len(actual_prices) < 24:
        logger.warning(
            "Incomplete data for forecast evaluation: %d forecasts, %d actuals for %s",
            len(latest_forecasts),
            len(actual_prices),
            target_date,
        )
        return None

    y_pred = np.array([latest_forecasts[h] for h in range(24)], dtype=np.float64)
    y_true = np.array([actual_prices[h] for h in range(24)], dtype=np.float64)

    abs_err = np.abs(y_true - y_pred)
    mae = float(np.mean(abs_err))
    mape = float(np.mean(abs_err / np.maximum(y_true, 10.0)) * 100.0)
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

    threshold = settings.forecast_error_threshold if settings else 25.0
    logger.info(
        "Forecast evaluation for %s: MAE=%.2f, MAPE=%.2f%%, RMSE=%.2f (threshold=%.1f%%)",
        target_date,
        mae,
        mape,
        rmse,
        threshold,
    )

    # 3. Log warning in dispatch_log if MAPE > threshold (SPEC §6.3)
    if mape > threshold:
        warning_msg = f"WARNING: Forecast MAPE for {target_date} is {mape:.1f}%, exceeding threshold {threshold:.1f}%"
        logger.warning(warning_msg)
        dispatch_entry = DispatchLog(
            ts=sim_dt,
            setpoint_kw=0.0,
            actual_kw=0.0,
            reason=warning_msg,
            schedule_id=None,
            override=False,
        )
        session.add(dispatch_entry)
        await session.commit()

    return {
        "mae": round(mae, 2),
        "mape": round(mape, 2),
        "rmse": round(rmse, 2),
    }
