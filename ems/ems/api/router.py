"""Main API router aggregating all endpoints."""

from fastapi import APIRouter

from ems.api.data import router as data_router
from ems.api.dispatch import router as dispatch_router
from ems.api.health import router as health_router
from ems.api.ml import router as ml_router
from ems.api.optimize import router as optimize_router
from ems.api.reports import router as reports_router
from ems.api.schedules import router as schedules_router
from ems.api.settings import router as settings_router
from ems.api.sim import router as sim_router
from ems.api.ws import router as ws_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(sim_router)
api_router.include_router(settings_router)
api_router.include_router(data_router)
api_router.include_router(reports_router)
api_router.include_router(schedules_router)
api_router.include_router(dispatch_router)
api_router.include_router(optimize_router)
api_router.include_router(ml_router)

# WS router is mounted at app level (no /api prefix) — included separately in main.py
ws_api_router = ws_router
