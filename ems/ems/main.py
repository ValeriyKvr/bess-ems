"""EMS Core FastAPI application entrypoint (SPEC §4, §6)."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
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
from ems.ingestion.generator import SyntheticDataGenerator
from ems.market.financials import compute_hourly_financials, record_hourly_financials
from ems.market.simulator import (
    MarketSimulator,
    MarketTariffs,
    calculate_buy_price,
    calculate_sell_price,
)
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


def _new_hour_accumulator() -> dict[str, float]:
    """Fresh energy accumulator for one simulated hour."""
    return {
        "load_kwh": 0.0,
        "pv_kwh": 0.0,
        "aux_kwh": 0.0,
        "charge_kwh": 0.0,
        "discharge_kwh": 0.0,
        "price_dam_weighted": 0.0,
        "hours": 0.0,
    }


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
        self._price_cache: dict[datetime, float] = {}
        self._load_cache: dict[datetime, tuple[float, float]] = {}
        self._current_sim_date: date | None = None
        self._today_net_uah: float = 0.0
        self._today_baseline_uah: float = 0.0

        # Marginal battery wear cost, derived from capex / cycle life / usable capacity
        # (SPEC §7). Recomputed whenever the battery section is saved.
        self.deg_cost_uah_per_kwh: float = 1.5625

        # Energy accumulated over the current simulated hour, so hourly settlement
        # integrates real power over time instead of sampling the instantaneous value
        # at the hour boundary.
        self._hour_acc: dict[str, float] = _new_hour_accumulator()
        self._prev_hour_acc: dict[str, float] | None = None
        self._acc_hour: datetime | None = None

        # Deterministic fallback generator (same seed/profile as the seeded database)
        self._fallback_generator = SyntheticDataGenerator(seed=42)

        # Index of the last dispatcher event pushed to WebSocket clients
        self._last_event_index: int = 0

        # Backoff for on-the-fly schedule construction when the DB is unavailable
        self._last_schedule_attempt: datetime | None = None

        # Timestamp tracking how long BESS has been in a physically safe state during a fault
        self._bess_fault_safe_since: datetime | None = None

        # Queued D+1 schedules (SPEC §6.3: D+1 becomes active at 00:00 midnight)
        self._d_plus_one_schedule: Any | None = None
        self._preliminary_schedule: Any | None = None


app_state = ApplicationState()


async def preload_telemetry_cache(target_dt: datetime) -> None:
    """Preload prices and site loads into memory cache for smooth real-time ticks."""
    try:
        start_range = (target_dt - timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
        end_range = (target_dt + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)

        async with async_session_factory() as session:
            # 1. Fetch DAM prices
            p_stmt = select(DamPrice.ts, DamPrice.price_uah_mwh).where(
                DamPrice.ts >= start_range, DamPrice.ts <= end_range
            )
            p_res = await session.execute(p_stmt)
            for ts, price in p_res.all():
                app_state._price_cache[ts] = float(price)

            # 2. Fetch Site Loads
            l_stmt = select(SiteLoad.ts, SiteLoad.load_kw, SiteLoad.pv_kw).where(
                SiteLoad.ts >= start_range, SiteLoad.ts <= end_range
            )
            l_res = await session.execute(l_stmt)
            for ts, load, pv in l_res.all():
                app_state._load_cache[ts] = (float(load), float(pv))

    except Exception as e:
        logger.warning("Failed to preload telemetry cache: %s", e)


def _synthetic_hour(hour_dt: datetime) -> tuple[float, float, float]:
    """Generate (price_dam, load_kw, pv_kw) for one hour with the seeded generator.

    Uses the same SyntheticDataGenerator that fills the database, so a cache miss
    produces a profile consistent with the stored history instead of a different
    ad-hoc sine curve.
    """
    gen = app_state._fallback_generator
    price_df = gen.generate_dam_prices(start_dt=hour_dt, end_dt=hour_dt)
    load_df = gen.generate_site_load(start_dt=hour_dt, end_dt=hour_dt)
    price = float(price_df.iloc[0]["price_uah_mwh"]) if len(price_df) else 4500.0
    load = float(load_df.iloc[0]["load_kw"]) if len(load_df) else 300.0
    pv = float(load_df.iloc[0]["pv_kw"]) if len(load_df) else 0.0
    return price, load, pv


def _hour_sample(hour_dt: datetime) -> tuple[float, float, float]:
    """Return (price_dam, load_kw, pv_kw) for an hour, preferring the DB cache."""
    price = app_state._price_cache.get(hour_dt)
    load_pv = app_state._load_cache.get(hour_dt)
    if price is not None and load_pv is not None:
        return price, load_pv[0], load_pv[1]

    syn_price, syn_load, syn_pv = _synthetic_hour(hour_dt)
    if price is None:
        price = syn_price
        app_state._price_cache[hour_dt] = price
    if load_pv is None:
        load_pv = (syn_load, syn_pv)
        app_state._load_cache[hour_dt] = load_pv

    # Bound memory during long fast-forward runs (keep ~1 year of hourly samples)
    for cache in (app_state._price_cache, app_state._load_cache):
        if len(cache) > 10000:
            for key in sorted(cache)[:2000]:
                cache.pop(key, None)

    return price, load_pv[0], load_pv[1]


def _get_current_market_and_site(sim_time: datetime) -> tuple[float, float, float]:
    """Get (price_dam, load_kw, pv_kw) for sim_time.

    The DAM price is a step function held constant across the settlement hour (that
    is how the market actually clears), while load and PV are linearly interpolated
    between hourly samples so the physical model sees a continuous profile instead
    of hourly jumps.
    """
    hour_dt = sim_time.replace(minute=0, second=0, microsecond=0)
    next_hour_dt = hour_dt + timedelta(hours=1)
    frac = (sim_time - hour_dt).total_seconds() / 3600.0

    price_dam, load_now, pv_now = _hour_sample(hour_dt)
    _, load_next, pv_next = _hour_sample(next_hour_dt)

    load_kw = load_now + (load_next - load_now) * frac
    pv_kw = max(0.0, pv_now + (pv_next - pv_now) * frac)

    return price_dam, load_kw, pv_kw


async def on_hour_transition(new_hour_start: datetime) -> None:
    """Perform hourly financial settlement when simulation time advances an hour."""
    prev_hour = new_hour_start - timedelta(hours=1)
    logger.debug("Processing hourly settlement for hour: %s", prev_hour)

    # 1. Financial settlement for the elapsed hour, using the energy integrated over
    #    that hour by the tick loop rather than the instantaneous power at the boundary.
    acc = app_state._prev_hour_acc or app_state._hour_acc
    app_state._prev_hour_acc = None
    elapsed_h = acc.get("hours", 0.0)

    try:
        market_sim = app_state.market or MarketSimulator()

        if elapsed_h > 0.05:
            load_kwh = acc["load_kwh"]
            aux_kwh = acc["aux_kwh"]
            pv_kwh = acc["pv_kwh"]
            ch_kwh = acc["charge_kwh"]
            dis_kwh = acc["discharge_kwh"]
            price_dam = acc["price_dam_weighted"] / elapsed_h
        else:
            # Cold start (no ticks accumulated yet) — fall back to the stored profile
            price_dam, load_kw, pv_kw = _get_current_market_and_site(prev_hour)
            load_kwh, pv_kwh, ch_kwh, dis_kwh = load_kw, pv_kw, 0.0, 0.0
            aux_kwh = 0.0

        price_buy = calculate_buy_price(price_dam, market_sim.tariffs)
        price_sell = calculate_sell_price(price_dam, market_sim.tariffs)

        fin_result = compute_hourly_financials(
            ts=prev_hour,
            load_kwh=load_kwh,
            pv_kwh=pv_kwh,
            charge_kwh=ch_kwh,
            discharge_kwh=dis_kwh,
            price_buy_uah_mwh=price_buy,
            price_sell_uah_mwh=price_sell,
            c_deg_uah_kwh=app_state.deg_cost_uah_per_kwh,
            aux_kwh=aux_kwh,
        )
        async with async_session_factory() as session:
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

        # Collect site load and PV forecasts for the horizon
        load_series: list[float] = []
        pv_series: list[float] = []
        cur_h = horizon_start
        while cur_h <= horizon_end:
            _, l_kw, p_kw = _get_current_market_and_site(cur_h)
            load_series.append(l_kw)
            pv_series.append(p_kw)
            cur_h += timedelta(hours=1)

        c_deg = bat_cfg.degradation_cost_uah_per_kwh() * strat_cfg.degradation_cost_weight

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
            load_series=load_series,
            pv_series=pv_series,
            c_deg_uah_kwh=c_deg,
            eff_charge=bat_cfg.eff_charge,
            eff_discharge=bat_cfg.eff_discharge,
        )

        strategy = get_strategy(
            app_state._strategy_name,
            n_charge_hours=app_state._n_charge_hours,
            n_discharge_hours=app_state._n_discharge_hours,
        )
        schedule = strategy.build_schedule(context)
        schedule.params["start_soc_pct"] = soc_pct
        schedule.params["eff_charge"] = bat_cfg.eff_charge
        schedule.params["eff_discharge"] = bat_cfg.eff_discharge

        await _persist_schedule(schedule)
        app_state._preliminary_schedule = schedule

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


async def _build_schedule_for_date(target_date: date, sim_dt: datetime) -> None:
    """Build and activate schedule for target_date (SPEC §6.5)."""
    if not app_state.clock or not app_state.market or not app_state.dispatcher:
        return

    try:
        if sim_dt.date() == target_date:
            horizon_start = sim_dt.replace(minute=0, second=0, microsecond=0)
        else:
            horizon_start = datetime(
                target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=UTC
            )

        horizon_end = datetime(
            target_date.year, target_date.month, target_date.day, 23, 0, 0, tzinfo=UTC
        )
        if horizon_start >= horizon_end:
            horizon_end = horizon_start + timedelta(hours=24)

        tariffs = None
        try:
            async with async_session_factory() as session:
                tariffs = await app_state.market.get_hourly_tariffs(horizon_start, horizon_end, session)
        except Exception as e:
            logger.warning("Could not fetch tariffs from DB (%s) — falling back to market profile.", e)

        if not tariffs:
            # Fallback synthetic tariffs if database is missing this date
            tariffs = []
            cur_h = horizon_start
            m_sim = app_state.market or MarketSimulator()
            while cur_h <= horizon_end:
                p_dam, _, _ = _get_current_market_and_site(cur_h)
                tariffs.append(
                    {
                        "ts": cur_h.isoformat(),
                        "price_dam": p_dam,
                        "price_buy": calculate_buy_price(p_dam, m_sim.tariffs),
                        "price_sell": calculate_sell_price(p_dam, m_sim.tariffs),
                    }
                )
                cur_h += timedelta(hours=1)

        # Get current BESS state from MQTT cache
        soc_pct = 50.0
        if app_state.mqtt and app_state.mqtt.latest_bess_telemetry:
            bess_id = app_state.settings.bess_id
            tdata = app_state.mqtt.latest_bess_telemetry.get(bess_id, {})
            soc_pct = float(tdata.get("soc_pct", 50.0))

        bat_cfg = await get_battery_settings()
        strat_cfg = await get_strategy_settings()

        # Collect site load and PV forecasts for the horizon
        load_series: list[float] = []
        pv_series: list[float] = []
        cur_h = horizon_start
        while cur_h <= horizon_end:
            _, l_kw, p_kw = _get_current_market_and_site(cur_h)
            load_series.append(l_kw)
            pv_series.append(p_kw)
            cur_h += timedelta(hours=1)

        c_deg = bat_cfg.degradation_cost_uah_per_kwh() * strat_cfg.degradation_cost_weight

        if horizon_start.hour > 0:
            soc_end_target = min(soc_pct, max(bat_cfg.soc_min_pct, strat_cfg.reserve_soc_pct, 50.0))
        else:
            soc_end_target = soc_pct

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
            soc_end_target_pct=soc_end_target,
            reserve_soc_pct=strat_cfg.reserve_soc_pct,
            peak_limit_kw=strat_cfg.peak_limit_kw,
            prices=tariffs,
            load_series=load_series,
            pv_series=pv_series,
            c_deg_uah_kwh=c_deg,
            eff_charge=bat_cfg.eff_charge,
            eff_discharge=bat_cfg.eff_discharge,
        )

        strategy = get_strategy(
            app_state._strategy_name,
            n_charge_hours=app_state._n_charge_hours,
            n_discharge_hours=app_state._n_discharge_hours,
        )
        schedule = strategy.build_schedule(context)
        schedule.params["start_soc_pct"] = soc_pct
        schedule.params["eff_charge"] = bat_cfg.eff_charge
        schedule.params["eff_discharge"] = bat_cfg.eff_discharge

        # Persist schedule to database
        await _persist_schedule(schedule)

        # SPEC §6.3: D+1 schedule becomes active at 00:00 of the next day
        if target_date > sim_dt.date():
            app_state._d_plus_one_schedule = schedule
            logger.info(
                "Schedule for %s built and queued for D+1 midnight activation: %s (%d items, profit=%.2f UAH)",
                target_date,
                schedule.id,
                len(schedule.items),
                schedule.expected_profit_uah or 0,
            )
        else:
            app_state.dispatcher.set_schedule(schedule)
            logger.info(
                "Schedule for %s built and activated: %s (%d items, profit=%.2f UAH)",
                target_date,
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
        logger.error("Failed to build schedule for %s: %s", target_date, e)


async def _build_schedule_for_next_day(sim_dt: datetime) -> None:
    """Build and activate TOU schedule for D+1 after 13:00 gate closure."""
    target_date = sim_dt.date() + timedelta(days=1)
    await _build_schedule_for_date(target_date, sim_dt)


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

        # Collect site load and PV forecasts for the horizon
        load_series: list[float] = []
        pv_series: list[float] = []
        cur_h = horizon_start
        while cur_h <= horizon_end:
            _, l_kw, p_kw = _get_current_market_and_site(cur_h)
            load_series.append(l_kw)
            pv_series.append(p_kw)
            cur_h += timedelta(hours=1)

        c_deg = bat_cfg.degradation_cost_uah_per_kwh() * strat_cfg.degradation_cost_weight

        soc_end_target = active.params.get("start_soc_pct") or strat_cfg.reserve_soc_pct

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
            soc_end_target_pct=soc_end_target,
            reserve_soc_pct=strat_cfg.reserve_soc_pct,
            peak_limit_kw=strat_cfg.peak_limit_kw,
            prices=tariffs,
            load_series=load_series,
            pv_series=pv_series,
            c_deg_uah_kwh=c_deg,
            eff_charge=bat_cfg.eff_charge,
            eff_discharge=bat_cfg.eff_discharge,
        )
        strategy = get_strategy(app_state._strategy_name)
        new_schedule = strategy.build_schedule(context)
        new_schedule.params["start_soc_pct"] = current_soc
        new_schedule.params["eff_charge"] = bat_cfg.eff_charge
        new_schedule.params["eff_discharge"] = bat_cfg.eff_discharge

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


def _bess_telemetry() -> dict[str, Any]:
    """Latest telemetry frame for the configured BESS, or an empty dict."""
    if app_state.mqtt and app_state.mqtt.latest_bess_telemetry:
        return app_state.mqtt.latest_bess_telemetry.get(app_state.settings.bess_id, {}) or {}
    return {}


def _planned_soc_pct(sim_time: datetime) -> float | None:
    """Integrate the active schedule to the planned SoC at sim_time (SPEC §6.5).

    Returns None when there is no usable schedule, no capacity information, or no
    telemetry to anchor the trajectory on.
    """
    schedule = app_state.dispatcher.active_schedule if app_state.dispatcher else None
    if schedule is None or not schedule.items:
        return None
    capacity_kwh = schedule.capacity_kwh
    if capacity_kwh <= 0:
        return None

    anchor = schedule.params.get("start_soc_pct") if schedule.params else None
    if anchor is None:
        return None

    # Mirror the battery's energy conversion, otherwise the plan drifts above the
    # measured SoC on every charge and trips the deviation check spuriously.
    eff_ch = float(schedule.params.get("eff_charge", 1.0))
    eff_dis = float(schedule.params.get("eff_discharge", 1.0))

    energy_kwh = capacity_kwh * (float(anchor) / 100.0)
    for item in sorted(schedule.items, key=lambda i: i.ts):
        if item.ts >= sim_time:
            break
        span_h = min(1.0, max(0.0, (sim_time - item.ts).total_seconds() / 3600.0))
        power = item.setpoint_kw
        if power > 0.0:
            energy_kwh += power * span_h * eff_ch
        elif power < 0.0 and eff_dis > 0.0:
            energy_kwh += power * span_h / eff_dis

    return max(0.0, min(100.0, energy_kwh / capacity_kwh * 100.0))


def _accumulate_hour_energy(
    sim_time: datetime,
    delta_seconds: float,
    price_dam: float,
    load_kw: float,
    pv_kw: float,
) -> None:
    """Integrate power over the tick into the current simulated hour's energy totals."""
    hour_dt = sim_time.replace(minute=0, second=0, microsecond=0)
    if app_state._acc_hour is not None and hour_dt != app_state._acc_hour:
        app_state._prev_hour_acc = app_state._hour_acc
        app_state._hour_acc = _new_hour_accumulator()
    app_state._acc_hour = hour_dt

    dt_hours = max(0.0, delta_seconds) / 3600.0
    if dt_hours <= 0.0:
        return

    tdata = _bess_telemetry()
    bess_power = float(tdata.get("power_kw", 0.0))
    aux_kw = float(tdata.get("aux_kw", 0.0))

    acc = app_state._hour_acc
    acc["load_kwh"] += load_kw * dt_hours
    acc["pv_kwh"] += pv_kw * dt_hours
    acc["aux_kwh"] += aux_kw * dt_hours
    acc["charge_kwh"] += max(0.0, bess_power) * dt_hours
    acc["discharge_kwh"] += max(0.0, -bess_power) * dt_hours
    acc["price_dam_weighted"] += price_dam * dt_hours
    acc["hours"] += dt_hours


def on_clock_tick(sim_time: datetime, delta_seconds: float) -> None:
    """Handle each simulation clock tick: run dispatcher, update WebSocket."""
    if not app_state.dispatcher or not app_state.clock:
        return

    # 1. Activate queued D+1 schedule when simulation time reaches its horizon start (00:00 of D+1)
    if app_state._d_plus_one_schedule and sim_time >= app_state._d_plus_one_schedule.horizon_start:
        logger.info(
            "Activating D+1 schedule %s at sim_time %s",
            app_state._d_plus_one_schedule.id,
            sim_time,
        )
        app_state.dispatcher.set_schedule(app_state._d_plus_one_schedule)
        app_state._d_plus_one_schedule = None

    # 2. Check if active schedule covers current sim_time.
    # The last hour slot starting at horizon_end is valid until horizon_end + 1 hour.
    active = app_state.dispatcher.active_schedule
    schedule_valid = (
        active is not None
        and active.horizon_start <= sim_time < (active.horizon_end + timedelta(hours=1))
    )
    if not schedule_valid:
        last_try = app_state._last_schedule_attempt
        if last_try is None or (sim_time - last_try) >= timedelta(minutes=15):
            app_state._last_schedule_attempt = sim_time
            try:
                asyncio.create_task(_build_schedule_for_date(sim_time.date(), sim_time))
            except RuntimeError:
                pass

    # Retrieve current market price and site telemetry
    price_dam, load_kw, pv_kw = _get_current_market_and_site(sim_time)

    # Update dispatcher with current site load for peak shaving
    app_state.dispatcher.update_site_load(load_kw)

    # Update dispatcher with latest telemetry from MQTT
    bess_soc_pct: float | None = None
    if app_state.mqtt and app_state.mqtt.latest_bess_telemetry:
        bess_id = app_state.settings.bess_id
        tdata = app_state.mqtt.latest_bess_telemetry.get(bess_id, {})
        if tdata:
            bess_soc_pct = float(tdata.get("soc_pct", 50.0))
            app_state.dispatcher.update_telemetry(
                sim_time=sim_time,
                soc_pct=bess_soc_pct,
                state=str(tdata.get("state", "STANDBY")),
                power_kw=float(tdata.get("power_kw", 0.0)),
                temp_c=float(tdata.get("temp_c", 25.0)),
            )

    # Run dispatcher tick
    decision = app_state.dispatcher.tick(sim_time)

    # Auto-recovery watchdog: if BESS reported FAULT, check if physical conditions
    # have returned to safe operating bounds (SoC 12-88%, Temp <= 40°C) for >= 30 seconds.
    # If so, dispatch an automatic reset_alarm supervisory command to clear the latch.
    if app_state.dispatcher.state == "SAFE_MODE":
        tdata = _bess_telemetry()
        if tdata.get("state") == "FAULT":
            cur_soc = float(tdata.get("soc_pct", 50.0))
            cur_temp = float(tdata.get("temp_c", 25.0))
            if 12.0 <= cur_soc <= 88.0 and cur_temp <= 40.0:
                if app_state._bess_fault_safe_since is None:
                    app_state._bess_fault_safe_since = sim_time
                elif (sim_time - app_state._bess_fault_safe_since).total_seconds() >= 30.0:
                    logger.info(
                        "BESS telemetry safe for >= 30s. Sending auto-recovery reset_alarm."
                    )
                    if app_state.mqtt and app_state.mqtt.is_connected:
                        app_state.mqtt.publish_command(
                            app_state.settings.bess_id, {"cmd": "reset_alarm"}
                        )
                    app_state._bess_fault_safe_since = None
            else:
                app_state._bess_fault_safe_since = None
        else:
            app_state._bess_fault_safe_since = None
    else:
        app_state._bess_fault_safe_since = None

    # Closed-loop check: does the measured SoC still track the plan? (SPEC §6.5)
    if bess_soc_pct is not None:
        planned_soc = _planned_soc_pct(sim_time)
        if planned_soc is not None:
            app_state.dispatcher.check_reoptimization_needed(sim_time, bess_soc_pct, planned_soc)

    # Publish setpoint to MQTT (include both setpoint_kw and power_kw for compatibility)
    if app_state.mqtt and app_state.mqtt.is_connected:
        bess_id = app_state.settings.bess_id
        app_state.mqtt.publish_setpoint(
            bess_id,
            {
                "setpoint_kw": decision.setpoint_kw,
                "power_kw": decision.setpoint_kw,
                "ts_sim": sim_time.isoformat(),
                "source": "dispatcher",
                "reason": decision.reason,
            },
        )

    # Integrate energy over this tick for the hourly settlement
    _accumulate_hour_energy(sim_time, delta_seconds, price_dam, load_kw, pv_kw)

    # Persist to DB (async, fire-and-forget)
    try:
        asyncio.create_task(_persist_dispatch_decision(decision))
    except RuntimeError:
        pass

    # Broadcast to WebSocket clients
    _broadcast_ws_tick(sim_time, decision, price_dam, load_kw, pv_kw, delta_seconds)

    # Broadcast events if new ones appeared
    _broadcast_ws_events()


def _broadcast_ws_tick(
    sim_time: datetime,
    decision: Any,
    price_dam: float,
    load_kw: float,
    pv_kw: float,
    delta_seconds: float,
) -> None:
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

    bess_power = float(bess_data.get("power_kw", decision.setpoint_kw if decision else 0.0))
    aux_kw = float(bess_data.get("aux_kw", 0.0))

    # Grid import / export balance. BESS auxiliaries (HVAC, BMS, PCS idle draw) are fed
    # from the AC bus, so they add to what the site imports.
    net_facility = load_kw + aux_kw - pv_kw + bess_power
    grid_import = max(0.0, net_facility)
    grid_export = max(0.0, -net_facility)

    # Market prices & levels
    tariffs = app_state.market.tariffs if app_state.market else MarketTariffs()
    price_buy = calculate_buy_price(price_dam, tariffs)
    price_sell = calculate_sell_price(price_dam, tariffs)
    if price_dam >= 5500.0:
        level = "PEAK"
    elif price_dam <= 3200.0:
        level = "CHEAP"
    else:
        level = "MID"

    # Cumulative financial calculations for simulated day
    if app_state._current_sim_date != sim_time.date():
        app_state._current_sim_date = sim_time.date()
        app_state._today_net_uah = 0.0
        app_state._today_baseline_uah = 0.0

    dt_hours = max(0.0, delta_seconds) / 3600.0 if delta_seconds > 0 else (1.0 / 60.0)
    baseline_import = max(0.0, load_kw - pv_kw)
    cost_baseline = baseline_import * (price_buy / 1000.0) * dt_hours
    cost_actual = (
        grid_import * (price_buy / 1000.0) - grid_export * (price_sell / 1000.0)
    ) * dt_hours
    deg_cost = app_state.deg_cost_uah_per_kwh * abs(bess_power) * dt_hours
    net_saving = cost_baseline - cost_actual - deg_cost

    app_state._today_baseline_uah += cost_baseline
    app_state._today_net_uah += net_saving

    clock_data = app_state.clock.to_dict() if app_state.clock else {}

    payload: dict[str, Any] = {
        "clock": clock_data,
        "bess": bess_data,
        "site": {
            "load_kw": round(load_kw, 2),
            "pv_kw": round(pv_kw, 2),
            "aux_kw": round(aux_kw, 2),
        },
        "grid": {
            "import_kw": round(grid_import, 2),
            "export_kw": round(grid_export, 2),
        },
        "market": {
            "price_dam": round(price_dam, 2),
            "price_buy": round(price_buy, 2),
            "price_sell": round(price_sell, 2),
            "level": level,
        },
        "ems": app_state.dispatcher.get_ws_ems_state() if app_state.dispatcher else {},
        "finance": {
            "today_net_uah": round(app_state._today_net_uah, 2),
            "today_baseline_uah": round(app_state._today_baseline_uah, 2),
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

    # Only broadcast events that have not been sent yet — re-sending the tail on every
    # tick floods the UI event feed with duplicates.
    events = app_state.dispatcher.event_log
    if app_state._last_event_index > len(events):
        app_state._last_event_index = 0
    pending = events[app_state._last_event_index :]
    if not pending:
        return
    app_state._last_event_index = len(events)
    for event in pending:
        try:
            asyncio.create_task(ws_manager.broadcast_event(event))
        except RuntimeError:
            pass


async def _publish_bess_config(payload: dict[str, Any]) -> None:
    """Publish the retained BESS config once the MQTT connection is established."""
    for _ in range(30):
        if app_state.mqtt and app_state.mqtt.is_connected:
            app_state.mqtt.publish_config(app_state.settings.bess_id, payload)
            return
        await asyncio.sleep(1.0)
    logger.warning("MQTT never connected — BESS configuration was not published.")


async def _load_runtime_settings() -> dict[str, Any]:
    """Load persisted settings and configure market, dispatcher and strategy from them.

    Called on startup so that operator parameters saved in the UI actually govern the
    running system, instead of the services keeping their construction-time defaults.
    """
    from ems.api.settings import (
        battery_config_payload,
        get_ems_core_settings,
        get_market_tariffs,
    )

    battery = await get_battery_settings()
    strategy = await get_strategy_settings()
    tariffs = await get_market_tariffs()
    ems_cfg = await get_ems_core_settings()

    if app_state.market is not None:
        app_state.market.tariffs = tariffs

    app_state._strategy_name = strategy.active_strategy
    app_state.deg_cost_uah_per_kwh = (
        battery.degradation_cost_uah_per_kwh() * strategy.degradation_cost_weight
    )

    if app_state.dispatcher is not None:
        app_state.dispatcher.config.soc_min_pct = battery.soc_min_pct
        app_state.dispatcher.config.soc_max_pct = battery.soc_max_pct
        app_state.dispatcher.config.peak_limit_kw = strategy.peak_limit_kw
        app_state.dispatcher.config.soc_tolerance_pct = ems_cfg.soc_tolerance_pct

    logger.info(
        "Runtime settings applied: strategy=%s, capacity=%.0f kWh, power=%.0f kW, "
        "peak_limit=%.0f kW, c_deg=%.3f UAH/kWh",
        app_state._strategy_name,
        battery.capacity_kwh,
        battery.power_max_kw,
        strategy.peak_limit_kw,
        app_state.deg_cost_uah_per_kwh,
    )
    return battery_config_payload(battery)


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
    bess_config_payload: dict[str, Any] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection established.")

        # Auto-initialize schema and seed database if empty
        try:
            from ems.core.templates import apply_template
            from ems.db.seed import ensure_db_initialized_and_seeded

            async with async_session_factory() as session:
                await ensure_db_initialized_and_seeded(session)

            bess_config_payload = await _load_runtime_settings()

            # Preload telemetry cache & create Day 1 initial schedule using default template
            try:
                await apply_template("enterprise_september_2026")
                bess_config_payload = await _load_runtime_settings()
            except Exception as tmpl_err:
                logger.warning("Auto-applying template error: %s", tmpl_err)
                if app_state.clock:
                    start_dt = app_state.clock.now()
                    await preload_telemetry_cache(start_dt)
                    await _build_schedule_for_date(start_dt.date(), start_dt)
        except Exception as seed_err:
            logger.warning("Auto-seed or schedule initialization error: %s", seed_err)

    except Exception as e:
        logger.warning("Database not immediately available on startup (%s).", e)

    # 5. Initialize MQTT client with batched telemetry flusher
    app_state.mqtt = EmsMqttClient(
        settings=app_state.settings,
        session_factory=async_session_factory,
    )
    app_state.mqtt.connect()
    telemetry_flush_task = asyncio.create_task(app_state.mqtt.start_telemetry_flusher())

    # Push the operator's battery parameters to the simulator as a retained message,
    # so the physical model matches the configuration shown in the UI.
    config_push_task: asyncio.Task[None] | None = None
    if bess_config_payload:
        config_push_task = asyncio.create_task(_publish_bess_config(bess_config_payload))

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
    if config_push_task is not None:
        config_push_task.cancel()

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
