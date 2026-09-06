"""Health check and status API routes (SPEC §11)."""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ems.db.session import get_db

router = APIRouter(tags=["Health & Status"])


@router.get("/health")
async def get_health(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Basic health check verifying DB connection and app liveness."""
    db_ok = False
    try:
        result = await db.execute(text("SELECT 1"))
        db_ok = result.scalar() == 1
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "service": "ems-core",
        "database": db_ok,
    }


@router.get("/status")
async def get_system_status(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Comprehensive system status for dashboard and monitoring (SPEC §11)."""
    # Import app-level singletons or dependencies lazily to avoid cyclic imports
    from ems.main import app_state

    clock_data = app_state.clock.to_dict() if app_state.clock else {}
    mqtt_connected = app_state.mqtt.is_connected if app_state.mqtt else False
    bess_telemetry = app_state.mqtt.latest_bess_telemetry if app_state.mqtt else {}

    return {
        "status": "ONLINE",
        "clock": clock_data,
        "mqtt_connected": mqtt_connected,
        "bess_connected": len(bess_telemetry) > 0,
        "active_bess": list(bess_telemetry.keys()),
        "stage": "Stage 0: Skeleton",
    }
