"""Database initialization and seeding routines (SPEC §3.4, §6.1, §15.7).

Guarantees turnkey zero-touch startup: creates tables if they do not exist
and seeds default configuration and 2 years of synthetic energy market data.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ems.api.settings import SECTION_MODELS
from ems.db.models import Base, DamPrice, Setting, SiteLoad
from ems.db.session import engine
from ems.ingestion.generator import SyntheticDataGenerator

logger = logging.getLogger("ems-db-seed")


async def seed_default_settings(session: AsyncSession) -> None:
    """Ensure default settings exist in the settings table."""
    logger.info("Verifying default settings...")
    now = datetime.now(UTC)
    for section_name, model_cls in SECTION_MODELS.items():
        stmt = select(Setting).where(Setting.key == section_name)
        res = await session.execute(stmt)
        if not res.scalar_one_or_none():
            default_val = model_cls().model_dump()
            ins = insert(Setting).values(key=section_name, value=default_val, updated_at=now)
            await session.execute(ins)
            logger.info("Initialized default settings for '%s'", section_name)
    await session.commit()


async def seed_database_if_empty(session: AsyncSession, seed: int = 42) -> bool:
    """Populate database with 2 years of synthetic data if tables are empty."""
    # Check if data exists
    price_count = (await session.execute(select(func.count()).select_from(DamPrice))).scalar_one()
    load_count = (await session.execute(select(func.count()).select_from(SiteLoad))).scalar_one()

    await seed_default_settings(session)

    if price_count > 0 and load_count > 0:
        logger.info(
            "Database already contains data (%d prices, %d loads). Skipping synthetic data generation.",
            price_count,
            load_count,
        )
        return False

    start_dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    end_dt = datetime(2026, 3, 31, 23, 0, 0, tzinfo=UTC)
    logger.info(
        "Seeding synthetic data from %s to %s (seed=%d)...", start_dt.date(), end_dt.date(), seed
    )

    gen = SyntheticDataGenerator(seed=seed)

    # 1. Generate & insert DAM prices
    df_prices = gen.generate_dam_prices(start_dt, end_dt)
    price_records = df_prices.to_dict(orient="records")
    batch_size = 2000
    for i in range(0, len(price_records), batch_size):
        batch = price_records[i : i + batch_size]
        stmt = insert(DamPrice).values(batch).on_conflict_do_nothing()
        await session.execute(stmt)
    logger.info("Inserted %d DAM price records.", len(price_records))

    # 2. Generate & insert site load
    df_load = gen.generate_site_load(start_dt, end_dt)
    load_records = df_load.to_dict(orient="records")
    for i in range(0, len(load_records), batch_size):
        batch = load_records[i : i + batch_size]
        stmt = insert(SiteLoad).values(batch).on_conflict_do_nothing()
        await session.execute(stmt)
    logger.info("Inserted %d Site load records.", len(load_records))

    await session.commit()
    logger.info("Database seeding completed successfully.")
    return True


async def ensure_db_initialized_and_seeded(session: AsyncSession, seed: int = 42) -> bool:
    """Create all tables if not exist and seed default settings & synthetic data."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema validated / created successfully.")
    except Exception as e:
        logger.warning("Schema creation warning (may already exist): %s", e)

    return await seed_database_if_empty(session, seed=seed)
