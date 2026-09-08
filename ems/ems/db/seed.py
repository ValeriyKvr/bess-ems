"""Database initialization and seeding routines (SPEC §3.4, §6.1, §15.7).

Guarantees turnkey zero-touch startup: creates tables if they do not exist
and seeds default configuration and 2 years of synthetic energy market data.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ems.api.settings import SECTION_MODELS
from ems.db.models import Base, DamPrice, MlModel, Setting, SiteLoad
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


async def seed_ml_models_if_empty(session: AsyncSession) -> None:
    """Scan models directory and register trained baseline models in ml_models table."""
    models_root = Path(__file__).resolve().parent.parent.parent / "models"
    if not models_root.exists():
        return

    for meta_file in models_root.glob("*/*/*/metadata.json"):
        try:
            with open(meta_file, encoding="utf-8") as f:
                meta = json.load(f)
            name = meta.get("name")
            version = meta.get("version")
            target = meta.get("target")
            metrics = meta.get("metrics")
            if not (name and version and target):
                continue

            artifact_dir = meta_file.parent
            trained_at_str = meta.get("trained_at")
            trained_at = (
                datetime.fromisoformat(trained_at_str) if trained_at_str else datetime.now(UTC)
            )

            stmt = (
                insert(MlModel)
                .values(
                    name=name,
                    version=version,
                    target=target,
                    trained_at=trained_at,
                    metrics=metrics,
                    artifact_path=str(artifact_dir),
                    is_active=(name == "lightgbm"),
                )
                .on_conflict_do_nothing(index_elements=["name", "version"])
            )
            await session.execute(stmt)
            logger.info("Discovered and registered ML model %s:%s for %s", name, version, target)
        except Exception as e:
            logger.warning("Failed to auto-register ML model from %s: %s", meta_file, e)

    await session.commit()


async def seed_september_2026_enterprise_data(session: AsyncSession) -> None:
    """Seed real Ukrainian DAM market prices and enterprise site load for 01-09 September 2026."""
    from datetime import timedelta

    import numpy as np

    start_sept = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end_sept = datetime(2026, 9, 9, 23, 0, 0, tzinfo=UTC)

    # 1. Check if September 2026 DAM prices exist
    p_count = (
        await session.execute(
            select(func.count())
            .select_from(DamPrice)
            .where(DamPrice.ts >= start_sept, DamPrice.ts <= end_sept)
        )
    ).scalar_one()

    if p_count < 216:
        logger.info("Seeding September 2026 real DAM prices (current count: %d)...", p_count)
        candidates = [
            Path(__file__).resolve().parent.parent.parent / "data" / "samples" / "dam_prices_september_2026.csv",
            Path(__file__).resolve().parent.parent / "ingestion" / "dam_prices_september_2026.csv",
            Path(__file__).resolve().parent.parent.parent.parent / "data" / "samples" / "dam_prices_september_2026.csv",
        ]
        csv_file = next((p for p in candidates if p.exists()), None)
        if csv_file:
            import pandas as pd

            df = pd.read_csv(csv_file)
            records = []
            for _, r in df.iterrows():
                dt = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))
                records.append({
                    "ts": dt,
                    "price_uah_mwh": float(r["price_uah_mwh"]),
                    "volume_mwh": float(r.get("volume_mwh", 1500.0)),
                })
            for i in range(0, len(records), 500):
                batch = records[i : i + 500]
                stmt = insert(DamPrice).values(batch).on_conflict_do_nothing()
                await session.execute(stmt)
            logger.info("Inserted %d September 2026 real DAM prices.", len(records))

    # 2. Check if September 2026 site load exists
    l_count = (
        await session.execute(
            select(func.count())
            .select_from(SiteLoad)
            .where(SiteLoad.ts >= start_sept, SiteLoad.ts <= end_sept)
        )
    ).scalar_one()

    if l_count < 216:
        logger.info("Seeding September 2026 enterprise site load (current count: %d)...", l_count)
        records = []
        cur = start_sept
        np.random.seed(42)
        while cur <= end_sept:
            h = cur.hour
            # Enterprise load: 200-300 kW daytime (07-23), 0-100 kW nighttime (23-07)
            if 7 <= h < 23:
                base_load = 250.0 + float(np.random.uniform(-40.0, 45.0))
            else:
                base_load = 50.0 + float(np.random.uniform(-35.0, 45.0))
            base_load = max(5.0, base_load)

            # Solar PV: 50-150 kW peak daytime
            if 8 <= h <= 17:
                solar_frac = np.sin(np.pi * (h - 7) / 11)
                pv = max(0.0, float(140.0 * solar_frac + np.random.uniform(-10.0, 10.0)))
            else:
                pv = 0.0

            records.append({
                "ts": cur,
                "load_kw": round(base_load, 2),
                "pv_kw": round(pv, 2),
            })
            cur += timedelta(hours=1)

        for i in range(0, len(records), 500):
            batch = records[i : i + 500]
            stmt = insert(SiteLoad).values(batch).on_conflict_do_nothing()
            await session.execute(stmt)
        logger.info("Inserted %d September 2026 enterprise site load records.", len(records))

    await session.commit()


async def ensure_db_initialized_and_seeded(session: AsyncSession, seed: int = 42) -> bool:
    """Create all tables if not exist and seed default settings, models & synthetic data."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema validated / created successfully.")
    except Exception as e:
        logger.warning("Schema creation warning (may already exist): %s", e)

    seeded = await seed_database_if_empty(session, seed=seed)
    await seed_september_2026_enterprise_data(session)
    await seed_ml_models_if_empty(session)
    return seeded

