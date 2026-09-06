"""Hourly financial calculations and settlement (SPEC §6.2, §7)."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ems.db.models import Financial


@dataclass
class FinancialHourResult:
    """Financial settlement for one simulated hour."""

    ts: datetime
    import_kwh: float
    export_kwh: float
    price_buy: float
    price_sell: float
    cost_baseline_uah: float
    cost_actual_uah: float
    revenue_uah: float
    degradation_uah: float
    net_uah: float


def compute_hourly_financials(
    ts: datetime,
    load_kwh: float,
    pv_kwh: float,
    charge_kwh: float,
    discharge_kwh: float,
    price_buy_uah_mwh: float,
    price_sell_uah_mwh: float,
    c_deg_uah_kwh: float = 1.25,
    aux_kwh: float = 0.0,
) -> FinancialHourResult:
    """Calculate hourly financial metrics matching SPEC §6.2.

    Baseline: Without BESS (Import = max(0, load - pv)).
    Actual: With BESS (Net = load + aux - pv + charge - discharge).

    ``aux_kwh`` is the BESS auxiliary consumption (HVAC, BMS, PCS idle). It exists
    only because the battery is installed, so it is charged to the actual case and
    left out of the baseline — otherwise the auxiliaries cancel out of the net
    benefit and appear free.
    """
    # 1. Baseline calculation (Facility without battery storage)
    baseline_import_kwh = max(0.0, load_kwh - pv_kwh)
    cost_baseline_uah = baseline_import_kwh * (price_buy_uah_mwh / 1000.0)

    # 2. Actual system with BESS
    net_flow_kwh = load_kwh + aux_kwh - pv_kwh + charge_kwh - discharge_kwh
    if net_flow_kwh >= 0.0:
        actual_import_kwh = net_flow_kwh
        actual_export_kwh = 0.0
    else:
        actual_import_kwh = 0.0
        actual_export_kwh = abs(net_flow_kwh)

    cost_actual_uah = actual_import_kwh * (price_buy_uah_mwh / 1000.0)
    revenue_uah = actual_export_kwh * (price_sell_uah_mwh / 1000.0)
    degradation_uah = c_deg_uah_kwh * (charge_kwh + discharge_kwh)

    # Net financial benefit (savings + revenue - battery degradation cost)
    net_uah = (cost_baseline_uah - cost_actual_uah) + revenue_uah - degradation_uah

    return FinancialHourResult(
        ts=ts,
        import_kwh=round(actual_import_kwh, 3),
        export_kwh=round(actual_export_kwh, 3),
        price_buy=round(price_buy_uah_mwh, 2),
        price_sell=round(price_sell_uah_mwh, 2),
        cost_baseline_uah=round(cost_baseline_uah, 2),
        cost_actual_uah=round(cost_actual_uah, 2),
        revenue_uah=round(revenue_uah, 2),
        degradation_uah=round(degradation_uah, 2),
        net_uah=round(net_uah, 2),
    )


async def record_hourly_financials(
    result: FinancialHourResult,
    session: AsyncSession,
) -> Financial:
    """Persist hourly financial record into TimescaleDB table 'financials'."""
    stmt = insert(Financial).values(
        ts=result.ts,
        import_kwh=result.import_kwh,
        export_kwh=result.export_kwh,
        price_buy=result.price_buy,
        price_sell=result.price_sell,
        cost_baseline_uah=result.cost_baseline_uah,
        cost_actual_uah=result.cost_actual_uah,
        revenue_uah=result.revenue_uah,
        degradation_uah=result.degradation_uah,
        net_uah=result.net_uah,
    )
    # Upsert on timestamp conflict
    stmt = stmt.on_conflict_do_update(
        index_elements=["ts"],
        set_={
            "import_kwh": result.import_kwh,
            "export_kwh": result.export_kwh,
            "price_buy": result.price_buy,
            "price_sell": result.price_sell,
            "cost_baseline_uah": result.cost_baseline_uah,
            "cost_actual_uah": result.cost_actual_uah,
            "revenue_uah": result.revenue_uah,
            "degradation_uah": result.degradation_uah,
            "net_uah": result.net_uah,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return Financial(**result.__dict__)
