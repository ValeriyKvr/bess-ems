"""Financial reporting and strategy comparison endpoints (SPEC §10.1, §11)."""

import csv
import io
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ems.api.settings import get_battery_settings, get_strategy_settings
from ems.db.models import DamPrice, Financial, SiteLoad
from ems.db.session import get_db
from ems.market.financials import compute_hourly_financials
from ems.market.simulator import calculate_buy_price, calculate_sell_price
from ems.optimization.strategies import ScheduleContext, get_strategy

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/summary")
async def get_report_summary(
    from_date: str | None = Query(None, alias="from", description="Start timestamp ISO 8601"),
    to_date: str | None = Query(None, alias="to", description="End timestamp ISO 8601"),
    report_format: str = Query(
        "json", alias="format", description="Output format: 'json', 'xlsx', or 'csv'"
    ),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Retrieve financial summary KPIs and hourly breakdown with export options (SPEC §10.1(5), §11)."""
    start_dt: datetime | None = None
    end_dt: datetime | None = None

    if from_date:
        try:
            start_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
        except Exception:
            pass
    if to_date:
        try:
            end_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
        except Exception:
            pass

    stmt = select(Financial).order_by(Financial.ts.asc())
    if start_dt:
        stmt = stmt.where(Financial.ts >= start_dt)
    if end_dt:
        stmt = stmt.where(Financial.ts <= end_dt)

    res = await db.execute(stmt)
    rows = list(res.scalars().all())

    # Calculate KPIs
    total_cost_baseline = sum(r.cost_baseline_uah for r in rows)
    total_cost_actual = sum(r.cost_actual_uah for r in rows)
    net_savings = total_cost_baseline - total_cost_actual
    export_revenue = sum(r.revenue_uah for r in rows)
    degradation_cost = sum(r.degradation_uah for r in rows)
    net_benefit = sum(r.net_uah for r in rows)
    total_import = sum(r.import_kwh for r in rows)
    total_export = sum(r.export_kwh for r in rows)

    bat_cfg = await get_battery_settings(db)
    capacity = bat_cfg.capacity_kwh if bat_cfg.capacity_kwh > 0 else 1000.0
    capex_uah = bat_cfg.capex_uah if bat_cfg.capex_uah > 0 else 15000000.0

    # Approximate cycles: degradation / c_deg / (2 * capacity)
    equivalent_cycles = degradation_cost / (1.25 * 2.0 * capacity) if capacity > 0 else 0.0

    # Simple payback (years) based on period net benefit extrapolated to 365 days
    hours_count = len(rows)
    payback_years: float | None = None
    if hours_count > 0 and net_benefit > 0:
        annual_benefit = (net_benefit / hours_count) * 8760.0
        if annual_benefit > 0:
            payback_years = round(capex_uah / annual_benefit, 2)

    hourly_data = [
        {
            "ts": r.ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cost_baseline_uah": round(r.cost_baseline_uah, 2),
            "cost_actual_uah": round(r.cost_actual_uah, 2),
            "net_savings_uah": round(r.cost_baseline_uah - r.cost_actual_uah, 2),
            "revenue_uah": round(r.revenue_uah, 2),
            "degradation_uah": round(r.degradation_uah, 2),
            "net_uah": round(r.net_uah, 2),
            "import_kwh": round(r.import_kwh, 2),
            "export_kwh": round(r.export_kwh, 2),
            "price_buy": round(r.price_buy, 2),
            "price_sell": round(r.price_sell, 2),
        }
        for r in rows
    ]

    summary_kpis = {
        "total_cost_baseline_uah": round(total_cost_baseline, 2),
        "total_cost_actual_uah": round(total_cost_actual, 2),
        "net_savings_uah": round(net_savings, 2),
        "export_revenue_uah": round(export_revenue, 2),
        "degradation_uah": round(degradation_cost, 2),
        "net_benefit_uah": round(net_benefit, 2),
        "total_import_kwh": round(total_import, 2),
        "total_export_kwh": round(total_export, 2),
        "equivalent_cycles": round(equivalent_cycles, 2),
        "payback_years": payback_years,
        "hours_count": hours_count,
    }

    date_suffix = f"{start_dt.strftime('%Y%m%d') if start_dt else 'start'}_{end_dt.strftime('%Y%m%d') if end_dt else 'end'}"

    if report_format.lower() == "csv":
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(
            [
                "Час (UTC)",
                "Базова вартість (грн)",
                "Фактична вартість (грн)",
                "Економія (грн)",
                "Дохід від експорту (грн)",
                "Вартість деградації (грн)",
                "Чистий ефект (грн)",
                "Імпорт з мережі (кВт·год)",
                "Експорт у мережу (кВт·год)",
                "Ціна покупки (грн/МВт·год)",
                "Ціна продажу (грн/МВт·год)",
            ]
        )
        for row in hourly_data:
            writer.writerow(
                [
                    row["ts"],
                    row["cost_baseline_uah"],
                    row["cost_actual_uah"],
                    row["net_savings_uah"],
                    row["revenue_uah"],
                    row["degradation_uah"],
                    row["net_uah"],
                    row["import_kwh"],
                    row["export_kwh"],
                    row["price_buy"],
                    row["price_sell"],
                ]
            )
        csv_text = csv_buffer.getvalue()
        return Response(
            content=csv_text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=ems_report_{date_suffix}.csv"},
        )

    elif report_format.lower() == "xlsx":
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            # Sheet 1: Summary
            summary_df = pd.DataFrame(
                [
                    {
                        "Показник": "Базова вартість без BESS",
                        "Значення": summary_kpis["total_cost_baseline_uah"],
                        "Одиниця": "грн",
                    },
                    {
                        "Показник": "Фактична вартість з BESS",
                        "Значення": summary_kpis["total_cost_actual_uah"],
                        "Одиниця": "грн",
                    },
                    {
                        "Показник": "Чиста економія на споживанні",
                        "Значення": summary_kpis["net_savings_uah"],
                        "Одиниця": "грн",
                    },
                    {
                        "Показник": "Дохід від експорту в мережу",
                        "Значення": summary_kpis["export_revenue_uah"],
                        "Одиниця": "грн",
                    },
                    {
                        "Показник": "Оцінка вартості деградації BESS",
                        "Значення": summary_kpis["degradation_uah"],
                        "Одиниця": "грн",
                    },
                    {
                        "Показник": "Загальний фінансовий ефект (Net)",
                        "Значення": summary_kpis["net_benefit_uah"],
                        "Одиниця": "грн",
                    },
                    {
                        "Показник": "Сумарний імпорт з мережі",
                        "Значення": summary_kpis["total_import_kwh"],
                        "Одиниця": "кВт·год",
                    },
                    {
                        "Показник": "Сумарний експорт в мережу",
                        "Значення": summary_kpis["total_export_kwh"],
                        "Одиниця": "кВт·год",
                    },
                    {
                        "Показник": "Еквівалентна кількість циклів",
                        "Значення": summary_kpis["equivalent_cycles"],
                        "Одиниця": "цикли",
                    },
                    {
                        "Показник": "Простий термін окупності (Payback)",
                        "Значення": summary_kpis["payback_years"]
                        if summary_kpis["payback_years"]
                        else "N/A",
                        "Одиниця": "років",
                    },
                    {
                        "Показник": "Кількість проаналізованих годин",
                        "Значення": summary_kpis["hours_count"],
                        "Одиниця": "год",
                    },
                ]
            )
            summary_df.to_excel(writer, sheet_name="Підсумок", index=False)

            # Sheet 2: Hourly breakdown
            if hourly_data:
                hourly_df = pd.DataFrame(hourly_data)
                hourly_df.rename(
                    columns={
                        "ts": "Час (UTC)",
                        "cost_baseline_uah": "Базова вартість (грн)",
                        "cost_actual_uah": "Фактична вартість (грн)",
                        "net_savings_uah": "Економія (грн)",
                        "revenue_uah": "Дохід експорт (грн)",
                        "degradation_uah": "Деградація (грн)",
                        "net_uah": "Чистий ефект (грн)",
                        "import_kwh": "Імпорт (кВт·год)",
                        "export_kwh": "Експорт (кВт·год)",
                        "price_buy": "Ціна покупки (грн/МВт·год)",
                        "price_sell": "Ціна продажу (грн/МВт·год)",
                    },
                    inplace=True,
                )
                hourly_df.to_excel(writer, sheet_name="Погодинна деталізація", index=False)
            else:
                pd.DataFrame(
                    [{"Повідомлення": "Немає погодинних даних за обраний період"}]
                ).to_excel(writer, sheet_name="Погодинна деталізація", index=False)

        excel_bytes = excel_buffer.getvalue()
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=ems_report_{date_suffix}.xlsx"},
        )

    return {
        "from": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if start_dt else None,
        "to": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if end_dt else None,
        "summary": summary_kpis,
        "hourly": hourly_data,
    }


@router.get("/compare-strategies")
async def compare_strategies(
    target_date: str | None = Query(None, alias="date", description="Target date YYYY-MM-DD"),
    strategies_str: str = Query(
        "TOU_SIMPLE,ARBITRAGE,PEAK_SHAVING,SELF_CONSUMPTION",
        alias="strategies",
        description="Comma-separated strategy names",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run isolated in-memory simulation comparison across strategies on a 24h horizon (SPEC §10.1(5))."""
    if target_date:
        try:
            d = datetime.strptime(target_date, "%Y-%m-%d").date()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid date format: {e}") from e
    else:
        d = datetime.now(UTC).date()

    start_dt = datetime(d.year, d.month, d.day, 0, 0, tzinfo=UTC)
    end_dt = start_dt + timedelta(hours=23)

    # 1. Fetch DAM prices and load from DB
    stmt_p = (
        select(DamPrice).where(DamPrice.ts >= start_dt, DamPrice.ts <= end_dt).order_by(DamPrice.ts)
    )
    res_p = await db.execute(stmt_p)
    dam_rows = list(res_p.scalars().all())

    stmt_l = (
        select(SiteLoad).where(SiteLoad.ts >= start_dt, SiteLoad.ts <= end_dt).order_by(SiteLoad.ts)
    )
    res_l = await db.execute(stmt_l)
    load_rows = list(res_l.scalars().all())

    # If insufficient data in DB, synthesize 24h
    from ems.ingestion.generator import SyntheticDataGenerator
    from ems.market.simulator import MarketTariffs

    tariffs_cfg = MarketTariffs()

    if len(dam_rows) < 24 or len(load_rows) < 24:
        gen = SyntheticDataGenerator(seed=42)
        gen_prices = gen.generate_dam_prices(start_dt, end_dt)
        gen_load = gen.generate_site_load(start_dt, end_dt)
        price_list = [
            {
                "ts": row["ts"],
                "price_dam": row["price_uah_mwh"],
                "price_buy": calculate_buy_price(row["price_uah_mwh"], tariffs_cfg),
                "price_sell": calculate_sell_price(row["price_uah_mwh"], tariffs_cfg),
            }
            for _, row in gen_prices.iterrows()
        ]
        load_list = list(gen_load["load_kw"])
        pv_list = list(gen_load["pv_kw"])
    else:
        price_list = [
            {
                "ts": r.ts,
                "price_dam": r.price_uah_mwh,
                "price_buy": calculate_buy_price(r.price_uah_mwh, tariffs_cfg),
                "price_sell": calculate_sell_price(r.price_uah_mwh, tariffs_cfg),
            }
            for r in dam_rows[:24]
        ]
        load_list = [r.load_kw for r in load_rows[:24]]
        pv_list = [r.pv_kw for r in load_rows[:24]]

    bat_cfg = await get_battery_settings(db)
    strat_cfg = await get_strategy_settings(db)

    strategy_names = [s.strip().upper() for s in strategies_str.split(",") if s.strip()]
    comparison_results: list[dict[str, Any]] = []

    for strat_name in strategy_names:
        context = ScheduleContext(
            current_time=start_dt,
            horizon_start=start_dt,
            horizon_end=end_dt,
            soc_pct=50.0,
            capacity_kwh=bat_cfg.capacity_kwh,
            max_charge_kw=bat_cfg.power_max_kw,
            max_discharge_kw=bat_cfg.power_max_kw,
            soc_min_pct=bat_cfg.soc_min_pct,
            soc_max_pct=bat_cfg.soc_max_pct,
            reserve_soc_pct=strat_cfg.reserve_soc_pct,
            peak_limit_kw=strat_cfg.peak_limit_kw,
            prices=price_list,
            load_series=load_list,
            pv_series=pv_list,
        )

        try:
            strategy_obj = get_strategy(strat_name)
            schedule = strategy_obj.build_schedule(context)

            # Evaluate 24h operational results
            tot_baseline = 0.0
            tot_actual = 0.0
            tot_revenue = 0.0
            tot_degradation = 0.0
            tot_charge = 0.0
            tot_discharge = 0.0

            for h in range(min(24, len(schedule.items))):
                item = schedule.items[h]
                p_set = item.setpoint_kw
                ch_kwh = max(0.0, p_set)
                dis_kwh = max(0.0, -p_set)
                tot_charge += ch_kwh
                tot_discharge += dis_kwh

                fin = compute_hourly_financials(
                    ts=item.ts,
                    load_kwh=load_list[h] if h < len(load_list) else 100.0,
                    pv_kwh=pv_list[h] if h < len(pv_list) else 0.0,
                    charge_kwh=ch_kwh,
                    discharge_kwh=dis_kwh,
                    price_buy_uah_mwh=price_list[h]["price_buy"],
                    price_sell_uah_mwh=price_list[h]["price_sell"],
                )
                tot_baseline += fin.cost_baseline_uah
                tot_actual += fin.cost_actual_uah
                tot_revenue += fin.revenue_uah
                tot_degradation += fin.degradation_uah

            tot_net = (tot_baseline - tot_actual) + tot_revenue - tot_degradation
            capacity = bat_cfg.capacity_kwh if bat_cfg.capacity_kwh > 0 else 1000.0
            equiv_cycles = (tot_charge + tot_discharge) / (2.0 * capacity)

            comparison_results.append(
                {
                    "strategy": strat_name,
                    "baseline_cost_uah": round(tot_baseline, 2),
                    "actual_cost_uah": round(tot_actual, 2),
                    "net_savings_uah": round(tot_baseline - tot_actual, 2),
                    "export_revenue_uah": round(tot_revenue, 2),
                    "degradation_uah": round(tot_degradation, 2),
                    "net_benefit_uah": round(tot_net, 2),
                    "total_charge_kwh": round(tot_charge, 2),
                    "total_discharge_kwh": round(tot_discharge, 2),
                    "equivalent_cycles": round(equiv_cycles, 2),
                    "solver_status": schedule.solver_status,
                    "solve_time_ms": schedule.solve_time_ms,
                }
            )
        except Exception as e:
            logger.warning("Failed to simulate strategy %s: %s", strat_name, e)
            comparison_results.append(
                {
                    "strategy": strat_name,
                    "error": str(e),
                    "baseline_cost_uah": 0.0,
                    "actual_cost_uah": 0.0,
                    "net_benefit_uah": 0.0,
                }
            )

    return {
        "date": d.strftime("%Y-%m-%d"),
        "comparison": comparison_results,
    }
