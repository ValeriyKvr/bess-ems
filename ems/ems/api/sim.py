"""Simulation control API endpoints (SPEC §11)."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/sim", tags=["Simulation Control"])


class SimControlRequest(BaseModel):
    """Payload for POST /api/sim/control."""

    action: str = Field(
        ...,
        description="Control action: 'start', 'pause', 'resume', 'step', 'reset', 'speed', 'jump'",
    )
    speed: int | None = Field(default=None, description="Clock speed: 0, 1, 10, 60, 600, 3600")
    scenario: str | None = Field(
        default=None,
        description="Scenario for reset: 'default', 'winter_week', 'summer_month', 'year_2025'",
    )
    jump_to: str | None = Field(default=None, description="Target ISO 8601 timestamp for jump")
    step_seconds: float = Field(
        default=60.0, description="Step duration in seconds for action='step'"
    )


@router.post("/control")
async def control_simulation(payload: SimControlRequest) -> dict[str, Any]:
    """Control simulation clock speed, pause, step, reset, and jumps."""
    from ems.main import app_state

    if not app_state.clock:
        raise HTTPException(status_code=500, detail="Simulation clock not initialized.")

    clock = app_state.clock
    action = payload.action.lower()

    if action in ("start", "resume"):
        clock.resume(payload.speed)
    elif action == "pause":
        clock.pause()
    elif action == "step":
        clock.step(payload.step_seconds)
    elif action == "reset":
        clock.reset(scenario=payload.scenario or "default", custom_time=payload.jump_to)
    elif action == "speed":
        if payload.speed is None:
            raise HTTPException(status_code=400, detail="Must provide 'speed' for action='speed'")
        clock.set_speed(payload.speed)
    elif action == "jump":
        if not payload.jump_to:
            raise HTTPException(status_code=400, detail="Must provide 'jump_to' for action='jump'")
        clock.jump_to(payload.jump_to)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{payload.action}'. Allowed: start, pause, resume, step, reset, speed, jump",
        )

    # Broadcast updated clock state over MQTT immediately
    if app_state.mqtt and app_state.mqtt.is_connected:
        app_state.mqtt.publish_clock(clock.to_dict())

    return {
        "status": "success",
        "action": action,
        "clock": clock.to_dict(),
    }
