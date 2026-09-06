"""System configuration and settings API endpoints (SPEC §11)."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ems.db.models import Setting
from ems.db.session import get_db
from ems.market.simulator import MarketTariffs

router = APIRouter(prefix="/settings", tags=["Settings"])


class BatterySettings(BaseModel):
    """BESS hardware and operating settings (SPEC §5.1)."""

    capacity_kwh: float = Field(default=1000.0, ge=10.0, le=100000.0)
    power_max_kw: float = Field(default=500.0, ge=5.0, le=50000.0)
    soc_min_pct: float = Field(default=10.0, ge=0.0, le=50.0)
    soc_max_pct: float = Field(default=90.0, ge=50.0, le=100.0)
    soc_hard_min_pct: float = Field(default=5.0, ge=0.0, le=20.0)
    soc_hard_max_pct: float = Field(default=97.0, ge=80.0, le=100.0)
    eff_charge: float = Field(default=0.95, gt=0.5, le=1.0)
    eff_discharge: float = Field(default=0.95, gt=0.5, le=1.0)
    self_discharge_pct_day: float = Field(default=0.1, ge=0.0, le=5.0)
    aux_load_kw: float = Field(default=3.0, ge=0.0, le=50.0)
    ramp_rate_kw_s: float = Field(default=50.0, ge=1.0, le=1000.0)
    temp_ambient_c: float = Field(default=25.0, ge=-30.0, le=60.0)
    temp_max_c: float = Field(default=45.0, ge=30.0, le=80.0)
    cycle_life: float = Field(default=6000.0, ge=500.0, le=30000.0)
    capex_uah: float = Field(default=15000000.0, ge=0.0)
    initial_soc_pct: float = Field(default=50.0, ge=0.0, le=100.0)


class StrategySettings(BaseModel):
    """Energy dispatch strategy parameters (SPEC §6.7, §9)."""

    active_strategy: str = Field(
        default="ARBITRAGE"
    )  # ARBITRAGE, PEAK_SHAVING, SELF_CONSUMPTION, TOU_SIMPLE
    w_arbitrage: float = Field(default=1.0, ge=0.0, le=10.0)
    w_peak: float = Field(default=1.0, ge=0.0, le=10.0)
    w_reserve: float = Field(default=1.0, ge=0.0, le=10.0)
    reserve_soc_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    peak_limit_kw: float = Field(default=500.0, ge=10.0)
    degradation_cost_weight: float = Field(default=1.0, ge=0.0, le=2.0)


class SimulationSettings(BaseModel):
    """Simulation run parameters."""

    default_scenario: str = Field(default="default")
    default_speed: int = Field(default=60)
    seed: int = Field(default=42)
    pv_enabled: bool = Field(default=True)
    pv_peak_kw: float = Field(default=200.0, ge=0.0)


class EmsCoreSettings(BaseModel):
    """EMS Core algorithm parameters."""

    soc_tolerance_pct: float = Field(default=3.0, ge=0.5, le=20.0)
    optimization_horizon_h: int = Field(default=24, ge=12, le=72)
    optimization_step_min: int = Field(default=60)  # 60 or 15


SECTION_MODELS: dict[str, type[BaseModel]] = {
    "battery": BatterySettings,
    "market": MarketTariffs,
    "strategy": StrategySettings,
    "simulation": SimulationSettings,
    "ems": EmsCoreSettings,
}

RESTART_REQUIRED_FIELDS: dict[str, list[str]] = {
    "battery": ["capacity_kwh", "power_max_kw", "initial_soc_pct"],
    "simulation": ["seed", "default_scenario"],
    "strategy": [],
    "market": [],
    "ems": [],
}


@router.get("/{section}/schema")
async def get_settings_schema(section: str) -> dict[str, Any]:
    """Retrieve JSON Schema and metadata for a settings section (SPEC §11)."""
    section_lower = section.lower()
    if section_lower not in SECTION_MODELS:
        raise HTTPException(
            status_code=404,
            detail=f"Section '{section}' not found. Valid sections: {list(SECTION_MODELS.keys())}",
        )

    model_cls = SECTION_MODELS[section_lower]
    return {
        "section": section_lower,
        "schema": model_cls.model_json_schema(),
        "requires_restart": RESTART_REQUIRED_FIELDS.get(section_lower, []),
    }


@router.get("/{section}")
async def get_settings_section(
    section: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve settings for a given section with fallback to defaults."""
    section_lower = section.lower()
    if section_lower not in SECTION_MODELS:
        raise HTTPException(
            status_code=404,
            detail=f"Section '{section}' not found. Valid sections: {list(SECTION_MODELS.keys())}",
        )

    model_cls = SECTION_MODELS[section_lower]

    stmt = select(Setting).where(Setting.key == section_lower)
    result = await db.execute(stmt)
    setting_row = result.scalar_one_or_none()

    if setting_row:
        # Validate through Pydantic to ensure completeness
        return model_cls(**setting_row.value).model_dump()
    else:
        # Return default instance
        return model_cls().model_dump()


@router.put("/{section}")
async def update_settings_section(
    section: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Validate and update configuration for a given section."""
    section_lower = section.lower()
    if section_lower not in SECTION_MODELS:
        raise HTTPException(
            status_code=404,
            detail=f"Section '{section}' not found. Valid sections: {list(SECTION_MODELS.keys())}",
        )

    model_cls = SECTION_MODELS[section_lower]
    try:
        validated_obj = model_cls(**payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Validation error: {e}") from e

    validated_dict = validated_obj.model_dump()

    stmt = insert(Setting).values(
        key=section_lower,
        value=validated_dict,
        updated_at=datetime.now(UTC),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": validated_dict, "updated_at": datetime.now(UTC)},
    )
    await db.execute(stmt)
    await db.commit()

    return {
        "section": section_lower,
        "status": "updated",
        "settings": validated_dict,
    }


async def get_battery_settings(db: AsyncSession | None = None) -> BatterySettings:
    """Helper to fetch battery settings from DB with fallback to defaults."""
    if db is not None:
        stmt = select(Setting).where(Setting.key == "battery")
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row and isinstance(row.value, dict):
            return BatterySettings(**row.value)
        return BatterySettings()

    from ems.db.session import async_session_factory

    async with async_session_factory() as session:
        stmt = select(Setting).where(Setting.key == "battery")
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row and isinstance(row.value, dict):
            return BatterySettings(**row.value)
        return BatterySettings()


async def get_strategy_settings(db: AsyncSession | None = None) -> StrategySettings:
    """Helper to fetch strategy settings from DB with fallback to defaults."""
    if db is not None:
        stmt = select(Setting).where(Setting.key == "strategy")
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row and isinstance(row.value, dict):
            return StrategySettings(**row.value)
        return StrategySettings()

    from ems.db.session import async_session_factory

    async with async_session_factory() as session:
        stmt = select(Setting).where(Setting.key == "strategy")
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row and isinstance(row.value, dict):
            return StrategySettings(**row.value)
        return StrategySettings()
