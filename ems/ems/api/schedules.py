"""Schedule endpoints (SPEC §11 — GET /api/schedules)."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from ems.db.models import Schedule as ScheduleModel
from ems.db.session import async_session_factory

logger = logging.getLogger(__name__)
router = APIRouter(tags=["schedules"])


@router.get("/schedules")
async def list_schedules(
    from_dt: str | None = Query(None, alias="from", description="ISO 8601 start filter"),
    to_dt: str | None = Query(None, alias="to", description="ISO 8601 end filter"),
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """List optimization schedules, optionally filtered by time range."""
    async with async_session_factory() as session:
        stmt = select(ScheduleModel).order_by(ScheduleModel.created_at_sim.desc()).limit(limit)

        if from_dt:
            dt_from = datetime.fromisoformat(from_dt.replace("Z", "+00:00"))
            stmt = stmt.where(ScheduleModel.horizon_start >= dt_from)
        if to_dt:
            dt_to = datetime.fromisoformat(to_dt.replace("Z", "+00:00"))
            stmt = stmt.where(ScheduleModel.horizon_end <= dt_to)

        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    return [
        {
            "id": r.id,
            "strategy": r.strategy,
            "created_at_sim": r.created_at_sim.isoformat() if r.created_at_sim else None,
            "horizon_start": r.horizon_start.isoformat() if r.horizon_start else None,
            "horizon_end": r.horizon_end.isoformat() if r.horizon_end else None,
            "expected_profit_uah": r.expected_profit_uah,
            "solver_status": r.solver_status,
            "solve_time_ms": r.solve_time_ms,
            "items_count": len(r.items) if r.items else 0,
        }
        for r in rows
    ]


@router.get("/schedules/{schedule_id}")
async def get_schedule(schedule_id: str) -> dict[str, Any]:
    """Get a specific schedule by ID with full item details."""
    async with async_session_factory() as session:
        stmt = select(ScheduleModel).where(ScheduleModel.id == schedule_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

    if not row:
        return {"error": "Schedule not found", "id": schedule_id}

    return {
        "id": row.id,
        "strategy": row.strategy,
        "created_at_sim": row.created_at_sim.isoformat() if row.created_at_sim else None,
        "horizon_start": row.horizon_start.isoformat() if row.horizon_start else None,
        "horizon_end": row.horizon_end.isoformat() if row.horizon_end else None,
        "expected_profit_uah": row.expected_profit_uah,
        "solver_status": row.solver_status,
        "solve_time_ms": row.solve_time_ms,
        "items": row.items or [],
    }
