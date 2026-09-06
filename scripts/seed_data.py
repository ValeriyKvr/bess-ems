"""Seed database with 2 years of synthetic energy market data and default settings (SPEC §12)."""

# ruff: noqa: E402
import asyncio
import logging
import sys
from pathlib import Path

# Add project roots to sys.path so scripts can import ems modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMS_DIR = PROJECT_ROOT / "ems"
if str(EMS_DIR) not in sys.path:
    sys.path.insert(0, str(EMS_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from ems.db.seed import ensure_db_initialized_and_seeded
from ems.db.session import async_session_factory, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed-data")


async def main() -> None:
    """CLI script entrypoint."""
    logger.info("Starting database auto-initialization and seeding...")
    async with async_session_factory() as session:
        await ensure_db_initialized_and_seeded(session)
    await engine.dispose()
    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
