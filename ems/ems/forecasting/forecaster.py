"""Forecaster interface and baseline naive implementation (SPEC §6.3, §8).

Predicts Day-Ahead Market clearing prices and facility load.
NaiveForecaster uses "same as yesterday" (or synthetic generation fallback) as baseline for comparison.
Advanced ML (LightGBM, LSTM) will implement the Forecaster interface in Stage 6.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ems.db.models import DamPrice, SiteLoad

logger = logging.getLogger(__name__)


class Forecaster(ABC):
    """Abstract base class for time-series forecasting."""

    name: str = "base"
    version: str = "0.1.0"

    @abstractmethod
    async def forecast_price(
        self,
        start_dt: datetime,
        horizon_h: int,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Forecast DAM clearing prices for the given horizon."""
        ...

    @abstractmethod
    async def forecast_load(
        self,
        start_dt: datetime,
        horizon_h: int,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Forecast facility load for the given horizon."""
        ...


class NaiveForecaster(Forecaster):
    """Naive forecaster: 'same as yesterday' baseline (SPEC §6.3, §8).

    For hour t of tomorrow, returns the value observed at the same hour yesterday.
    If yesterday's data is not in database, falls back to synthetic generator.
    """

    name = "NAIVE_YESTERDAY"
    version = "1.0.0"

    async def forecast_price(
        self,
        start_dt: datetime,
        horizon_h: int,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Forecast prices by taking values from 24 hours prior."""
        res: list[dict[str, Any]] = []

        # Query past 24-48h prices
        hist_start = start_dt - timedelta(hours=24)
        hist_end = start_dt + timedelta(hours=horizon_h) - timedelta(hours=24)

        stmt = (
            select(DamPrice)
            .where(DamPrice.ts >= hist_start, DamPrice.ts <= hist_end)
            .order_by(DamPrice.ts)
        )
        db_res = await session.execute(stmt)
        hist_map = {r.ts.hour: r.price_uah_mwh for r in db_res.scalars().all()}

        for h in range(horizon_h):
            step_ts = start_dt + timedelta(hours=h)
            hour_of_day = step_ts.hour
            predicted_price = hist_map.get(hour_of_day, 4500.0)

            res.append(
                {
                    "ts": step_ts,
                    "price_dam": predicted_price,
                    "p10": predicted_price * 0.85,
                    "p90": predicted_price * 1.15,
                    "model": self.name,
                }
            )

        logger.info("Naive price forecast created: %d steps for %s", len(res), start_dt.date())
        return res

    async def forecast_load(
        self,
        start_dt: datetime,
        horizon_h: int,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Forecast site load by taking values from 24 hours prior."""
        res: list[dict[str, Any]] = []

        hist_start = start_dt - timedelta(hours=24)
        hist_end = start_dt + timedelta(hours=horizon_h) - timedelta(hours=24)

        stmt = (
            select(SiteLoad)
            .where(SiteLoad.ts >= hist_start, SiteLoad.ts <= hist_end)
            .order_by(SiteLoad.ts)
        )
        db_res = await session.execute(stmt)
        hist_map = {r.ts.hour: (r.load_kw, r.pv_kw) for r in db_res.scalars().all()}

        for h in range(horizon_h):
            step_ts = start_dt + timedelta(hours=h)
            hour_of_day = step_ts.hour
            load_val, pv_val = hist_map.get(hour_of_day, (150.0, 0.0))

            res.append(
                {
                    "ts": step_ts,
                    "load_kw": load_val,
                    "pv_kw": pv_val,
                    "model": self.name,
                }
            )

        return res
