"""Optimization REST API endpoints (SPEC §11)."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ems.db.models import Schedule as ScheduleModel
from ems.db.session import async_session_factory
from ems.optimization.strategies import ScheduleContext, get_strategy

logger = logging.getLogger(__name__)
router = APIRouter(tags=["optimize"])


class OptimizeRunRequest(BaseModel):
    """Payload for POST /api/optimize/run."""

    horizon_h: int = Field(default=24, ge=2, le=72, description="Optimization horizon in hours")
    strategy: str = Field(default="ARBITRAGE", description="Optimization strategy name")
    use_perfect_foresight: bool = Field(
        default=False, description="Whether to use actual DAM prices instead of forecasts"
    )
    initial_soc_pct: float | None = Field(
        default=None, ge=0.0, le=100.0, description="Override initial SoC %"
    )


@router.post("/optimize/run")
async def run_optimization(req: OptimizeRunRequest) -> dict[str, Any]:
    """Trigger on-demand BESS optimization (SPEC §11).

    Computes optimal dispatch schedule for the given horizon and strategy.
    """
    try:
        from ems.main import app_state

        sim_now = app_state.clock.now() if app_state.clock else datetime.now(tz=UTC)
        horizon_start = sim_now.replace(minute=0, second=0, microsecond=0)
        horizon_end = horizon_start + timedelta(hours=req.horizon_h - 1)

        # Retrieve current battery state
        soc_pct = 50.0
        if req.initial_soc_pct is not None:
            soc_pct = req.initial_soc_pct
        elif app_state.mqtt and app_state.mqtt.latest_bess_telemetry:
            bess_id = app_state.settings.bess_id
            tdata = app_state.mqtt.latest_bess_telemetry.get(bess_id, {})
            soc_pct = float(tdata.get("soc_pct", 50.0))

        # Get tariffs for horizon
        async with async_session_factory() as session:
            market = app_state.market
            if not market:
                raise HTTPException(status_code=500, detail="Market simulator not initialized")
            tariffs = await market.get_hourly_tariffs(horizon_start, horizon_end, session)

        if not tariffs:
            # Generate synthetic tariffs if none in DB for this horizon
            from ems.ingestion.generator import SyntheticDataGenerator
            from ems.market.simulator import calculate_buy_price, calculate_sell_price

            gen = SyntheticDataGenerator(seed=42)
            df = gen.generate_dam_prices(start_dt=horizon_start, end_dt=horizon_end)
            tariffs = [
                {
                    "ts": row["ts"],
                    "price_dam": row["price_uah_mwh"],
                    "price_buy": calculate_buy_price(row["price_uah_mwh"], market.tariffs),
                    "price_sell": calculate_sell_price(row["price_uah_mwh"], market.tariffs),
                }
                for _, row in df.iterrows()
            ]

        from ems.api.settings import get_battery_settings, get_strategy_settings

        bat_cfg = await get_battery_settings()
        strat_cfg = await get_strategy_settings()

        context = ScheduleContext(
            current_time=sim_now,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            soc_pct=soc_pct,
            capacity_kwh=bat_cfg.capacity_kwh,
            max_charge_kw=bat_cfg.power_max_kw,
            max_discharge_kw=bat_cfg.power_max_kw,
            soc_min_pct=bat_cfg.soc_min_pct,
            soc_max_pct=bat_cfg.soc_max_pct,
            reserve_soc_pct=strat_cfg.reserve_soc_pct,
            peak_limit_kw=strat_cfg.peak_limit_kw,
            prices=tariffs,
        )

        strat = get_strategy(req.strategy)
        schedule = strat.build_schedule(context)

        # Persist schedule to DB
        async with async_session_factory() as session:
            db_data = schedule.to_db_dict()
            obj = ScheduleModel(**db_data)
            session.add(obj)
            await session.commit()

        # Optionally activate in dispatcher
        if app_state.dispatcher:
            app_state.dispatcher.set_schedule(schedule)

        return {
            "status": "success",
            "schedule_id": schedule.id,
            "strategy": schedule.strategy,
            "capacity_kwh": schedule.capacity_kwh,
            "solver_status": schedule.solver_status,
            "solve_time_ms": schedule.solve_time_ms,
            "expected_profit_uah": schedule.expected_profit_uah,
            "items_count": len(schedule.items),
            "items": [
                {
                    "ts": item.ts.isoformat(),
                    "setpoint_kw": item.setpoint_kw,
                    "reason": item.reason,
                }
                for item in schedule.items
            ],
        }

    except Exception as e:
        logger.error("Failed to run optimization: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
