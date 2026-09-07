"""Machine learning management and forecast query REST APIs (SPEC §11)."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, update

from ems.db.models import Forecast, MlModel
from ems.db.session import async_session_factory
from ems.forecasting.backtest import run_economic_backtest
from ems.forecasting.train import train_model_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ml"])


class TrainRequest(BaseModel):
    """Payload for POST /api/ml/train."""

    target: Literal["price", "load"] = "price"
    model: Literal["naive", "lightgbm", "lstm"] = "lightgbm"
    version: str = Field(default="v1.0.0")
    from_date: str = Field(default="2024-01-01")
    to_date: str = Field(default="2025-12-31")


@router.get("/ml/models")
async def list_models() -> list[dict[str, Any]]:
    """List registered forecasting models, versions, and validation metrics (SPEC §11)."""
    async with async_session_factory() as session:
        stmt = select(MlModel).order_by(desc(MlModel.trained_at))
        rows = (await session.execute(stmt)).scalars().all()

        return [
            {
                "name": r.name,
                "version": r.version,
                "target": r.target,
                "trained_at": r.trained_at.isoformat() if r.trained_at else None,
                "metrics": r.metrics,
                "artifact_path": r.artifact_path,
                "is_active": r.is_active,
            }
            for r in rows
        ]


@router.post("/ml/train")
async def train_model_endpoint(
    req: TrainRequest, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Launch model training job in the background (SPEC §11)."""
    start_dt = datetime.fromisoformat(req.from_date).replace(tzinfo=UTC)
    end_dt = datetime.fromisoformat(req.to_date).replace(tzinfo=UTC)

    async def _train_task() -> None:
        try:
            logger.info(
                "Background training job started: model=%s target=%s", req.model, req.target
            )
            res = await train_model_pipeline(
                target=req.target,
                model_name=req.model,
                start_dt=start_dt,
                end_dt=end_dt,
                version=req.version,
            )
            logger.info("Background training finished: %s", res)
        except Exception as e:
            logger.error("Background training failed: %s", e)

    background_tasks.add_task(_train_task)

    return {
        "status": "training_started",
        "model": req.model,
        "target": req.target,
        "version": req.version,
        "message": f"Training of {req.model} started in background.",
    }


@router.post("/ml/models/{name}/{version}/activate")
async def activate_model(name: str, version: str) -> dict[str, Any]:
    """Set the specified model as active for online 11:00 forecasting (SPEC §11)."""
    async with async_session_factory() as session:
        # Find target for this model
        stmt = select(MlModel).where(MlModel.name == name, MlModel.version == version)
        model_obj = (await session.execute(stmt)).scalar_one_or_none()
        if not model_obj:
            raise HTTPException(status_code=404, detail=f"Model {name}:{version} not found")

        # Deactivate previous active models for same target
        await session.execute(
            update(MlModel).where(MlModel.target == model_obj.target).values(is_active=False)
        )
        # Activate target model
        await session.execute(
            update(MlModel)
            .where(MlModel.name == name, MlModel.version == version)
            .values(is_active=True)
        )
        await session.commit()

        logger.info("Activated model %s:%s for target %s", name, version, model_obj.target)
        return {
            "status": "activated",
            "name": name,
            "version": version,
            "target": model_obj.target,
        }


@router.get("/ml/backtest")
async def get_backtest_results() -> list[dict[str, Any]]:
    """Run / retrieve economic backtest comparing models vs Perfect Foresight (SPEC §8.4)."""
    try:
        results = await run_economic_backtest()
        return results
    except Exception as e:
        logger.error("Backtest failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/forecasts")
async def get_forecasts(
    target: str = Query(default="price"),
    limit: int = Query(default=48, le=200),
) -> list[dict[str, Any]]:
    """Query recent generated forecasts with p10/p90 prediction intervals (SPEC §11)."""
    async with async_session_factory() as session:
        stmt = (
            select(Forecast)
            .where(Forecast.target == target)
            .order_by(desc(Forecast.ts))
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()

        return [
            {
                "ts": r.ts.isoformat(),
                "target": r.target,
                "model_name": r.model_name,
                "model_version": r.model_version,
                "value": r.value,
                "p10": r.p10,
                "p90": r.p90,
                "horizon_h": r.horizon_h,
            }
            for r in rows
        ]


@router.post("/forecasts/run")
async def run_forecast_now(target: str = "price") -> dict[str, Any]:
    """Trigger immediate forecast generation using active ML model (SPEC §11)."""
    from ems.forecasting.service import generate_day_ahead_forecast
    from ems.main import app_state

    sim_now = app_state.clock.now() if app_state.clock else datetime.now(tz=UTC)
    target_date = (sim_now + timedelta(days=1)).date()

    async with async_session_factory() as session:
        forecasts = await generate_day_ahead_forecast(
            target_date=target_date,
            sim_dt=sim_now,
            session=session,
            target=target,
        )

    return {
        "status": "success",
        "target": target,
        "horizon_h": len(forecasts),
        "forecasts": [
            {
                "ts": f["ts"].isoformat(),
                "value": f.get("price_dam") if target == "price" else f.get("load_kw"),
                "p10": f.get("p10"),
                "p90": f.get("p90"),
            }
            for f in forecasts
        ],
    }
