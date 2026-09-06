"""Data ingestion, generation, and series retrieval API endpoints (SPEC §11)."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ems.db.models import DamPrice, SiteLoad
from ems.db.session import get_db
from ems.ingestion.generator import SyntheticDataGenerator
from ems.ingestion.importer import CsvDataImporter, CsvValidationError

router = APIRouter(prefix="/data", tags=["Data"])


class GenerateDataRequest(BaseModel):
    """Payload for POST /api/data/generate."""

    start_date: str = Field(default="2024-01-01T00:00:00Z")
    end_date: str = Field(default="2026-03-31T23:00:00Z")
    seed: int = Field(default=42)
    overwrite: bool = Field(default=False)


@router.post("/generate")
async def generate_synthetic_data(
    payload: GenerateDataRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate synthetic time series for DAM prices and industrial site load."""
    try:
        start_dt = datetime.fromisoformat(payload.start_date.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(payload.end_date.replace("Z", "+00:00"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}") from e

    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="end_date must be after start_date")

    gen = SyntheticDataGenerator(seed=payload.seed)

    # 1. Generate DAM prices
    df_prices = gen.generate_dam_prices(start_dt, end_dt)
    price_records = df_prices.to_dict(orient="records")

    # 2. Generate site load & PV
    df_load = gen.generate_site_load(start_dt, end_dt)
    load_records = df_load.to_dict(orient="records")

    if payload.overwrite:
        await db.execute(delete(DamPrice).where(DamPrice.ts >= start_dt, DamPrice.ts <= end_dt))
        await db.execute(delete(SiteLoad).where(SiteLoad.ts >= start_dt, SiteLoad.ts <= end_dt))

    # Bulk upsert DAM prices
    if price_records:
        stmt_prices = insert(DamPrice).values(price_records).on_conflict_do_nothing()
        await db.execute(stmt_prices)

    # Bulk upsert Site load
    if load_records:
        stmt_load = insert(SiteLoad).values(load_records).on_conflict_do_nothing()
        await db.execute(stmt_load)

    await db.commit()

    return {
        "status": "success",
        "prices_count": len(price_records),
        "load_count": len(load_records),
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "seed": payload.seed,
    }


@router.post("/import")
async def import_csv_data(
    file: UploadFile = File(...),
    data_type: str = Query(..., alias="type", description="Type of data: 'price' or 'load'"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Import time series data from CSV file."""
    content = await file.read()
    importer = CsvDataImporter()

    try:
        if data_type == "price":
            df = importer.import_dam_prices(content)
            records = df.to_dict(orient="records")
            if records:
                stmt = insert(DamPrice).values(records).on_conflict_do_nothing()
                await db.execute(stmt)
                await db.commit()
            return {"status": "success", "imported_rows": len(records), "type": "price"}

        elif data_type == "load":
            df = importer.import_site_load(content)
            records = df.to_dict(orient="records")
            if records:
                stmt = insert(SiteLoad).values(records).on_conflict_do_nothing()
                await db.execute(stmt)
                await db.commit()
            return {"status": "success", "imported_rows": len(records), "type": "load"}
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported type '{data_type}'. Use 'price' or 'load'."
            )

    except CsvValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/preview")
async def preview_csv_data(
    file: UploadFile = File(...),
    data_type: str | None = Query(
        None, alias="type", description="Optional data type: 'price' or 'load'"
    ),
) -> dict[str, Any]:
    """Preview uploaded CSV file (first 20 rows) and validate format (SPEC §10.1)."""
    import io

    import pandas as pd

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        df_raw = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        return {
            "detected_type": "unknown",
            "columns": [],
            "total_rows": 0,
            "preview_rows": [],
            "is_valid": False,
            "errors": [f"CSV parsing error: {e}"],
        }

    columns = [str(c).strip() for c in df_raw.columns]
    col_lower = {c.strip().lower() for c in df_raw.columns}
    total_rows = len(df_raw)

    # Detect type if not provided
    detected_type = data_type
    if not detected_type:
        if {"date", "hour", "price_uah_mwh"}.issubset(col_lower):
            detected_type = "price"
        elif {"ts", "load_kw"}.issubset(col_lower):
            detected_type = "load"
        else:
            detected_type = "unknown"

    # Preview up to 20 rows
    preview_df = df_raw.head(20).copy()
    preview_df = preview_df.fillna("")
    preview_rows = preview_df.to_dict(orient="records")

    # Run validation
    is_valid = True
    errors: list[str] = []
    importer = CsvDataImporter()

    if detected_type == "price":
        try:
            importer.import_dam_prices(content)
        except Exception as e:
            is_valid = False
            errors.append(str(e))
    elif detected_type == "load":
        try:
            importer.import_site_load(content)
        except Exception as e:
            is_valid = False
            errors.append(str(e))
    else:
        is_valid = False
        errors.append(
            f"Unable to recognize data schema from columns {columns}. "
            "Expected 'date,hour,price_uah_mwh' for DAM prices or 'ts,load_kw,pv_kw' for site load."
        )

    return {
        "detected_type": detected_type,
        "columns": columns,
        "total_rows": total_rows,
        "preview_rows": preview_rows,
        "is_valid": is_valid,
        "errors": errors,
    }


@router.get("/heatmap")
async def get_data_heatmap(
    data_type: str = Query("price", alias="type", description="'price' or 'load'"),
    from_date: str | None = Query(None, alias="from", description="Start timestamp ISO 8601"),
    to_date: str | None = Query(None, alias="to", description="End timestamp ISO 8601"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve 24h x 7d average distribution heatmap (SPEC §10.1)."""
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

    if data_type == "price":
        stmt = select(DamPrice.ts, DamPrice.price_uah_mwh)
        if start_dt:
            stmt = stmt.where(DamPrice.ts >= start_dt)
        if end_dt:
            stmt = stmt.where(DamPrice.ts <= end_dt)
        stmt = stmt.order_by(DamPrice.ts.desc()).limit(24 * 90)  # Up to 90 days
        res = await db.execute(stmt)
        rows = res.all()
        unit = "грн/МВт·год"
        records = [(r[0], float(r[1])) for r in rows if r[1] is not None]
    elif data_type == "load":
        stmt = select(SiteLoad.ts, SiteLoad.load_kw)
        if start_dt:
            stmt = stmt.where(SiteLoad.ts >= start_dt)
        if end_dt:
            stmt = stmt.where(SiteLoad.ts <= end_dt)
        stmt = stmt.order_by(SiteLoad.ts.desc()).limit(24 * 90)
        res = await db.execute(stmt)
        rows = res.all()
        unit = "кВт"
        records = [(r[0], float(r[1])) for r in rows if r[1] is not None]
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported heatmap type '{data_type}'.")

    # Aggregate by (hour 0..23, dow 0..6)
    accum: dict[tuple[int, int], list[float]] = {}
    for ts, val in records:
        h = ts.hour
        dow = ts.weekday()  # 0=Monday, 6=Sunday
        accum.setdefault((h, dow), []).append(val)

    data_points: list[list[Any]] = []
    all_vals: list[float] = []

    for dow in range(7):
        for h in range(24):
            vals = accum.get((h, dow), [])
            avg_val = round(sum(vals) / len(vals), 2) if vals else 0.0
            data_points.append([h, dow, avg_val])
            if vals:
                all_vals.append(avg_val)

    min_val = min(all_vals) if all_vals else 0.0
    max_val = max(all_vals) if all_vals else 0.0

    return {
        "type": data_type,
        "x_categories": [f"{h:02d}:00" for h in range(24)],
        "y_categories": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"],
        "data": data_points,
        "min_value": min_val,
        "max_value": max_val,
        "unit": unit,
        "total_samples": len(records),
    }


@router.get("/series")
async def get_time_series(
    series_type: str = Query(..., alias="type", description="Type: 'price', 'load', 'pv'"),
    from_date: str = Query(..., alias="from", description="Start timestamp ISO 8601"),
    to_date: str = Query(..., alias="to", description="End timestamp ISO 8601"),
    step: str = Query("1h", description="Resampling step: '1h' or '15min'"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve historical/synthetic time series within the specified interval."""
    try:
        start_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp format: {e}") from e

    if series_type == "price":
        stmt = (
            select(DamPrice)
            .where(DamPrice.ts >= start_dt, DamPrice.ts <= end_dt)
            .order_by(DamPrice.ts)
        )
        res = await db.execute(stmt)
        rows = res.scalars().all()
        data = [{"ts": r.ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "value": r.price_uah_mwh} for r in rows]

    elif series_type in ("load", "pv"):
        stmt = (
            select(SiteLoad)
            .where(SiteLoad.ts >= start_dt, SiteLoad.ts <= end_dt)
            .order_by(SiteLoad.ts)
        )
        res = await db.execute(stmt)
        rows = res.scalars().all()
        if series_type == "load":
            data = [{"ts": r.ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "value": r.load_kw} for r in rows]
        else:
            data = [{"ts": r.ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "value": r.pv_kw} for r in rows]
    else:
        raise HTTPException(status_code=400, detail=f"Unknown series type '{series_type}'")

    return {
        "type": series_type,
        "step": step,
        "count": len(data),
        "data": data,
    }
