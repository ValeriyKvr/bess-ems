"""Standalone Demo HTTP & WebSocket Server (SPEC §14 Stage 8).

Runs FastAPI + Uvicorn to serve web/dist SPA, API endpoints,
and live WebSocket telemetry without requiring external PostgreSQL or Mosquitto.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import math
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "web" / "dist"
PORT = 5173


class BatterySettings(BaseModel):
    capacity_kwh: float = Field(default=1000.0, ge=10.0, le=100000.0)
    power_max_kw: float = Field(default=500.0, ge=5.0, le=50000.0)
    soc_min_pct: float = Field(default=10.0, ge=0.0, le=50.0)
    soc_max_pct: float = Field(default=90.0, ge=50.0, le=100.0)
    soc_hard_min_pct: float = Field(default=5.0, ge=0.0, le=20.0)
    soc_hard_max_pct: float = Field(default=97.0, ge=80.0, le=100.0)
    eff_charge: float = Field(default=0.95, gt=0.5, le=1.0)
    eff_discharge: float = Field(default=0.95, gt=0.5, le=1.0)
    self_discharge_pct_day: float = Field(default=0.1, ge=0.0, le=5.0)
    aux_load_kw: float = Field(default=3.0, ge=0.0, le=50.0)
    ramp_rate_kw_s: float = Field(default=50.0, ge=1.0, le=1000.0)
    temp_ambient_c: float = Field(default=25.0, ge=-30.0, le=60.0)
    temp_max_c: float = Field(default=45.0, ge=30.0, le=80.0)
    cycle_life: float = Field(default=6000.0, ge=500.0, le=30000.0)
    capex_uah: float = Field(default=15000000.0, ge=0.0)
    initial_soc_pct: float = Field(default=50.0, ge=0.0, le=100.0)


class MarketTariffs(BaseModel):
    transmission_tariff_uah_mwh: float = Field(default=528.57)
    distribution_tariff_uah_mwh: float = Field(default=1250.00)
    supplier_margin_uah_mwh: float = Field(default=150.00)
    export_price_coeff: float = Field(default=0.90)
    export_allowed: bool = Field(default=True)
    price_cap_min: float = Field(default=10.0)
    price_cap_max: float = Field(default=9000.0)


class StrategySettings(BaseModel):
    active_strategy: str = Field(default="ARBITRAGE")
    w_arbitrage: float = Field(default=1.0, ge=0.0, le=10.0)
    w_peak: float = Field(default=1.0, ge=0.0, le=10.0)
    w_reserve: float = Field(default=1.0, ge=0.0, le=10.0)
    reserve_soc_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    peak_limit_kw: float = Field(default=500.0, ge=10.0)
    degradation_cost_weight: float = Field(default=1.0, ge=0.0, le=2.0)


class SimulationSettings(BaseModel):
    default_scenario: str = Field(default="default")
    default_speed: int = Field(default=60)
    seed: int = Field(default=42)
    pv_enabled: bool = Field(default=True)
    pv_peak_kw: float = Field(default=200.0, ge=0.0)


class EmsCoreSettings(BaseModel):
    soc_tolerance_pct: float = Field(default=3.0, ge=0.5, le=20.0)
    optimization_horizon_h: int = Field(default=24, ge=12, le=72)
    optimization_step_min: int = Field(default=60)


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

# In-memory mutable settings
CURRENT_SETTINGS: dict[str, dict[str, Any]] = {
    k: v().model_dump() for k, v in SECTION_MODELS.items()
}

# Connected WebSockets for telemetry
active_connections: list[WebSocket] = []
sim_state = {
    "is_running": True,
    "speed": 60,
    "step_count": 0,
    "start_sim_time": datetime(2026, 3, 2, 8, 0, 0, tzinfo=UTC),
}


async def telemetry_broadcaster():
    """Background task streaming realistic live telemetry ticks every second."""
    while True:
        await asyncio.sleep(1.0)
        if not active_connections:
            continue

        if sim_state["is_running"]:
            sim_state["step_count"] += 1

        t_sim = sim_state["start_sim_time"] + timedelta(
            seconds=sim_state["step_count"] * sim_state["speed"]
        )
        hour = t_sim.hour + t_sim.minute / 60.0

        # Dynamic simulation physics:
        # Load profile with morning & evening peaks
        load_kw = 320.0 + 150.0 * math.sin(math.pi * (hour - 6) / 12) ** 2 if 6 <= hour <= 22 else 180.0
        # PV generation during daytime (08:00 - 18:00)
        pv_kw = max(0.0, 180.0 * math.sin(math.pi * (hour - 7) / 11)) if 7 <= hour <= 18 else 0.0

        # Battery cycle: Charge at night / early morning, discharge during evening peak
        if 1 <= hour <= 6:
            bess_power = 280.0  # charging
            bess_state = "CHARGING"
        elif 17 <= hour <= 22:
            bess_power = -320.0  # discharging
            bess_state = "DISCHARGING"
        else:
            bess_power = -50.0 if load_kw > 350 else 60.0
            bess_state = "DISCHARGING" if bess_power < 0 else "CHARGING"

        # SoC dynamic calculation oscillating between 25% and 85%
        soc_pct = 55.0 + 30.0 * math.sin(math.pi * (hour - 3) / 12)
        soc_pct = max(10.0, min(90.0, soc_pct))

        # Net grid power: site_load - pv + bess_power
        grid_power = load_kw - pv_kw + bess_power
        dam_price = 3200.0 + 3400.0 * (math.sin(math.pi * (hour - 8) / 14) ** 2)

        tick_payload = {
            "type": "tick",
            "clock": {
                "ts_sim": t_sim.isoformat(),
                "speed": sim_state["speed"],
                "is_running": sim_state["is_running"],
            },
            "bess": {
                "soc_pct": round(soc_pct, 2),
                "power_kw": round(bess_power, 1),
                "voltage_v": 804.2,
                "temp_c": round(24.5 + abs(bess_power) * 0.015, 1),
                "state": bess_state,
            },
            "site": {
                "load_kw": round(load_kw, 1),
                "pv_kw": round(pv_kw, 1),
            },
            "grid": {
                "power_kw": round(grid_power, 1),
                "voltage_v": 398.5,
                "frequency_hz": 50.02,
            },
            "market": {
                "price_dam_uah_mwh": round(dam_price, 2),
                "price_buy_uah_mwh": round(dam_price + 1928.57, 2),
                "price_sell_uah_mwh": round(dam_price * 0.90, 2),
            },
            "ems": {
                "setpoint_kw": round(bess_power, 1),
                "strategy": "ARBITRAGE",
            },
            "finance": {
                "today_net_uah": round(1450.0 + (sim_state["step_count"] * 1.8), 2),
                "today_baseline_uah": round(6800.0 + (sim_state["step_count"] * 2.2), 2),
            },
        }

        # Broadcast to all connected WebSockets
        dead_conns = []
        for ws in active_connections:
            try:
                await ws.send_json(tick_payload)
            except Exception:
                dead_conns.append(ws)
        for dead in dead_conns:
            if dead in active_connections:
                active_connections.remove(dead)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(telemetry_broadcaster())
    yield
    task.cancel()


app = FastAPI(title="BESS EMS Standalone Demo Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- WEBSOCKET TELEMETRY ---
@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            # Keep receiving client pings / messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)


# --- SIMULATION CONTROL ---
@app.post("/api/sim/control")
async def control_sim(payload: dict[str, Any]):
    action = payload.get("action")
    if action == "speed":
        sim_state["speed"] = int(payload.get("speed", 60))
    elif action == "pause":
        sim_state["is_running"] = False
    elif action == "resume":
        sim_state["is_running"] = True
        if "speed" in payload and payload["speed"]:
            sim_state["speed"] = int(payload["speed"])
    elif action == "step":
        sim_state["step_count"] += 1
    return {"status": "ok", "state": sim_state}


# --- SETTINGS API ---
@app.get("/api/settings/{section}/schema")
async def get_settings_schema(section: str):
    s = section.lower()
    if s not in SECTION_MODELS:
        raise HTTPException(status_code=404, detail="Section not found")
    return {
        "section": s,
        "schema": SECTION_MODELS[s].model_json_schema(),
        "requires_restart": RESTART_REQUIRED_FIELDS.get(s, []),
    }


@app.get("/api/settings/{section}")
async def get_settings(section: str):
    s = section.lower()
    if s not in CURRENT_SETTINGS:
        raise HTTPException(status_code=404, detail="Section not found")
    return CURRENT_SETTINGS[s]


@app.put("/api/settings/{section}")
async def update_settings(section: str, payload: dict[str, Any]):
    s = section.lower()
    if s not in SECTION_MODELS:
        raise HTTPException(status_code=404, detail="Section not found")
    validated = SECTION_MODELS[s](**payload).model_dump()
    CURRENT_SETTINGS[s] = validated
    return {"section": s, "status": "updated", "settings": validated}


# --- SCHEDULES API ---
@app.get("/api/schedules")
async def get_schedules(limit: int = 1):
    return [
        {
            "id": "sch-20260302-01",
            "strategy": "ARBITRAGE",
            "created_at_sim": "2026-03-02T00:00:00Z",
            "horizon_start": "2026-03-02T00:00:00Z",
            "horizon_end": "2026-03-03T00:00:00Z",
            "expected_profit_uah": 2480.50,
        }
    ]


@app.get("/api/schedules/{schedule_id}")
async def get_schedule_detail(schedule_id: str):
    now = datetime(2026, 3, 2, 0, 0, 0, tzinfo=UTC)
    items = []
    for h in range(24):
        p = 250.0 if 1 <= h <= 6 else (-300.0 if 18 <= h <= 22 else 0.0)
        reason = "charge_low_dam" if p > 0 else ("discharge_peak_dam" if p < 0 else "idle")
        items.append({
            "ts": (now + timedelta(hours=h)).isoformat(),
            "setpoint_kw": p,
            "reason": reason,
        })
    return {
        "id": schedule_id,
        "strategy": "ARBITRAGE",
        "created_at_sim": now.isoformat(),
        "horizon_start": now.isoformat(),
        "horizon_end": (now + timedelta(days=1)).isoformat(),
        "expected_profit_uah": 2480.50,
        "items": items,
    }


# --- ML API ---
@app.get("/api/ml/models")
async def get_ml_models():
    return [
        {
            "name": "Naive Baseline",
            "model": "naive",
            "version": "v1.0.0",
            "target": "price",
            "mae": 412.50,
            "mape": 7.8,
            "rmse": 534.20,
            "spearman_rank_corr": 0.82,
            "status": "ready",
            "active": False,
        },
        {
            "name": "LightGBM 24h Direct",
            "model": "lightgbm",
            "version": "v1.2.0",
            "target": "price",
            "mae": 238.40,
            "mape": 4.1,
            "rmse": 308.15,
            "spearman_rank_corr": 0.94,
            "status": "ready",
            "active": True,
        },
        {
            "name": "Seq2Seq PyTorch LSTM",
            "model": "lstm",
            "version": "v1.1.0",
            "target": "price",
            "mae": 254.10,
            "mape": 4.5,
            "rmse": 322.80,
            "spearman_rank_corr": 0.92,
            "status": "ready",
            "active": False,
        },
    ]


@app.get("/api/ml/backtest")
async def get_ml_backtest():
    return [
        {
            "model": "Naive (Вчора)",
            "net_uah": 17611.73,
            "pct_of_ideal": 26.3,
            "description": "Baseline персистенція",
        },
        {
            "model": "LightGBM",
            "net_uah": 43235.81,
            "pct_of_ideal": 64.5,
            "description": "24 Direct Models + Quantiles",
        },
        {
            "model": "Perfect Foresight (Ідеал)",
            "net_uah": 67081.79,
            "pct_of_ideal": 100.0,
            "description": "Теоретична верхня межа (істинні ціни)",
        },
    ]


@app.get("/api/forecasts")
async def get_forecasts():
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    items = []
    prices = [3100, 2950, 2900, 3050, 3400, 4600, 5500, 5700, 5400, 4900, 4600, 4500,
              4600, 4900, 5300, 6100, 7000, 7300, 7000, 6300, 5200, 4300, 3700, 3300]
    for i in range(24):
        t = now + timedelta(hours=i)
        p = prices[i]
        items.append({
            "ts": t.isoformat(),
            "value": p,
            "p10": p * 0.92,
            "p90": p * 1.08,
        })
    return {"target": "price", "forecasts": items}


# --- REPORTS API ---
@app.get("/api/reports/summary")
async def get_reports_summary():
    return {
        "period_from": "2026-02-01T00:00:00Z",
        "period_to": "2026-03-01T23:00:00Z",
        "cost_baseline_uah": 1141373.64,
        "cost_actual_uah": 996674.57,
        "revenue_uah": 24520.00,
        "degradation_uah": 14210.00,
        "net_savings_uah": 43235.81,
        "cycles": 20.29,
        "payback_years": 4.8,
        "hourly": [],
    }


@app.get("/api/reports/compare-strategies")
async def get_compare_strategies():
    return [
        {
            "strategy": "TOU_SIMPLE",
            "cost_baseline_uah": 270729.08,
            "cost_actual_uah": 282130.63,
            "revenue_uah": 4210.00,
            "degradation_uah": 15576.97,
            "net_uah": 17611.73,
            "cycles": 12.28,
        },
        {
            "strategy": "ARBITRAGE (MILP)",
            "cost_baseline_uah": 270729.08,
            "cost_actual_uah": 244426.95,
            "revenue_uah": 9850.00,
            "degradation_uah": 14730.66,
            "net_uah": 43235.81,
            "cycles": 20.29,
        },
        {
            "strategy": "PEAK_SHAVING",
            "cost_baseline_uah": 270729.08,
            "cost_actual_uah": 251100.20,
            "revenue_uah": 3100.00,
            "degradation_uah": 9200.00,
            "net_uah": 36120.40,
            "cycles": 14.10,
        },
        {
            "strategy": "SELF_CONSUMPTION",
            "cost_baseline_uah": 270729.08,
            "cost_actual_uah": 259800.00,
            "revenue_uah": 1800.00,
            "degradation_uah": 8100.00,
            "net_uah": 28450.00,
            "cycles": 11.50,
        },
    ]


# --- DATA API ---
@app.get("/api/data/heatmap")
async def get_data_heatmap():
    matrix = []
    for d in range(7):
        for h in range(24):
            base = 3200 + 3000 * ((1 - ((h - 18) / 8) ** 2) if 10 <= h <= 22 else 0.1)
            if d in (5, 6):
                base *= 0.85
            matrix.append([h, d, round(base, 1)])
    return {"type": "price", "matrix": matrix}


# --- DISPATCH LOGS API ---
@app.get("/api/dispatch/log")
async def get_dispatch_logs(page: int = 1, limit: int = 15):
    items = []
    now = datetime.now(UTC)
    reasons = ["schedule", "schedule", "reactive_derate", "schedule", "safe_mode_clear"]
    for i in range(limit):
        t = now - timedelta(minutes=i * 5)
        items.append({
            "id": 100 - i,
            "ts": t.isoformat(),
            "setpoint_kw": -250.0 if i % 2 == 0 else 300.0,
            "actual_kw": -248.5 if i % 2 == 0 else 298.0,
            "reason": reasons[i % len(reasons)],
            "schedule_id": f"sch-20260301-{10 - i // 2}",
            "override": i == 2,
        })
    return {
        "items": items,
        "total": 450,
        "page": page,
        "limit": limit,
    }


# --- EVENTS API ---
@app.get("/api/events")
async def get_events(limit: int = 30):
    return [
        {
            "event": "OPTIMIZATION_COMPLETED",
            "schedule_id": "sch-20260302-01",
            "strategy": "ARBITRAGE",
            "ts": datetime.now(UTC).isoformat(),
        },
        {
            "event": "MARKET_PRICES_PUBLISHED",
            "target_date": "2026-03-02",
            "count": 24,
            "ts": datetime.now(UTC).isoformat(),
        },
    ]


# --- STATIC SPA FILES ---
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        target = DIST_DIR / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(DIST_DIR / "index.html")


def run_demo():
    print(f"\n=======================================================")
    print(f"  BESS EMS Live Demo Server running on:")
    print(f"  -> http://localhost:{PORT}")
    print(f"  Includes Live Telemetry WebSocket + Interactive UI")
    print(f"=======================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    run_demo()
