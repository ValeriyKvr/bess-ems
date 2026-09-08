"""Simulation control API endpoints (SPEC §11)."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/sim", tags=["Simulation Control"])


class SimControlRequest(BaseModel):
    """Payload for POST /api/sim/control."""

    action: str = Field(
        ...,
        description="Control action: 'start', 'pause', 'resume', 'step', 'reset', 'speed', 'jump', 'loop'",
    )
    speed: int | None = Field(default=None, description="Clock speed: 0, 1, 10, 60, 600, 3600")
    scenario: str | None = Field(
        default=None,
        description="Scenario for reset: 'default', 'september_2026', 'march_baseline', 'winter_week'",
    )
    jump_to: str | None = Field(default=None, description="Target ISO 8601 timestamp for jump")
    step_seconds: float = Field(
        default=60.0, description="Step duration in seconds for action='step'"
    )
    loop_enabled: bool | None = Field(default=None, description="Enable or disable cyclic loop")
    loop_start: str | None = Field(default=None, description="Start time for cyclic loop")
    loop_end: str | None = Field(default=None, description="End time for cyclic loop")
    loop_days: int | None = Field(default=None, description="Loop duration in days")


class ApplyTemplateRequest(BaseModel):
    """Payload for POST /api/sim/templates/{template_id}/apply."""

    loop_days: int | None = Field(default=None, ge=1, le=365, description="Number of days to loop")


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
    elif action in ("loop", "set_loop"):
        clock.set_loop(
            enabled=payload.loop_enabled if payload.loop_enabled is not None else True,
            start=payload.loop_start,
            end=payload.loop_end,
            duration_days=payload.loop_days,
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{payload.action}'. Allowed: start, pause, resume, step, reset, speed, jump, loop",
        )

    # Broadcast updated clock state over MQTT immediately
    if app_state.mqtt and app_state.mqtt.is_connected:
        app_state.mqtt.publish_clock(clock.to_dict())

    return {
        "status": "success",
        "action": action,
        "clock": clock.to_dict(),
    }


@router.get("/templates")
async def list_templates() -> list[dict[str, Any]]:
    """List all available simulation templates (built-in and custom)."""
    from ems.core.templates import get_all_templates

    templates = get_all_templates()
    return [t.model_dump() for t in templates]


@router.get("/templates/{template_id}")
async def get_single_template(template_id: str) -> dict[str, Any]:
    """Retrieve details of a specific simulation template."""
    from ems.core.templates import get_template

    template = get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found.")
    return template.model_dump()


@router.post("/templates")
async def create_or_update_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Create or update a custom simulation template."""
    from ems.core.templates import SimulationTemplate, save_template

    try:
        tmpl = SimulationTemplate(**payload)
        saved = save_template(tmpl)
        return {"status": "saved", "template": saved.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid template format: {e}") from e


@router.post("/templates/{template_id}/apply")
async def apply_simulation_template(
    template_id: str,
    payload: ApplyTemplateRequest | None = None,
) -> dict[str, Any]:
    """Apply a simulation template, configuring battery, strategy, clock loop and Day 1 schedule."""
    from ems.core.templates import apply_template

    loop_days = payload.loop_days if payload else None
    try:
        result = await apply_template(template_id=template_id, loop_days=loop_days)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to apply template: {e}") from e


@router.get("/templates/{template_id}/report")
async def get_template_report(
    template_id: str,
    days: int | None = None,
) -> dict[str, Any]:
    """Generate analytical performance and savings report for the template."""
    from ems.core.templates import compute_template_report

    try:
        report = await compute_template_report(template_id=template_id, days=days)
        return report
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {e}") from e


