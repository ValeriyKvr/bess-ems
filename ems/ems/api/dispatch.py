"""Dispatch log, events, and BESS command endpoints (SPEC §11)."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ems.db.models import DispatchLog
from ems.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dispatch"])


@router.get("/dispatch/log")
async def get_dispatch_log(
    from_dt: str | None = Query(None, alias="from", description="ISO 8601 start"),
    to_dt: str | None = Query(None, alias="to", description="ISO 8601 end"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(50, ge=1, le=1000, description="Items per page"),
    reason: str | None = Query(None, description="Filter by reason keyword"),
    override: bool | None = Query(None, description="Filter by override flag"),
    schedule_id: str | None = Query(None, description="Filter by schedule ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve paginated dispatcher decision log entries with filters (SPEC §10.1(6), §11)."""
    session = db
    stmt = select(DispatchLog)

    if from_dt:
        dt_from = datetime.fromisoformat(from_dt.replace("Z", "+00:00"))
        stmt = stmt.where(DispatchLog.ts >= dt_from)
    if to_dt:
        dt_to = datetime.fromisoformat(to_dt.replace("Z", "+00:00"))
        stmt = stmt.where(DispatchLog.ts <= dt_to)
    if reason:
        stmt = stmt.where(DispatchLog.reason.ilike(f"%{reason}%"))
    if override is not None:
        stmt = stmt.where(DispatchLog.override == override)
    if schedule_id:
        stmt = stmt.where(DispatchLog.schedule_id == schedule_id)

    # Count total matching rows
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_res = await session.execute(count_stmt)
    total_count = total_res.scalar_one() or 0

    # Paginate
    offset = (page - 1) * limit
    stmt = stmt.order_by(DispatchLog.ts.desc()).offset(offset).limit(limit)

    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    items = [
        {
            "ts": r.ts.isoformat() if r.ts else None,
            "setpoint_kw": r.setpoint_kw,
            "actual_kw": r.actual_kw,
            "reason": r.reason,
            "schedule_id": r.schedule_id,
            "override": r.override,
        }
        for r in rows
    ]

    return {
        "items": items,
        "total": total_count,
        "page": page,
        "limit": limit,
    }


@router.get("/events")
async def get_events(
    from_dt: str | None = Query(None, alias="from", description="ISO 8601 start"),
    to_dt: str | None = Query(None, alias="to", description="ISO 8601 end"),
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Retrieve dispatcher events (alarms, mode changes).

    Events are stored in-memory in the Dispatcher instance — we expose them from app_state.
    Falls back to an empty list if dispatcher is not initialized.
    """
    try:
        from ems.main import app_state

        if app_state.dispatcher:
            events = app_state.dispatcher.event_log
            # Apply time filtering
            filtered = events
            if from_dt:
                dt_from = datetime.fromisoformat(from_dt.replace("Z", "+00:00"))
                filtered = [
                    e
                    for e in filtered
                    if datetime.fromisoformat(e["ts"].replace("Z", "+00:00")) >= dt_from
                ]
            if to_dt:
                dt_to = datetime.fromisoformat(to_dt.replace("Z", "+00:00"))
                filtered = [
                    e
                    for e in filtered
                    if datetime.fromisoformat(e["ts"].replace("Z", "+00:00")) <= dt_to
                ]
            return filtered[-limit:]
        return []
    except Exception:
        return []


class BessCommandRequest(BaseModel):
    """BESS control command request body."""

    cmd: str  # reset_alarm | standby | start


@router.post("/bess/command")
async def send_bess_command(req: BessCommandRequest) -> dict[str, Any]:
    """Send a control command to BESS via MQTT (SPEC §11)."""
    try:
        from ems.main import app_state

        if not app_state.mqtt or not app_state.mqtt.is_connected:
            return {"status": "error", "message": "MQTT not connected"}

        bess_id = app_state.settings.bess_id
        app_state.mqtt.publish_command(bess_id, {"cmd": req.cmd})
        logger.info("Sent BESS command '%s' to %s", req.cmd, bess_id)
        return {"status": "ok", "cmd": req.cmd, "bess_id": bess_id}
    except Exception as e:
        logger.error("Failed to send BESS command: %s", e)
        return {"status": "error", "message": str(e)}


class FaultInjectionRequest(BaseModel):
    """Payload for fault injection (SPEC §10.1(2))."""

    type: str  # comms_dropout | force_overheat | soc_noise | power_limit_50 | clear_all
    duration_s: float = 60.0
    enabled: bool = True
    bess_id: str | None = None


@router.post("/bess/fault-injection")
async def inject_bess_fault(req: FaultInjectionRequest) -> dict[str, Any]:
    """Inject a simulated fault into BESS for testing fail-safes (SPEC §10.1(2))."""
    try:
        from ems.main import app_state

        if not app_state.mqtt or not app_state.mqtt.is_connected:
            return {"status": "error", "message": "MQTT not connected"}

        bess_id = req.bess_id or app_state.settings.bess_id
        payload: dict[str, Any] = {
            "cmd": "fault_injection",
            "type": req.type,
            "duration_s": req.duration_s,
            "enabled": req.enabled,
        }
        app_state.mqtt.publish_command(bess_id, payload)
        logger.warning("Injected fault '%s' into BESS %s", req.type, bess_id)
        return {"status": "ok", "type": req.type, "fault_type": req.type, "bess_id": bess_id}
    except Exception as e:
        logger.error("Failed to inject fault: %s", e)
        return {"status": "error", "message": str(e)}
