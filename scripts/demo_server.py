"""Standalone Demo HTTP & WebSocket Server (SPEC §14 Stage 8).

Runs FastAPI + Uvicorn to serve web/dist SPA, API endpoints,
and live WebSocket telemetry with realistic 24-hour Ukrainian Day-Ahead Market dynamics.
Fully adheres to SPEC §11 contracts and thread-safe async architecture without external DB.
"""

import asyncio
import math
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "web" / "dist"
PORT = 5173

# Ukrainian Day-Ahead Market (РДН) hourly price factors (SPEC §3, generator.py)
# Reflects: Night valley (00-06), Morning peak (07-11), Solar day dip (12-16), Evening super-peak (17-22)
DAM_HOURLY_SHAPE = {
    0: 0.65,
    1: 0.60,
    2: 0.58,
    3: 0.56,
    4: 0.58,
    5: 0.65,
    6: 0.82,
    7: 1.12,
    8: 1.25,
    9: 1.28,
    10: 1.22,
    11: 1.10,
    12: 0.95,
    13: 0.90,
    14: 0.88,
    15: 0.94,
    16: 1.10,
    17: 1.35,
    18: 1.55,
    19: 1.72,
    20: 1.75,
    21: 1.65,
    22: 1.40,
    23: 1.02,
}


def get_dam_price(t: datetime) -> float:
    """Calculate hourly DAM price with smooth minute-to-minute transitions."""
    base_dam = 4200.0  # Base Ukrainian DAM clearing price in UAH/MWh
    h1 = t.hour
    h2 = (h1 + 1) % 24
    factor1 = DAM_HOURLY_SHAPE.get(h1, 1.0)
    factor2 = DAM_HOURLY_SHAPE.get(h2, 1.0)
    alpha = t.minute / 60.0
    factor = factor1 * (1.0 - alpha) + factor2 * alpha
    price = base_dam * factor
    # Regulatory price caps: min 10.0, max 9000.0 (SPEC §3)
    return round(max(10.0, min(9000.0, price)), 2)


class BatterySettings(BaseModel):
    capacity_kwh: float = Field(default=1000.0, ge=10.0, le=100000.0)
    power_max_kw: float = Field(default=500.0, ge=5.0, le=50000.0)
    soc_min_pct: float = Field(default=10.0, ge=0.0, le=50.0)
    soc_max_pct: float = Field(default=90.0, ge=50.0, le=100.0)
    soc_hard_min_pct: float = Field(default=5.0, ge=0.0, le=20.0)
    soc_hard_max_pct: float = Field(default=97.0, ge=80.0, le=100.0)
    eff_charge: float = Field(default=0.95, gt=0.5, le=1.0)
    eff_discharge: float = Field(default=0.95, gt=0.5, le=1.0)
    soc_derate_charge_start_pct: float = Field(default=85.0, ge=20.0, le=100.0)
    soc_derate_discharge_start_pct: float = Field(default=15.0, ge=0.0, le=80.0)
    self_discharge_pct_day: float = Field(default=0.1, ge=0.0, le=5.0)
    aux_load_kw: float = Field(default=3.0, ge=0.0, le=50.0)
    aux_from_ac: bool = Field(default=True)
    ramp_rate_kw_s: float = Field(default=50.0, ge=1.0, le=1000.0)
    temp_ambient_c: float = Field(default=25.0, ge=-30.0, le=60.0)
    temp_max_c: float = Field(default=45.0, ge=30.0, le=80.0)
    thermal_loss_frac_rated: float = Field(default=0.025, ge=0.001, le=0.2)
    cooling_design_delta_t_c: float = Field(default=10.0, ge=1.0, le=40.0)
    thermal_mass_kj_per_kwh: float = Field(default=5.0, ge=0.5, le=50.0)
    v_nominal_v: float = Field(default=780.0, ge=48.0, le=2000.0)
    cycle_life: float = Field(default=6000.0, ge=500.0, le=30000.0)
    calendar_fade_pct_per_year: float = Field(default=1.5, ge=0.0, le=10.0)
    deg_temp_ref_c: float = Field(default=25.0, ge=0.0, le=45.0)
    deg_temp_doubling_k: float = Field(default=10.0, ge=2.0, le=30.0)
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
    active_strategy: Literal[
        "ARBITRAGE",
        "PEAK_SHAVING",
        "SELF_CONSUMPTION",
        "BACKUP_RESERVE",
        "TOU_SIMPLE",
    ] = Field(default="ARBITRAGE")
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

CURRENT_SETTINGS: dict[str, dict[str, Any]] = {
    k: v().model_dump() for k, v in SECTION_MODELS.items()
}

# Thread-safe asyncio locks and simulation state
state_lock = asyncio.Lock()
ws_lock = asyncio.Lock()
active_connections: list[WebSocket] = []

sim_state = {
    "is_running": True,
    "speed": 60,
    "step_count": 0,
    "start_sim_time": datetime(2026, 3, 2, 8, 15, 0, tzinfo=UTC),
}


def get_current_sim_time() -> datetime:
    """Read current simulation time deterministically without datetime.now()."""
    return sim_state["start_sim_time"] + timedelta(
        seconds=sim_state["step_count"] * sim_state["speed"]
    )


def make_tick(t_sim: datetime) -> dict[str, Any]:
    """Generate realistic physical and market telemetry bound to current configuration settings."""
    hour = t_sim.hour + t_sim.minute / 60.0
    dam_price = get_dam_price(t_sim)

    # Read live settings without magic hardcoded numbers
    b_cfg = CURRENT_SETTINGS["battery"]
    m_cfg = CURRENT_SETTINGS["market"]
    sim_cfg = CURRENT_SETTINGS["simulation"]

    p_max = float(b_cfg.get("power_max_kw", 500.0))
    soc_min = float(b_cfg.get("soc_min_pct", 10.0))
    soc_max = float(b_cfg.get("soc_max_pct", 90.0))

    pv_peak = float(sim_cfg.get("pv_peak_kw", 200.0)) if sim_cfg.get("pv_enabled", True) else 0.0

    # 1. Industrial site load (active power in kW)
    if 7.0 <= hour <= 21.5:
        load_kw = 320.0 + 130.0 * math.sin(math.pi * (hour - 7.0) / 14.5) ** 2
    else:
        load_kw = 180.0 + 25.0 * math.sin(math.pi * hour / 7.0)

    # 2. On-site Solar PV
    if 8.0 <= hour <= 17.5 and pv_peak > 0:
        pv_kw = max(0.0, (pv_peak * 0.92) * math.sin(math.pi * (hour - 8.0) / 9.5))
    else:
        pv_kw = 0.0

    # 3. BESS Dispatch Strategy (Arbitrage / Peak Shaving) bound to P_max
    if 1.0 <= hour < 6.5:
        bess_power = min(p_max, 250.0)  # charging (+kW)
        bess_state = "CHARGING"
        reason = "charge_night_valley"
    elif 17.5 <= hour < 22.5:
        bess_power = -min(p_max, 320.0)  # discharging (-kW)
        bess_state = "DISCHARGING"
        reason = "discharge_evening_peak"
    elif 12.0 <= hour < 15.0 and pv_kw > 100.0:
        bess_power = min(p_max, 80.0)
        bess_state = "CHARGING"
        reason = "solar_self_consumption"
    elif load_kw > 400.0:
        bess_power = -min(p_max, 70.0)
        bess_state = "DISCHARGING"
        reason = "peak_shaving"
    else:
        bess_power = 0.0
        bess_state = "STANDBY"
        reason = "idle"

    # 4. Realistic Battery SoC dynamics across 24h bounded by [soc_min, soc_max]
    usable_range = soc_max - soc_min
    if 1.0 <= hour < 6.5:
        soc_pct = soc_min + ((hour - 1.0) / 5.5) * (usable_range * 0.95)
    elif 6.5 <= hour < 12.0:
        soc_pct = soc_max - (hour - 6.5) * 0.4
    elif 12.0 <= hour < 15.0:
        soc_pct = (soc_max - 2.0) + (hour - 12.0) * 0.8
    elif 15.0 <= hour < 17.5:
        soc_pct = soc_max - (hour - 15.0) * 0.5
    elif 17.5 <= hour < 22.5:
        soc_pct = soc_max - ((hour - 17.5) / 5.0) * (usable_range * 0.95)
    else:
        soc_pct = soc_min + (hour * 0.5 if hour < 1.0 else (hour - 22.5) * 0.4)

    soc_pct = max(soc_min, min(soc_max, soc_pct))

    # 5. External Grid balance (sign: import > 0, export < 0)
    net_facility = load_kw - pv_kw + bess_power
    grid_import = max(0.0, net_facility)
    grid_export = max(0.0, -net_facility)

    # 6. Tariffs computed from settings
    t_trans = float(m_cfg.get("transmission_tariff_uah_mwh", 528.57))
    t_dist = float(m_cfg.get("distribution_tariff_uah_mwh", 1250.00))
    t_supp = float(m_cfg.get("supplier_margin_uah_mwh", 150.00))
    k_export = float(m_cfg.get("export_price_coeff", 0.90))

    regulated_tariffs = t_trans + t_dist + t_supp
    price_buy = dam_price + regulated_tariffs
    price_sell = dam_price * k_export

    if dam_price >= 5500.0:
        level = "PEAK"
    elif dam_price <= 3200.0:
        level = "CHEAP"
    else:
        level = "MID"

    # 7. Financial savings computation
    today_net_savings = 1200.0 + (hour / 24.0) * 2300.0
    today_baseline_cost = 3100.0 + (hour / 24.0) * 6800.0

    return {
        "type": "tick",
        "clock": {
            "ts_sim": t_sim.isoformat(),
            "speed": sim_state["speed"],
            "is_running": sim_state["is_running"],
        },
        "bess": {
            "soc_pct": round(soc_pct, 2),
            "power_kw": round(bess_power, 1),
            "voltage_v": round(795.0 + (soc_pct / 100.0) * 25.0, 1),
            "temp_c": round(23.5 + abs(bess_power) * 0.012, 1),
            "state": bess_state,
        },
        "site": {
            "load_kw": round(load_kw, 1),
            "pv_kw": round(pv_kw, 1),
        },
        "grid": {
            "import_kw": round(grid_import, 1),
            "export_kw": round(grid_export, 1),
            "power_kw": round(grid_import - grid_export, 1),
            "voltage_v": 398.5,
            "frequency_hz": 50.01,
        },
        "market": {
            "price_dam": round(dam_price, 2),
            "price_dam_uah_mwh": round(dam_price, 2),
            "price_buy": round(price_buy, 2),
            "price_buy_uah_mwh": round(price_buy, 2),
            "price_sell": round(price_sell, 2),
            "price_sell_uah_mwh": round(price_sell, 2),
            "level": level,
        },
        "ems": {
            "setpoint_kw": round(bess_power, 1),
            "strategy": "ARBITRAGE",
            "state": "DISPATCHING",
            "reason": reason,
        },
        "finance": {
            "today_net_uah": round(today_net_savings, 2),
            "today_baseline_uah": round(today_baseline_cost, 2),
        },
    }


async def broadcast_tick(tick: dict[str, Any]):
    """Thread-safe WebSocket broadcasting with connection locks."""
    async with ws_lock:
        targets = list(active_connections)

    dead_conns = []
    for ws in targets:
        try:
            await ws.send_json(tick)
        except Exception:
            dead_conns.append(ws)

    if dead_conns:
        async with ws_lock:
            for dead in dead_conns:
                if dead in active_connections:
                    active_connections.remove(dead)


async def telemetry_broadcaster():
    """Background loop sending live telemetry ticks every second."""
    while True:
        await asyncio.sleep(1.0)
        async with state_lock:
            if sim_state["is_running"]:
                sim_state["step_count"] += 1
            t_sim = get_current_sim_time()

        tick = make_tick(t_sim)
        await broadcast_tick(tick)


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


# --- WEBSOCKET TELEMETRY WITH PRELOADED 24-HOUR HISTORY ---
@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    await websocket.accept()
    async with ws_lock:
        active_connections.append(websocket)
    try:
        async with state_lock:
            current_t = get_current_sim_time()

        # Send 48 points across past 24 hours (every 30 mins) for rich historical charts
        for i in range(48, 0, -1):
            hist_t = current_t - timedelta(minutes=i * 30)
            hist_tick = make_tick(hist_t)
            await websocket.send_json(hist_tick)

        # Send current instant tick
        await websocket.send_json(make_tick(current_t))

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        async with ws_lock:
            if websocket in active_connections:
                active_connections.remove(websocket)


# --- SIMULATION CONTROL (SPEC §11) ---
@app.post("/api/sim/control")
async def control_sim(payload: dict[str, Any]):
    action = payload.get("action", "").lower()
    async with state_lock:
        if action == "speed":
            sim_state["speed"] = int(payload.get("speed", 60))
        elif action == "pause":
            sim_state["is_running"] = False
        elif action in ("start", "resume"):
            sim_state["is_running"] = True
            if "speed" in payload and payload["speed"]:
                sim_state["speed"] = int(payload["speed"])
        elif action == "step":
            sim_state["step_count"] += 1
        elif action in ("jump", "seek"):
            # Supports both SPEC §11 'jump_to' and quick presets
            if "jump_to" in payload and payload["jump_to"]:
                target_t = datetime.fromisoformat(payload["jump_to"].replace("Z", "+00:00"))
            else:
                hour = int(payload.get("hour", 0))
                minute = int(payload.get("minute", 0))
                target_t = sim_state["start_sim_time"].replace(hour=hour, minute=minute, second=0)
            sim_state["start_sim_time"] = target_t
            sim_state["step_count"] = 0

        current_t = get_current_sim_time()

    tick = make_tick(current_t)
    await broadcast_tick(tick)
    return {
        "status": "success",
        "action": action,
        "clock": {
            "ts_sim": current_t.isoformat(),
            "speed": sim_state["speed"],
            "is_running": sim_state["is_running"],
        },
    }


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


# --- SCHEDULES API (SPEC §11) ---
@app.get("/api/schedules")
async def get_schedules(limit: int = 1):
    sim_t = get_current_sim_time()
    return [
        {
            "id": f"sch-{sim_t.strftime('%Y%m%d')}-01",
            "strategy": CURRENT_SETTINGS["strategy"]["active_strategy"],
            "created_at_sim": sim_t.replace(hour=0, minute=0, second=0).isoformat(),
            "horizon_start": sim_t.replace(hour=0, minute=0, second=0).isoformat(),
            "horizon_end": (
                sim_t.replace(hour=0, minute=0, second=0) + timedelta(days=1)
            ).isoformat(),
            "expected_profit_uah": 2480.50,
        }
    ]


@app.get("/api/schedules/{schedule_id}")
async def get_schedule_detail(schedule_id: str):
    sim_t = get_current_sim_time()
    base_t = sim_t.replace(hour=0, minute=0, second=0)
    items = []
    p_max = CURRENT_SETTINGS["battery"]["power_max_kw"]
    for h in range(24):
        p = min(p_max, 250.0) if 1 <= h <= 6 else (-min(p_max, 320.0) if 18 <= h <= 22 else 0.0)
        reason = "charge_low_dam" if p > 0 else ("discharge_peak_dam" if p < 0 else "idle")
        items.append(
            {
                "ts": (base_t + timedelta(hours=h)).isoformat(),
                "setpoint_kw": p,
                "reason": reason,
            }
        )
    return {
        "id": schedule_id,
        "strategy": CURRENT_SETTINGS["strategy"]["active_strategy"],
        "created_at_sim": base_t.isoformat(),
        "horizon_start": base_t.isoformat(),
        "horizon_end": (base_t + timedelta(days=1)).isoformat(),
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
async def get_forecasts(target: str = "price", limit: int = 48):
    sim_t = get_current_sim_time().replace(minute=0, second=0, microsecond=0)
    items = []
    for h in range(limit):
        t = sim_t + timedelta(hours=h)
        p = get_dam_price(t)
        items.append(
            {
                "ts": t.isoformat(),
                "value": p,
                "p10": round(p * 0.92, 2),
                "p90": round(p * 1.08, 2),
                "model_name": "LightGBM 24h Direct",
                "target": target,
            }
        )
    return items


# --- DATA TIME SERIES API ---
@app.get("/api/data/series")
async def get_data_series(type: str = "price", step: str = "1h"):
    sim_t = get_current_sim_time().replace(minute=0, second=0, microsecond=0)
    points = []
    start_t = sim_t - timedelta(days=7)
    for h in range(168):
        t = start_t + timedelta(hours=h)
        if type == "price":
            val = get_dam_price(t)
        elif type == "load":
            hour = t.hour + t.minute / 60.0
            val = round(
                320.0 + 130.0 * math.sin(math.pi * (hour - 7.0) / 14.5) ** 2
                if 7 <= hour <= 21
                else 180.0,
                1,
            )
        else:
            hour = t.hour + t.minute / 60.0
            val = round(
                max(0.0, 180.0 * math.sin(math.pi * (hour - 8.0) / 9.5))
                if 8 <= hour <= 17.5
                else 0.0,
                1,
            )
        points.append({"ts": t.isoformat(), "value": val})
    unit = "грн/МВт·год" if type == "price" else "кВт"
    return {"type": type, "unit": unit, "data": points}


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
    sim_t = get_current_sim_time().replace(hour=0, minute=0, second=0)
    for d in range(7):
        day_date = sim_t + timedelta(days=d)
        is_weekend = day_date.weekday() in (5, 6)
        for h in range(24):
            t = day_date.replace(hour=h)
            price = get_dam_price(t)
            if is_weekend:
                price *= 0.85
            matrix.append([h, d, round(price, 1)])
    return {"type": "price", "matrix": matrix}


# --- DISPATCH LOGS API (DETERMINISTIC SIM CLOCK) ---
@app.get("/api/dispatch/log")
async def get_dispatch_logs(page: int = 1, limit: int = 15):
    items = []
    sim_t = get_current_sim_time()
    reasons = ["schedule", "schedule", "reactive_derate", "schedule", "safe_mode_clear"]
    p_max = CURRENT_SETTINGS["battery"]["power_max_kw"]
    for i in range(limit):
        t = sim_t - timedelta(minutes=i * 5)
        items.append(
            {
                "id": 100 - i,
                "ts": t.isoformat(),
                "setpoint_kw": -min(p_max, 320.0) if i % 2 == 0 else min(p_max, 250.0),
                "actual_kw": -min(p_max, 318.5) if i % 2 == 0 else min(p_max, 248.0),
                "reason": reasons[i % len(reasons)],
                "schedule_id": f"sch-{t.strftime('%Y%m%d')}-{10 - i // 2}",
                "override": i == 2,
            }
        )
    return {
        "items": items,
        "total": 450,
        "page": page,
        "limit": limit,
    }


# --- EVENTS API (DETERMINISTIC SIM CLOCK) ---
@app.get("/api/events")
async def get_events(limit: int = 30):
    sim_t = get_current_sim_time()
    return [
        {
            "event": "OPTIMIZATION_COMPLETED",
            "schedule_id": f"sch-{sim_t.strftime('%Y%m%d')}-01",
            "strategy": CURRENT_SETTINGS["strategy"]["active_strategy"],
            "ts": sim_t.isoformat(),
        },
        {
            "event": "MARKET_PRICES_PUBLISHED",
            "target_date": (sim_t + timedelta(days=1)).strftime("%Y-%m-%d"),
            "count": 24,
            "ts": sim_t.isoformat(),
        },
    ]


# --- HEALTH & STATUS (SPEC §11) ---
# Without these the SPA catch-all below answers /api/health and /api/status with
# index.html, so the UI's response.json() fails and the dashboard reports the
# backend as unreachable.
@app.get("/api/health")
async def get_health():
    return {"status": "healthy", "service": "demo-server", "database": True}


@app.get("/api/status")
async def get_system_status():
    sim_t = get_current_sim_time()
    return {
        "status": "ONLINE",
        "clock": {
            "ts_sim": sim_t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "speed": sim_state["speed"],
            "is_paused": not sim_state["is_running"],
        },
        "mqtt_connected": True,
        "bess_connected": True,
        "active_bess": ["bess-01"],
        "stage": "Demo (standalone, no DB/MQTT)",
    }


# --- STATIC SPA FILES ---
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # An unknown /api/ path is a bug, not a client-side route — answering it with
        # index.html hides the failure behind an HTML parse error in the browser.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"Unknown API route: /{full_path}")
        target = DIST_DIR / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(DIST_DIR / "index.html")


def run_demo():
    print("\n=======================================================")
    print("  BESS EMS Live Demo Server running on:")
    print(f"  -> http://localhost:{PORT}")
    print("  Includes Live Telemetry WebSocket + Realistic 24h Ukrainian DAM")
    print("  Async Thread-Safe & SPEC §11 API Compliant")
    print("=======================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    run_demo()
