"""System configuration and settings API endpoints (SPEC §11)."""

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ems.db.models import Setting
from ems.db.session import get_db
from ems.market.simulator import MarketTariffs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["Settings"])

# Battery fields that are meaningful to the physical simulator and therefore
# pushed to it over MQTT whenever the operator saves the battery section.
BATTERY_SIM_FIELDS: tuple[str, ...] = (
    "capacity_kwh",
    "power_max_kw",
    "soc_min_pct",
    "soc_max_pct",
    "soc_hard_min_pct",
    "soc_hard_max_pct",
    "soc_derate_charge_start_pct",
    "soc_derate_discharge_start_pct",
    "eff_charge",
    "eff_discharge",
    "self_discharge_pct_day",
    "aux_load_kw",
    "aux_from_ac",
    "ramp_rate_kw_s",
    "temp_ambient_c",
    "temp_max_c",
    "thermal_loss_frac_rated",
    "cooling_design_delta_t_c",
    "thermal_mass_kj_per_kwh",
    "v_nominal_v",
    "cycle_life",
    "calendar_fade_pct_per_year",
    "deg_temp_ref_c",
    "deg_temp_doubling_k",
    "capex_uah",
    "initial_soc_pct",
)


def battery_config_payload(battery: "BatterySettings") -> dict[str, Any]:
    """Project battery settings onto the field set understood by the BESS simulator."""
    data = battery.model_dump()
    return {k: data[k] for k in BATTERY_SIM_FIELDS if k in data}


class BatterySettings(BaseModel):
    """BESS hardware and operating settings (SPEC §5.1)."""

    capacity_kwh: float = Field(default=1000.0, ge=10.0, le=100000.0)
    power_max_kw: float = Field(default=500.0, ge=5.0, le=50000.0)
    soc_min_pct: float = Field(default=10.0, ge=0.0, le=50.0)
    soc_max_pct: float = Field(default=90.0, ge=50.0, le=100.0)
    soc_hard_min_pct: float = Field(default=5.0, ge=0.0, le=20.0)
    soc_hard_max_pct: float = Field(default=97.0, ge=80.0, le=100.0)
    soc_derate_charge_start_pct: float = Field(default=85.0, ge=20.0, le=100.0)
    soc_derate_discharge_start_pct: float = Field(default=15.0, ge=0.0, le=80.0)
    eff_charge: float = Field(default=0.95, gt=0.5, le=1.0)
    eff_discharge: float = Field(default=0.95, gt=0.5, le=1.0)
    self_discharge_pct_day: float = Field(default=0.1, ge=0.0, le=5.0)
    aux_load_kw: float = Field(default=3.0, ge=0.0, le=50.0)
    aux_from_ac: bool = Field(
        default=True,
        description="Auxiliaries fed from the AC bus (real containerised topology) "
        "instead of draining the DC pack",
    )
    ramp_rate_kw_s: float = Field(default=50.0, ge=1.0, le=1000.0)
    temp_ambient_c: float = Field(default=25.0, ge=-30.0, le=60.0)
    temp_max_c: float = Field(default=45.0, ge=30.0, le=80.0)
    # Scale-invariant thermal design — the simulator derives R_internal, k_cooling,
    # C_thermal and the pack resistance from these plus capacity/power.
    thermal_loss_frac_rated: float = Field(default=0.025, ge=0.001, le=0.2)
    cooling_design_delta_t_c: float = Field(default=10.0, ge=1.0, le=40.0)
    thermal_mass_kj_per_kwh: float = Field(default=5.0, ge=0.5, le=50.0)
    v_nominal_v: float = Field(default=780.0, ge=48.0, le=2000.0)
    cycle_life: float = Field(default=6000.0, ge=500.0, le=30000.0)
    calendar_fade_pct_per_year: float = Field(default=1.5, ge=0.0, le=10.0)
    deg_temp_ref_c: float = Field(default=25.0, ge=0.0, le=45.0)
    deg_temp_doubling_k: float = Field(default=10.0, ge=2.0, le=30.0)
    capex_uah: float = Field(default=15000000.0, ge=0.0)
    initial_soc_pct: float = Field(default=50.0, ge=0.0, le=100.0)

    def degradation_cost_uah_per_kwh(self) -> float:
        """Marginal battery wear cost per kWh of throughput (charge + discharge).

        Lifetime throughput = cycle_life · usable_capacity · 2 (one charge and one
        discharge per equivalent full cycle), so c_deg = capex / that throughput.
        """
        usable_kwh = self.capacity_kwh * max(0.0, self.soc_max_pct - self.soc_min_pct) / 100.0
        lifetime_kwh = 2.0 * self.cycle_life * usable_kwh
        if lifetime_kwh <= 0.0:
            return 0.0
        return self.capex_uah / lifetime_kwh


class StrategySettings(BaseModel):
    """Energy dispatch strategy parameters (SPEC §6.7, §9)."""

    active_strategy: Literal[
        "ARBITRAGE",
        "PEAK_SHAVING",
        "SELF_CONSUMPTION",
        "BACKUP_RESERVE",
        "TOU_SIMPLE",
    ] = Field(default="ARBITRAGE")
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

    # The settings form must always render, even when the database is unreachable or
    # holds a row written by an older schema version — fall back to validated defaults
    # instead of returning 500 and leaving the UI with an empty parameter list.
    try:
        stmt = select(Setting).where(Setting.key == section_lower)
        result = await db.execute(stmt)
        setting_row = result.scalar_one_or_none()
    except Exception as e:
        logger.warning(
            "Settings section '%s' unavailable from database (%s) — serving defaults.",
            section_lower,
            e,
        )
        return model_cls().model_dump()

    if setting_row and isinstance(setting_row.value, dict):
        try:
            # Validate through Pydantic to ensure completeness
            return model_cls(**setting_row.value).model_dump()
        except Exception as e:
            logger.warning(
                "Stored settings for '%s' are invalid (%s) — serving defaults.", section_lower, e
            )
    return model_cls().model_dump()


@router.put("/{section}")
async def update_settings_section(
    section: str,
    payload: dict[str, Any],
    db: AsyncSession | None = Depends(get_db),
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

    real_db: AsyncSession | None = db if (db is not None and hasattr(db, "execute")) else None
    try:
        if real_db is not None:
            await real_db.execute(stmt)
            await real_db.commit()
        else:
            from ems.db.session import async_session_factory

            async with async_session_factory() as session:
                await session.execute(stmt)
                await session.commit()
    except Exception as e:
        logger.warning(
            "Could not persist settings section '%s' to database (%s) — applying to runtime only.",
            section_lower,
            e,
        )

    applied = await apply_settings_to_runtime(section_lower, validated_obj)

    return {
        "section": section_lower,
        "status": "updated",
        "settings": validated_dict,
        "applied": applied,
    }


async def apply_settings_to_runtime(section: str, validated_obj: BaseModel) -> list[str]:
    """Push saved settings into the live runtime so they take effect immediately.

    Without this the settings table is write-only: the dispatcher, the market
    tariffs, the active strategy and the BESS physics all keep running on their
    construction-time defaults (SPEC §11).
    """
    try:
        from ems.main import app_state
    except Exception:  # pragma: no cover - import cycle guard for standalone tests
        return []

    applied: list[str] = []

    if section == "market" and app_state.market is not None:
        app_state.market.tariffs = validated_obj  # type: ignore[assignment]
        applied.append("market_tariffs")

    if section == "strategy" and isinstance(validated_obj, StrategySettings):
        app_state._strategy_name = validated_obj.active_strategy
        applied.append("active_strategy")
        if app_state.dispatcher is not None:
            app_state.dispatcher.config.peak_limit_kw = validated_obj.peak_limit_kw
            applied.append("dispatcher_peak_limit")
        app_state._deg_cost_weight = validated_obj.degradation_cost_weight
        raw_deg = getattr(app_state, "_raw_deg_cost_per_kwh", app_state.deg_cost_uah_per_kwh)
        app_state.deg_cost_uah_per_kwh = raw_deg * app_state._deg_cost_weight
        applied.append("degradation_cost")

    if section == "ems" and isinstance(validated_obj, EmsCoreSettings):
        if app_state.dispatcher is not None:
            app_state.dispatcher.config.soc_tolerance_pct = validated_obj.soc_tolerance_pct
            applied.append("dispatcher_soc_tolerance")

    if section == "battery" and isinstance(validated_obj, BatterySettings):
        if app_state.dispatcher is not None:
            app_state.dispatcher.config.soc_min_pct = validated_obj.soc_min_pct
            app_state.dispatcher.config.soc_max_pct = validated_obj.soc_max_pct
            applied.append("dispatcher_soc_limits")
        app_state._raw_deg_cost_per_kwh = validated_obj.degradation_cost_uah_per_kwh()
        deg_weight = getattr(app_state, "_deg_cost_weight", 1.0)
        app_state.deg_cost_uah_per_kwh = app_state._raw_deg_cost_per_kwh * deg_weight
        applied.append("degradation_cost")
        if app_state.mqtt is not None:
            app_state.mqtt.publish_config(
                app_state.settings.bess_id, battery_config_payload(validated_obj)
            )
            applied.append("bess_config_published")

    return applied


async def load_section(section: str, db: AsyncSession | None = None) -> BaseModel:
    """Load one settings section from the DB, falling back to validated defaults."""
    model_cls = SECTION_MODELS[section]

    async def _read(session: AsyncSession) -> BaseModel:
        stmt = select(Setting).where(Setting.key == section)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row and isinstance(row.value, dict):
            return model_cls(**row.value)
        return model_cls()

    try:
        if db is not None:
            return await _read(db)
        from ems.db.session import async_session_factory

        async with async_session_factory() as session:
            return await _read(session)
    except Exception as e:
        logger.warning("Could not load '%s' settings (%s) — using defaults.", section, e)
        return model_cls()


async def get_battery_settings(db: AsyncSession | None = None) -> BatterySettings:
    """Helper to fetch battery settings from DB with fallback to defaults."""
    result = await load_section("battery", db)
    assert isinstance(result, BatterySettings)
    return result


async def get_strategy_settings(db: AsyncSession | None = None) -> StrategySettings:
    """Helper to fetch strategy settings from DB with fallback to defaults."""
    result = await load_section("strategy", db)
    assert isinstance(result, StrategySettings)
    return result


async def get_market_tariffs(db: AsyncSession | None = None) -> MarketTariffs:
    """Helper to fetch market tariff settings from DB with fallback to defaults."""
    result = await load_section("market", db)
    assert isinstance(result, MarketTariffs)
    return result


async def get_ems_core_settings(db: AsyncSession | None = None) -> EmsCoreSettings:
    """Helper to fetch EMS algorithm settings from DB with fallback to defaults."""
    result = await load_section("ems", db)
    assert isinstance(result, EmsCoreSettings)
    return result


async def get_simulation_settings(db: AsyncSession | None = None) -> SimulationSettings:
    """Helper to fetch simulation settings from DB with fallback to defaults."""
    result = await load_section("simulation", db)
    assert isinstance(result, SimulationSettings)
    return result
