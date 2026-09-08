"""Simulation Templates management for BESS/EMS scenarios (SPEC §3, §6, §11).

Provides structured modeling templates for various enterprise configurations and market data,
with cyclic looping and analytical performance reporting.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SimulationTemplate(BaseModel):
    """Configuration template defining an enterprise modeling scenario."""

    id: str = Field(..., description="Unique template identifier")
    name: str = Field(..., description="User-friendly name of the template")
    description: str = Field(..., description="Detailed description of enterprise setup")
    start_time: str = Field(default="2026-09-01T00:00:00Z", description="Simulation start ISO timestamp")
    duration_days: int = Field(default=9, ge=1, le=365, description="Full scenario duration in days")
    loop_cyclic: bool = Field(default=True, description="Whether to loop cyclically")
    default_loop_days: int = Field(default=9, ge=1, le=365, description="Default loop window in days")
    max_loop_days: int = Field(default=9, ge=1, le=365, description="Maximum loop window in days")
    battery_capacity_kwh: float = Field(default=2000.0, ge=10.0, description="Battery capacity in kWh")
    battery_power_kw: float = Field(default=1000.0, ge=5.0, description="Inverter max power in kW")
    soc_min_pct: float = Field(default=10.0, ge=0.0, le=50.0, description="Minimum allowable SoC %")
    soc_max_pct: float = Field(default=90.0, ge=50.0, le=100.0, description="Maximum allowable SoC %")
    reserve_soc_pct: float = Field(default=15.0, ge=0.0, le=50.0, description="Emergency reserve SoC %")
    initial_soc_pct: float = Field(default=20.0, ge=0.0, le=100.0, description="Starting SoC %")
    site_day_load_kw: float = Field(default=250.0, ge=0.0, description="Daytime load (07:00-23:00) in kW")
    site_night_load_kw: float = Field(default=50.0, ge=0.0, description="Nighttime load (23:00-07:00) in kW")
    pv_peak_kw: float = Field(default=150.0, ge=0.0, description="Peak solar PV generation in kW")
    strategy: str = Field(default="ARBITRAGE", description="Active dispatch strategy")
    price_source: str = Field(default="real_dam_september_2026", description="Dataset price source")
    is_default: bool = Field(default=False, description="Whether this is the default template")


# Predefined built-in system templates
BUILTIN_TEMPLATES: list[SimulationTemplate] = [
    SimulationTemplate(
        id="enterprise_september_2026",
        name="Підприємство 1 МВт / 2 МВт·год (Вересень 2026)",
        description=(
            "Реальний профіль промислового підприємства: денне навантаження 200–300 кВт, "
            "нічне 0–100 кВт, СЕС 150 кВт, BESS 1 000 кВт / 2 000 кВт·год. "
            "Реальні погодинні ціни РДН/ВДР України за 01–09 вересня 2026 р. із ціновим "
            "провалом до 10 грн/МВт·год та вечірнім піком до 15 000 грн/МВт·год."
        ),
        start_time="2026-09-01T00:00:00Z",
        duration_days=9,
        loop_cyclic=True,
        default_loop_days=9,
        max_loop_days=9,
        battery_capacity_kwh=2000.0,
        battery_power_kw=1000.0,
        soc_min_pct=10.0,
        soc_max_pct=90.0,
        reserve_soc_pct=15.0,
        initial_soc_pct=20.0,
        site_day_load_kw=250.0,
        site_night_load_kw=50.0,
        pv_peak_kw=150.0,
        strategy="ARBITRAGE",
        price_source="real_dam_september_2026",
        is_default=True,
    ),
    SimulationTemplate(
        id="march_baseline_2026",
        name="Базова весняна модель (Березень 2026)",
        description=(
            "Синтетичний профіль весняного сезону: BESS 500 кВт / 1 000 кВт·год, "
            "навантаження 300 кВт, СЕС 200 кВт пік, синтетичні ціни РДН 4 500–8 000 грн/МВт·год."
        ),
        start_time="2026-03-01T00:00:00Z",
        duration_days=7,
        loop_cyclic=True,
        default_loop_days=7,
        max_loop_days=31,
        battery_capacity_kwh=1000.0,
        battery_power_kw=500.0,
        soc_min_pct=10.0,
        soc_max_pct=90.0,
        reserve_soc_pct=20.0,
        initial_soc_pct=50.0,
        site_day_load_kw=320.0,
        site_night_load_kw=100.0,
        pv_peak_kw=200.0,
        strategy="ARBITRAGE",
        price_source="synthetic_generator_seed_42",
        is_default=False,
    ),
]


def _custom_templates_path() -> Path:
    base = Path(__file__).resolve().parent.parent.parent
    p = base / "data" / "templates"
    p.mkdir(parents=True, exist_ok=True)
    return p / "custom_templates.json"


def _load_custom_templates() -> list[SimulationTemplate]:
    path = _custom_templates_path()
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [SimulationTemplate(**item) for item in data]
    except Exception as e:
        logger.warning("Failed to load custom templates from %s: %s", path, e)
        return []


def _save_custom_templates(templates: list[SimulationTemplate]) -> None:
    path = _custom_templates_path()
    try:
        data = [t.model_dump() for t in templates]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Failed to save custom templates to %s: %s", path, e)


def get_all_templates() -> list[SimulationTemplate]:
    """Retrieve all available simulation templates (built-in + user custom)."""
    custom = _load_custom_templates()
    custom_ids = {c.id for c in custom}
    all_t = [b for b in BUILTIN_TEMPLATES if b.id not in custom_ids] + custom
    return all_t


def get_template(template_id: str) -> SimulationTemplate | None:
    """Retrieve a specific template by ID."""
    for t in get_all_templates():
        if t.id == template_id:
            return t
    return None


def save_template(template: SimulationTemplate) -> SimulationTemplate:
    """Save or update a template."""
    custom = [t for t in _load_custom_templates() if t.id != template.id]
    custom.append(template)
    _save_custom_templates(custom)
    return template


async def apply_template(template_id: str, loop_days: int | None = None) -> dict[str, Any]:
    """Apply a simulation template: update battery/site/strategy settings, clock, and schedule."""
    from ems.api.settings import (
        get_battery_settings,
        get_strategy_settings,
        update_settings_section,
    )
    from ems.main import (
        _build_schedule_for_date,
        _publish_bess_config,
        app_state,
        preload_telemetry_cache,
    )

    template = get_template(template_id)
    if not template:
        raise ValueError(f"Template '{template_id}' not found.")

    effective_loop_days = min(
        template.max_loop_days, max(1, loop_days or template.default_loop_days)
    )

    # 1. Update BatterySettings in database/runtime
    current_bat = await get_battery_settings()
    bat_update = current_bat.model_dump()
    bat_update.update(
        {
            "capacity_kwh": template.battery_capacity_kwh,
            "power_max_kw": template.battery_power_kw,
            "soc_min_pct": template.soc_min_pct,
            "soc_max_pct": template.soc_max_pct,
            "initial_soc_pct": template.initial_soc_pct,
        }
    )
    await update_settings_section("battery", bat_update)

    # 2. Update StrategySettings
    current_strat = await get_strategy_settings()
    strat_update = current_strat.model_dump()
    strat_update.update(
        {
            "reserve_soc_pct": template.reserve_soc_pct,
            "default_strategy": template.strategy,
        }
    )
    await update_settings_section("strategy", strat_update)
    app_state._strategy_name = template.strategy

    # 3. Configure Clock start and cyclic loop
    start_dt = datetime.fromisoformat(template.start_time.replace("Z", "+00:00"))
    end_dt = start_dt + timedelta(days=effective_loop_days)

    if app_state.clock:
        app_state.clock.set_loop(
            enabled=template.loop_cyclic,
            start=start_dt,
            end=end_dt,
        )
        app_state.clock.jump_to(start_dt)

    # 4. Preload cache & build fresh schedule for Day 1
    await preload_telemetry_cache(start_dt)
    await _build_schedule_for_date(start_dt.date(), start_dt)

    # 5. Push battery configuration over MQTT to simulator
    from ems.api.settings import battery_config_payload
    payload = battery_config_payload(current_bat)
    payload.update(
        {
            "capacity_kwh": template.battery_capacity_kwh,
            "power_max_kw": template.battery_power_kw,
            "soc_min_pct": template.soc_min_pct,
            "soc_max_pct": template.soc_max_pct,
            "initial_soc_pct": template.initial_soc_pct,
        }
    )
    import asyncio
    asyncio.create_task(_publish_bess_config(payload))

    logger.info(
        "Successfully applied simulation template '%s': %d-day window (%s to %s)",
        template.name,
        effective_loop_days,
        start_dt.date(),
        end_dt.date(),
    )

    return {
        "status": "applied",
        "template": template.model_dump(),
        "effective_loop_days": effective_loop_days,
        "loop_start": start_dt.isoformat(),
        "loop_end": end_dt.isoformat(),
    }


async def compute_template_report(template_id: str, days: int | None = None) -> dict[str, Any]:
    """Compute comprehensive analytical performance and savings report for a template."""
    import numpy as np
    from sqlalchemy import select

    from ems.db.models import DamPrice
    from ems.db.session import async_session_factory
    from ems.market.simulator import MarketTariffs, calculate_buy_price, calculate_sell_price
    from ems.optimization.milp import OptimizationProblem, solve

    template = get_template(template_id)
    if not template:
        raise ValueError(f"Template '{template_id}' not found.")

    effective_days = min(template.max_loop_days, max(1, days or template.duration_days))
    start_dt = datetime.fromisoformat(template.start_time.replace("Z", "+00:00"))
    tariffs_cfg = MarketTariffs()

    daily_reports: list[dict[str, Any]] = []
    tot_baseline = 0.0
    tot_actual = 0.0
    tot_savings = 0.0
    tot_deg_cost = 0.0
    tot_charged_kwh = 0.0
    tot_discharged_kwh = 0.0
    tot_pv_kwh = 0.0
    tot_load_kwh = 0.0
    max_baseline_peak_kw = 0.0
    max_actual_peak_kw = 0.0

    for d in range(effective_days):
        day_date = start_dt.date() + timedelta(days=d)
        day_start = datetime(day_date.year, day_date.month, day_date.day, 0, 0, 0, tzinfo=UTC)
        day_end = datetime(day_date.year, day_date.month, day_date.day, 23, 0, 0, tzinfo=UTC)
        timestamps = [day_start + timedelta(hours=h) for h in range(24)]

        # Fetch DAM prices for this day from DB or fallback CSV / generator
        prices_mwh: list[float] = []
        try:
            async with async_session_factory() as session:
                stmt = (
                    select(DamPrice.ts, DamPrice.price_uah_mwh)
                    .where(DamPrice.ts >= day_start, DamPrice.ts <= day_end)
                    .order_by(DamPrice.ts)
                )
                res = await session.execute(stmt)
                p_dict = {ts: float(p) for ts, p in res.all()}
                if len(p_dict) >= 24:
                    prices_mwh = [p_dict[ts] for ts in timestamps]
        except Exception:
            pass

        if len(prices_mwh) < 24:
            # Check if we have the September 2026 CSV file
            csv_path = (
                Path(__file__).resolve().parent.parent.parent.parent
                / "data"
                / "samples"
                / "dam_prices_september_2026.csv"
            )
            if not csv_path.exists():
                csv_path = Path(__file__).resolve().parent.parent / "ingestion" / "dam_prices_september_2026.csv"
            if csv_path.exists():
                import pandas as pd

                df_csv = pd.read_csv(csv_path)
                df_day = df_csv[df_csv["date"] == day_date.isoformat()].sort_values("hour")
                if len(df_day) == 24:
                    prices_mwh = [float(x) for x in df_day["price_uah_mwh"]]

        if len(prices_mwh) < 24:
            # Fallback to generator / synthetic if DB or CSV doesn't have exact day
            from ems.ingestion.generator import SyntheticDataGenerator

            gen = SyntheticDataGenerator(seed=42)
            df_p = gen.generate_dam_prices(day_start, day_end)
            prices_mwh = [float(r["price_uah_mwh"]) for _, r in df_p.iterrows()]

        # Generate load & PV curves
        load_kw: list[float] = []
        pv_kw: list[float] = []
        for h in range(24):
            if 7 <= h < 23:
                load_kw.append(template.site_day_load_kw)
            else:
                load_kw.append(template.site_night_load_kw)

            if 8 <= h <= 17:
                solar_frac = np.sin(np.pi * (h - 7) / 11)
                pv_kw.append(max(0.0, float(template.pv_peak_kw * solar_frac)))
            else:
                pv_kw.append(0.0)

        prices_buy = [calculate_buy_price(p, tariffs_cfg) / 1000.0 for p in prices_mwh]
        prices_sell = [calculate_sell_price(p, tariffs_cfg) / 1000.0 for p in prices_mwh]

        # 1. Baseline calculation without BESS
        day_baseline_cost = 0.0
        day_baseline_peak = 0.0
        for h in range(24):
            net_base = max(0.0, load_kw[h] - pv_kw[h])
            day_baseline_cost += net_base * prices_buy[h]
            if net_base > day_baseline_peak:
                day_baseline_peak = net_base

        # 2. Optimized schedule with BESS
        prob = OptimizationProblem(
            timestamps=timestamps,
            price_buy_uah_kwh=prices_buy,
            price_sell_uah_kwh=prices_sell,
            load_kw=load_kw,
            pv_kw=pv_kw,
            capacity_kwh=template.battery_capacity_kwh,
            max_charge_kw=template.battery_power_kw,
            max_discharge_kw=template.battery_power_kw,
            soc_min_pct=template.soc_min_pct,
            soc_max_pct=template.soc_max_pct,
            initial_soc_pct=template.initial_soc_pct,
            soc_end_target_pct=template.initial_soc_pct,
            reserve_soc_pct=template.reserve_soc_pct,
            export_allowed=True,
            c_deg_uah_kwh=1.25,
        )
        sched = solve(prob)

        day_actual_cost = 0.0
        day_deg_cost = 0.0
        day_charged = 0.0
        day_discharged = 0.0
        day_actual_peak = 0.0

        for h, item in enumerate(sched.items):
            p_bess = item.setpoint_kw
            if p_bess > 0:
                day_charged += p_bess
            else:
                day_discharged += abs(p_bess)

            net_facility = load_kw[h] - pv_kw[h] + p_bess
            g_imp = max(0.0, net_facility)
            g_exp = max(0.0, -net_facility)
            if g_imp > day_actual_peak:
                day_actual_peak = g_imp

            day_actual_cost += g_imp * prices_buy[h] - g_exp * prices_sell[h]
            day_deg_cost += 1.25 * abs(p_bess)

        day_net_saving = day_baseline_cost - day_actual_cost - day_deg_cost
        day_cycles = (day_charged + day_discharged) / (2.0 * template.battery_capacity_kwh)

        daily_reports.append(
            {
                "date": day_date.isoformat(),
                "day_index": d + 1,
                "baseline_cost_uah": round(day_baseline_cost, 2),
                "actual_cost_uah": round(day_actual_cost, 2),
                "degradation_uah": round(day_deg_cost, 2),
                "net_saving_uah": round(day_net_saving, 2),
                "saving_pct": round((day_net_saving / day_baseline_cost * 100) if day_baseline_cost > 0 else 0, 1),
                "cycles": round(day_cycles, 2),
                "charged_kwh": round(day_charged, 1),
                "discharged_kwh": round(day_discharged, 1),
                "baseline_peak_kw": round(day_baseline_peak, 1),
                "actual_peak_kw": round(day_actual_peak, 1),
                "peak_reduction_kw": round(max(0.0, day_baseline_peak - day_actual_peak), 1),
            }
        )

        tot_baseline += day_baseline_cost
        tot_actual += day_actual_cost
        tot_deg_cost += day_deg_cost
        tot_savings += day_net_saving
        tot_charged_kwh += day_charged
        tot_discharged_kwh += day_discharged
        tot_pv_kwh += sum(pv_kw)
        tot_load_kwh += sum(load_kw)
        max_baseline_peak_kw = max(max_baseline_peak_kw, day_baseline_peak)
        max_actual_peak_kw = max(max_actual_peak_kw, day_actual_peak)

    total_cycles = (tot_charged_kwh + tot_discharged_kwh) / (2.0 * template.battery_capacity_kwh)
    peak_reduction_pct = (
        ((max_baseline_peak_kw - max_actual_peak_kw) / max_baseline_peak_kw * 100)
        if max_baseline_peak_kw > 0
        else 0.0
    )

    summary_dict = {
        "baseline_cost_uah": round(tot_baseline, 2),
        "actual_cost_uah": round(tot_actual, 2),
        "battery_degradation_uah": round(tot_deg_cost, 2),
        "degradation_uah": round(tot_deg_cost, 2),
        "net_savings_uah": round(tot_savings, 2),
        "net_savings_pct": round((tot_savings / tot_baseline * 100) if tot_baseline > 0 else 0, 1),
        "savings_pct": round((tot_savings / tot_baseline * 100) if tot_baseline > 0 else 0, 1),
        "equivalent_cycles": round(total_cycles, 2),
        "total_cycles": round(total_cycles, 2),
        "avg_daily_savings_uah": round(tot_savings / effective_days, 2),
        "projected_monthly_savings_uah": round((tot_savings / effective_days) * 30, 2),
        "projected_annual_savings_uah": round((tot_savings / effective_days) * 365, 2),
        "baseline_max_peak_kw": round(max_baseline_peak_kw, 1),
        "actual_max_peak_kw": round(max_actual_peak_kw, 1),
        "peak_reduction_kw": round(max(0.0, max_baseline_peak_kw - max_actual_peak_kw), 1),
        "peak_shaving_kw": round(max(0.0, max_baseline_peak_kw - max_actual_peak_kw), 1),
        "peak_reduction_pct": round(max(0.0, peak_reduction_pct), 1),
        "peak_shaving_pct": round(max(0.0, peak_reduction_pct), 1),
        "total_charged_kwh": round(tot_charged_kwh, 1),
        "total_discharged_kwh": round(tot_discharged_kwh, 1),
        "total_pv_generation_kwh": round(tot_pv_kwh, 1),
        "total_pv_kwh": round(tot_pv_kwh, 1),
        "total_facility_load_kwh": round(tot_load_kwh, 1),
        "total_load_kwh": round(tot_load_kwh, 1),
    }

    return {
        "template_id": template.id,
        "template_name": template.name,
        "template": template.model_dump(),
        "horizon_days": effective_days,
        "analyzed_days": effective_days,
        "start_date": start_dt.date().isoformat(),
        "end_date": (start_dt.date() + timedelta(days=effective_days - 1)).isoformat(),
        "battery": {
            "capacity_kwh": template.battery_capacity_kwh,
            "power_kw": template.battery_power_kw,
        },
        "kpi": summary_dict,
        "summary": summary_dict,
        "daily": daily_reports,
        "daily_breakdown": daily_reports,
    }
