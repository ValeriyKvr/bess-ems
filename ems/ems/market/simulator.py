"""Market Simulator modeling Ukrainian Day-Ahead Market rules (SPEC §3, §6.2)."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ems.db.models import DamPrice
from ems.ingestion.generator import SyntheticDataGenerator

logger = logging.getLogger(__name__)


class MarketTariffs(BaseModel):
    """Tariffs structure for Ukrainian commercial electricity consumers (SPEC §3.1)."""

    transmission_tariff_uah_mwh: float = Field(
        default=528.57, description="Ukrenergo transmission tariff in UAH/MWh"
    )
    distribution_tariff_uah_mwh: float = Field(
        default=1250.00, description="DSO distribution tariff (Class 2) in UAH/MWh"
    )
    supplier_margin_uah_mwh: float = Field(
        default=150.00, description="Electricity supplier service margin in UAH/MWh"
    )
    export_price_coeff: float = Field(
        default=0.90, description="Discount coefficient for surplus energy feed-in"
    )
    export_allowed: bool = Field(
        default=True, description="Whether export of surplus energy to grid is permitted"
    )
    price_cap_min: float = Field(default=10.0, description="Regulatory lower price cap (UAH/MWh)")
    price_cap_max: float = Field(default=9000.0, description="Regulatory upper price cap (UAH/MWh)")


def calculate_buy_price(price_dam_uah_mwh: float, tariffs: MarketTariffs) -> float:
    """Calculate effective electricity purchase price per MWh (SPEC §3.1).

    Price_buy = Price_DAM + Transmission + Distribution + Supplier_margin
    """
    total = (
        price_dam_uah_mwh
        + tariffs.transmission_tariff_uah_mwh
        + tariffs.distribution_tariff_uah_mwh
        + tariffs.supplier_margin_uah_mwh
    )
    return round(total, 2)


def calculate_sell_price(price_dam_uah_mwh: float, tariffs: MarketTariffs) -> float:
    """Calculate effective surplus energy export price per MWh (SPEC §3.1).

    Price_sell = Price_DAM * export_price_coeff (0 if export not allowed)
    """
    if not tariffs.export_allowed:
        return 0.0
    return round(price_dam_uah_mwh * tariffs.export_price_coeff, 2)


class MarketSimulator:
    """Manages Day-Ahead Market calendar, gate closures, and tariff settlements."""

    def __init__(self, tariffs: MarketTariffs | None = None, seed: int = 42) -> None:
        self.tariffs = tariffs or MarketTariffs()
        self.generator = SyntheticDataGenerator(seed=seed)

    async def publish_d_plus_one_prices(
        self,
        current_sim_dt: datetime,
        session: AsyncSession,
    ) -> int:
        """Publish actual clearing prices for day D+1 at 13:00 simulation time (SPEC §3.2, §6.2).

        Returns number of published hourly records.
        """
        target_date = current_sim_dt.date() + timedelta(days=1)
        d_start = datetime(
            target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=UTC
        )
        d_end = datetime(target_date.year, target_date.month, target_date.day, 23, 0, 0, tzinfo=UTC)

        logger.info(
            "Market simulator publishing DAM prices for Day D+1: %s (at %s)",
            target_date,
            current_sim_dt,
        )

        # Check if prices already exist in database
        stmt = select(DamPrice).where(DamPrice.ts >= d_start, DamPrice.ts <= d_end)
        result = await session.execute(stmt)
        existing = list(result.scalars().all())

        if existing:
            # Update published_at to current simulation timestamp
            upd_stmt = (
                update(DamPrice)
                .where(DamPrice.ts >= d_start, DamPrice.ts <= d_end)
                .values(published_at=current_sim_dt)
            )
            await session.execute(upd_stmt)
            await session.commit()
            logger.info(
                "Updated published_at for %d existing DAM records for %s",
                len(existing),
                target_date,
            )
            return len(existing)
        else:
            # Generate and insert synthetic prices for D+1
            df = self.generator.generate_dam_prices(
                start_dt=d_start,
                end_dt=d_end,
                price_cap_min=self.tariffs.price_cap_min,
                price_cap_max=self.tariffs.price_cap_max,
            )
            for _, row in df.iterrows():
                record = DamPrice(
                    ts=row["ts"],
                    zone=row["zone"],
                    price_uah_mwh=row["price_uah_mwh"],
                    published_at=current_sim_dt,
                    source="synthetic",
                )
                session.add(record)
            await session.commit()
            logger.info("Generated and published %d new DAM records for %s", len(df), target_date)
            return len(df)

    async def get_hourly_tariffs(
        self,
        start_dt: datetime,
        end_dt: datetime,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Retrieve DAM prices and compute effective buy/sell prices for a time window."""
        stmt = (
            select(DamPrice)
            .where(DamPrice.ts >= start_dt, DamPrice.ts <= end_dt)
            .order_by(DamPrice.ts)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

        res: list[dict[str, Any]] = []
        for r in rows:
            p_buy = calculate_buy_price(r.price_uah_mwh, self.tariffs)
            p_sell = calculate_sell_price(r.price_uah_mwh, self.tariffs)
            res.append(
                {
                    "ts": r.ts,
                    "price_dam": r.price_uah_mwh,
                    "price_buy": p_buy,
                    "price_sell": p_sell,
                    "published_at": r.published_at,
                }
            )
        return res
