"""EMS Core FastAPI application entrypoint (SPEC §4, §6)."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ems.api.router import api_router, ws_api_router
from ems.api.settings import get_battery_settings, get_strategy_settings
from ems.api.ws import ws_manager
from ems.core.clock import SimulationClock
from ems.core.config import EmsSettings
from ems.db.models import DamPrice, DispatchLog, SiteLoad
from ems.db.models import Schedule as ScheduleModel
from ems.db.session import async_session_factory, engine
from ems.dispatch.dispatcher import Dispatcher, DispatcherConfig
from ems.market.financials import compute_hourly_financials, record_hourly_financials
from ems.market.simulator import MarketSimulator, calculate_buy_price, calculate_sell_price
from ems.mqtt.client import EmsMqttClient
from ems.optimization.strategies import (
    Schedule,
    ScheduleContext,
    get_strategy,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ems-core")


class ApplicationState:
    """Container holding runtime services."""

    def __init__(self) -> None:
        self.settings = EmsSettings()
        self.clock: SimulationClock | None = None
        self.mqtt: EmsMqttClient | None = None
        self.market: MarketSimulator | None = None
        self.dispatcher: Dispatcher | None = None
        self._strategy_name: str = "ARBITRAGE"
        self._n_charge_hours: int = 4
        self._n_discharge_hours: int = 4


app_state = ApplicationState()


async def on_hour_transition(new_hour_start: datetime) -> None:
    """Perform hourly financial settlement when simulation time advances an hour."""
    prev_hour = new_hour_start - timedelta(hours=1)
    logger.debug("Processing hourly settlement for hour: %s", prev_hour)

    # 1. Financial settlement for elapsed hour
    try:
        async with async_session_factory() as session:
            # Query load & PV for prev_hour
            load_stmt = select(SiteLoad).where(SiteLoad.ts == prev_hour)
            load_row = (await session.execute(load_stmt)).scalar_one_or_none()
            load_kwh = load_row.load_kw if load_row else 100.0
            pv_kwh = load_row.pv_kw if load_row else 0.0

            # Query DAM price for prev_hour
            price_stmt = select(DamPrice).where(DamPrice.ts == prev_hour)
            price_row = (await session.execute(price_stmt)).scalar_one_or_none()
            price_dam = price_row.price_uah_mwh if price_row else 4500.0

            # Compute effective buy/sell tariffs
            market_sim = app_state.market or MarketSimulator()
            price_buy = calculate_buy_price(price_dam, market_sim.tariffs)
            price_sell = calculate_sell_price(price_dam, market_sim.tariffs)

            # Retrieve BESS power if available from MQTT cache
            bess_power = 0.0
            if app_state.mqtt and app_state.mqtt.latest_bess_telemetry:
                bess_id = app_state.settings.bess_id
                tdata = app_state.mqtt.latest_bess_telemetry.get(bess_id, {})
                bess_power = float(tdata.get("power_kw", 0.0))

            ch_kwh = max(0.0, bess_power)  # 1 hour * power
            dis_kwh = max(0.0, -bess_power)

            fin_result = compute_hourly_financials(
                ts=prev_hour,
                load_kwh=load_kwh,
                pv_kwh=pv_kwh,
                charge_kwh=ch_kwh,
                discharge_kwh=dis_kwh,
                price_buy_uah_mwh=price_buy,
                price_sell_uah_mwh=price_sell,
            )
            await record_hourly_financials(fin_result, session)
    except Exception as e:
        logger.error("Failed to compute hourly financials for %s: %s", prev_hour, e)

    # 2. At 11:00 sim-time: trigger preliminary D+1 schedule using Forecaster (SPEC §6.3, §14)
    if new_hour_start.hour == 11:
        asyncio.create_task(_build_preliminary_schedule_with_forecast(new_hour_start))


async def _build_preliminary_schedule_with_forecast(sim_dt: datetime) -> None:
    """Build preliminary D+1 schedule at 11:00 using Forecaster (SPEC §6.3, §14)."""
    if not app_state.market or not app_state.dispatcher:
        return

    try:
        from ems.forecasting.service import generate_day_ahead_forecast

        target_date = sim_dt.date() + timedelta(days=1)
        horizon_start = datetime(
            target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=UTC
        )
        horizon_end = datetime(
            target_date.year, target_date.month, target_date.day, 23, 0, 0, tzinfo=UTC
        )

        async with async_session_factory() as session:
            price_forecasts = await generate_day_ahead_forecast(target_date, sim_dt, session)

        tariffs = []
        for p in price_forecasts:
            p_dam = p["price_dam"]
            p_buy = calculate_buy_price(p_dam, app_state.market.tariffs)
            p_sell = calculate_sell_price(p_dam, app_state.market.tariffs)
            tariffs.append(
                {
                    "ts": p["ts"],
                    "price_dam": p_dam,
                    "price_buy": p_buy,
                    "price_sell": p_sell,
                }
            )

        # Current SoC
        soc_pct = 50.0
        if app_state.mqtt and app_state.mqtt.latest_bess_telemetry:
            bess_id = app_state.settings.bess_id
            tdata = app_state.mqtt.latest_bess_telemetry.get(bess_id, {})
            soc_pct = float(tdata.get("soc_pct", 50.0))

        bat_cfg = await get_battery_settings()
        strat_cfg = await get_strategy_settings()

        context = ScheduleContext(
            current_time=sim_dt,
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

        strategy = get_strategy(app_state._strategy_name)
        schedule = strategy.build_schedule(context)

        await _persist_schedule(schedule)
        app_state.dispatcher.set_schedule(schedule)

        logger.info(
            "11:00 Preliminary schedule created with forecast: %s (profit=%.2f UAH)",
            schedule.id,
            schedule.expected_profit_uah or 0,
        )

        await ws_manager.broadcast_event(
            {
                "event": "PRELIMINARY_SCHEDULE_CREATED",
                "schedule_id": schedule.id,
                "strategy": schedule.strategy,
                "items_count": len(schedule.items),
                "expected_profit_uah": schedule.expected_profit_uah,
                "ts": sim_dt.isoformat(),
            }
        )

    except Exception as e:
        logger.error("Failed to build 11:00 preliminary schedule: %s", e)


async def on_13h_gate_closure(sim_dt: datetime) -> None:
    """Trigger Market Simulator publication of D+1 prices at 13:00 simulation time."""
    logger.info("Simulation clock reached 13:00 sim-time (%s). Publishing D+1 prices.", sim_dt)
    if not app_state.market:
        return
    try:
        target_date = sim_dt.date() + timedelta(days=1)
        async with async_session_factory() as session:
            count = await app_state.market.publish_d_plus_one_prices(sim_dt, session)
            logger.info("Successfully published %d D+1 prices for next day.", count)

            # Evaluate 11:00 forecast accuracy vs actuals (SPEC §6.3)
            from ems.forecasting.service import evaluate_d_plus_one_forecast

            metrics = await evaluate_d_plus_one_forecast(
                target_date, sim_dt, session, settings=app_state.settings
            )
            if metrics:
                await ws_manager.broadcast_event(
                    {
                        "event": "FORECAST_EVALUATED",
                        "target": "price",
                        "target_date": target_date.isoformat(),
                        "metrics": metrics,
                        "ts": sim_dt.isoformat(),
                    }
                )
    except Exception as e:
        logger.error("Failed to publish D+1 prices / evaluate forecast at 13:00: %s", e)

    # Build schedule for D+1 at 13:05 (5 sim-minutes after gate closure)
    asyncio.get_event_loop().call_later(
        0.1, lambda: asyncio.create_task(_build_schedule_for_next_day(sim_dt))
    )


async def _build_schedule_for_next_day(sim_dt: datetime) -> None:
    """Build and activate TOU_SIMPLE schedule for D+1 after 13:00 gate closure."""
    if not app_state.clock or not app_state.market or not app_state.dispatcher:
        return

    try:
        target_date = sim_dt.date() + timedelta(days=1)
        horizon_start = datetime(
            target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=UTC
        )
        horizon_end = datetime(
            target_date.year, target_date.month, target_date.day, 23, 0, 0, tzinfo=UTC
        )

        async with async_session_factory() as session:
            # Get D+1 prices
            tariffs = await app_state.market.get_hourly_tariffs(horizon_start, horizon_end, session)

        if not tariffs:
            logger.warning("No price data for D+1 (%s) — skipping schedule build.", target_date)
            return

        # Get current BESS state from MQTT cache
        soc_pct = 50.0
        if app_state.mqtt and app_state.mqtt.latest_bess_telemetry:
            bess_id = app_state.settings.bess_id
            tdata = app_state.mqtt.latest_bess_telemetry.get(bess_id, {})
            soc_pct = float(tdata.get("soc_pct", 50.0))

        bat_cfg = await get_battery_settings()
        strat_cfg = await get_strategy_settings()

        context = ScheduleContext(
            current_time=sim_dt,
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

        strategy = get_strategy(
            app_state._strategy_name,
            n_charge_hours=app_state._n_charge_hours,
            n_discharge_hours=app_state._n_discharge_hours,
        )
        schedule = strategy.build_schedule(context)

        # Persist schedule to database
        await _persist_schedule(schedule)

        # Activate in dispatcher
        app_state.dispatcher.set_schedule(schedule)
        logger.info(
            "D+1 schedule built and activated: %s (%d items, profit=%.2f UAH)",
            schedule.id,
            len(schedule.items),
            schedule.expected_profit_uah or 0,
        )

        # Broadcast schedule event via WebSocket
        await ws_manager.broadcast_event(
            {
                "event": "SCHEDULE_CREATED",
                "schedule_id": schedule.id,
                "strategy": schedule.strategy,
                "items_count": len(schedule.items),
                "expected_profit_uah": schedule.expected_profit_uah,
                "ts": sim_dt.isoformat(),
            }
        )

    except Exception as e:
        logger.error("Failed to build D+1 schedule: %s", e)


async def _persist_schedule(schedule: Schedule) -> None:
    """Save schedule to the database."""
    try:
        async with async_session_factory() as session:
            db_data = schedule.to_db_dict()
            obj = ScheduleModel(**db_data)
            session.add(obj)
            await session.commit()
            logger.debug("Schedule %s persisted to database.", schedule.id)
    except Exception as e:
        logger.error("Failed to persist schedule %s: %s", schedule.id, e)


async def _persist_dispatch_decision(decision: Any) -> None:
    """Persist a dispatch decision to the dispatch_log table."""
    try:
        async with async_session_factory() as session:
            stmt = (
                pg_insert(DispatchLog)
                .values(
                    ts=decision.ts,
                    setpoint_kw=decision.setpoint_kw,
                    actual_kw=None,  # Will be filled from telemetry
                    reason=decision.reason,
                    schedule_id=decision.schedule_id,
                    override=decision.override,
                )
                .on_conflict_do_nothing()
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as e:
        logger.debug("Failed to persist dispatch log: %s", e)


async def on_rolling_reopt_trigger(sim_time: datetime, current_soc: float) -> None:
    """Re-optimize remaining horizon when closed-loop SoC deviation exceeds tolerance (SPEC §6.5)."""
    if not app_state.dispatcher or not app_state.dispatcher.active_schedule:
        return

    active = app_state.dispatcher.active_schedule
    horizon_start = sim_time.replace(minute=0, second=0, microsecond=0)
    horizon_end = active.horizon_end
    if horizon_start >= horizon_end:
        return

    try:
        async with async_session_factory() as session:
            if not app_state.market:
                return
            tariffs = await app_state.market.get_hourly_tariffs(horizon_start, horizon_end, session)

        if not tariffs:
            return

        bat_cfg = await get_battery_settings()
        strat_cfg = await get_strategy_settings()

        context = ScheduleContext(
            current_time=sim_time,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            soc_pct=current_soc,
            capacity_kwh=bat_cfg.capacity_kwh,
            max_charge_kw=bat_cfg.power_max_kw,
            max_discharge_kw=bat_cfg.power_max_kw,
            soc_min_pct=bat_cfg.soc_min_pct,
            soc_max_pct=bat_cfg.soc_max_pct,
            reserve_soc_pct=strat_cfg.reserve_soc_pct,
            peak_limit_kw=strat_cfg.peak_limit_kw,
            prices=tariffs,
        )
        strategy = get_strategy(app_state._strategy_name)
        new_schedule = strategy.build_schedule(context)

        await _persist_schedule(new_schedule)
        app_state.dispatcher.set_schedule(new_schedule)
        logger.info(
            "Rolling re-optimization completed: %s (profit=%.2f UAH, items=%d)",
            new_schedule.id,
            new_schedule.expected_profit_uah or 0,
            len(new_schedule.items),
        )
        await ws_manager.broadcast_event(
            {
                "event": "ROLLING_REOPTIMIZATION_COMPLETED",
                "schedule_id": new_schedule.id,
                "strategy": new_schedule.strategy,
                "ts": sim_time.isoformat(),
            }
        )
    except Exception as e:
        logger.error("Failed rolling re-optimization: %s", e)


def on_clock_tick(sim_time: datetime, delta_seconds: float) -> None:
    """Handle each simulation clock tick: run dispatcher, update WebSocket."""
    if not app_state.dispatcher or not app_state.clock:
        return

    # Update dispatcher with latest telemetry from MQTT
    if app_state.mqtt and app_state.mqtt.latest_bess_telemetry:
        bess_id = app_state.settings.bess_id
        tdata = app_state.mqtt.latest_bess_telemetry.get(bess_id, {})
        if tdata:
            app_state.dispatcher.update_telemetry(
                sim_time=sim_time,
                soc_pct=float(tdata.get("soc_pct", 50.0)),
                state=str(tdata.get("state", "STANDBY")),
                power_kw=float(tdata.get("power_kw", 0.0)),
                temp_c=float(tdata.get("temp_c", 25.0)),
            )

    # Run dispatcher tick
    decision = app_state.dispatcher.tick(sim_time)

    # Publish setpoint to MQTT
    if app_state.mqtt and app_state.mqtt.is_connected:
        bess_id = app_state.settings.bess_id
        app_state.mqtt.publish_setpoint(
            bess_id,
            {
                "power_kw": decision.setpoint_kw,
                "ts_sim": sim_time.isoformat(),
                "source": "dispatcher",
                "reason": decision.reason,
            },
        )

    # Persist to DB (async, fire-and-forget)
    try:
        asyncio.create_task(_persist_dispatch_decision(decision))
    except RuntimeError:
        pass

    # Broadcast to WebSocket clients
    _broadcast_ws_tick(sim_time, decision)

    # Broadcast events if new ones appeared
    _broadcast_ws_events()


def _broadcast_ws_tick(sim_time: datetime, decision: Any) -> None:
    """Build and broadcast WebSocket tick payload (SPEC §10.2)."""
    if ws_manager.connection_count == 0:
        return

    # Update throttle based on current speed
    if app_state.clock:
        ws_manager.update_throttle(app_state.clock.speed)

    # Build tick payload
    bess_data: dict[str, Any] = {}
    if app_state.mqtt and app_state.mqtt.latest_bess_telemetry:
        bess_id = app_state.settings.bess_id
        bess_data = app_state.mqtt.latest_bess_telemetry.get(bess_id, {})

    clock_data = app_state.clock.to_dict() if app_state.clock else {}

    payload: dict[str, Any] = {
        "clock": clock_data,
        "bess": bess_data,
        "site": {
            "load_kw": app_state.dispatcher._site_load_kw if app_state.dispatcher else 0,
            "pv_kw": 0,
        },
        "grid": {
            "import_kw": 0,
            "export_kw": 0,
        },
        "market": {},
        "ems": app_state.dispatcher.get_ws_ems_state() if app_state.dispatcher else {},
        "finance": {
            "today_net_uah": 0,
            "today_baseline_uah": 0,
        },
    }

    try:
        asyncio.create_task(ws_manager.broadcast_tick(payload))
    except RuntimeError:
        pass


def _broadcast_ws_events() -> None:
    """Broadcast any new events from the dispatcher."""
    if not app_state.dispatcher or ws_manager.connection_count == 0:
        return

    # Check for new events (simple approach: track last broadcast index)
    events = app_state.dispatcher.event_log
    if events:
        latest = events[-1]
        try:
            asyncio.create_task(ws_manager.broadcast_event(latest))
        except RuntimeError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle."""
    logger.info("Initializing EMS Core services...")

    # 1. Initialize Market Simulator
    app_state.market = MarketSimulator()

    # 2. Initialize Dispatcher
    app_state.dispatcher = Dispatcher(DispatcherConfig())
    app_state.dispatcher.register_reopt_callback(
        lambda st, soc: asyncio.create_task(on_rolling_reopt_trigger(st, soc))
    )

    # 3. Initialize Simulation Clock and hooks
    app_state.clock = SimulationClock(
        start_time=app_state.settings.sim_start_time,
        speed=app_state.settings.sim_speed,
    )
    app_state.clock.register_hourly_callback(on_hour_transition)
    app_state.clock.register_13h_callback(on_13h_gate_closure)
    app_state.clock.register_tick_callback(on_clock_tick)

    # 4. Check Database connectivity and run seed if needed
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection established.")

        # Auto-initialize schema and seed database if empty
        try:
            from ems.db.seed import ensure_db_initialized_and_seeded

            async with async_session_factory() as session:
                await ensure_db_initialized_and_seeded(session)
        except Exception as seed_err:
            logger.warning("Auto-seed check encountered non-fatal error: %s", seed_err)

    except Exception as e:
        logger.warning("Database not immediately available on startup (%s).", e)

    # 5. Initialize MQTT client with batched telemetry flusher
    app_state.mqtt = EmsMqttClient(
        settings=app_state.settings,
        session_factory=async_session_factory,
    )
    app_state.mqtt.connect()
    telemetry_flush_task = asyncio.create_task(app_state.mqtt.start_telemetry_flusher())

    # 6. Start Clock background loop
    def publish_clock_mqtt(clock_dict: dict) -> None:
        if app_state.mqtt and app_state.mqtt.is_connected:
            app_state.mqtt.publish_clock(clock_dict)

    clock_loop_task = asyncio.create_task(app_state.clock.start_loop(publish_clock_mqtt))

    # 7. Start WebSocket throttle flusher (periodic flush for high-speed mode)
    ws_flush_task = asyncio.create_task(_ws_throttle_flusher())

    yield

    # Shutdown
    logger.info("Shutting down EMS Core...")
    if app_state.clock:
        app_state.clock.stop_loop()
    clock_loop_task.cancel()
    telemetry_flush_task.cancel()
    ws_flush_task.cancel()

    await ws_manager.close_all()

    if app_state.mqtt:
        app_state.mqtt.disconnect()

    await engine.dispose()
    logger.info("EMS Core shutdown complete.")


async def _ws_throttle_flusher() -> None:
    """Periodically flush pending throttled WebSocket ticks."""
    while True:
        await asyncio.sleep(0.1)
        await ws_manager.flush_pending()


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = app_state.settings

    app = FastAPI(
        title="BESS EMS Core API",
        description="Energy Management System for Ukrainian Electricity Market",
        version="0.3.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.ems_api_prefix)
    app.include_router(ws_api_router)  # WS at root, not under /api

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": "BESS EMS Core",
            "docs": "/docs",
            "health": f"{settings.ems_api_prefix}/health",
            "sim_time": app_state.clock.now_iso() if app_state.clock else "N/A",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = app_state.settings
    uvicorn.run("ems.main:app", host=settings.ems_host, port=settings.ems_port, reload=True)
