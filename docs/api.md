# REST & WebSocket API Specification

**Version:** 1.1  
**Compliance:** SPEC §11  

## 1. System & Health
- `GET /api/health`: Basic service liveness and database connection status.
- `GET /api/status`: Master system status (SimulationClock, MQTT, connected BESS units).

## 2. Simulation Control (`/api/sim`)
- `POST /api/sim/control`: Controls the master simulation clock.
  **Payload Schema:**
  ```json
  {
    "action": "start | pause | resume | step | reset | speed | jump",
    "speed": 60,
    "scenario": "default | winter_week | summer_month | year_2025",
    "jump_to": "2026-03-01T00:00:00Z",
    "step_seconds": 60.0
  }
  ```

## 3. Configuration & Settings (`/api/settings`)
- `GET /api/settings/{section}`: Retrieve settings for section (`battery`, `market`, `strategy`, `simulation`, `ems`).
- `PUT /api/settings/{section}`: Validate (via Pydantic) and persist updated section settings.

### Available Sections:
- **`battery`**: Physical properties (capacity, max power, SoC limits, efficiencies, degradation cycle life).
- **`market`**: Ukrainian market parameters (transmission, distribution tariffs, supplier margin, export price coefficient, price caps).
- **`strategy`**: Operational dispatch mode (`ARBITRAGE`, `PEAK_SHAVING`, `SELF_CONSUMPTION`, `TOU_SIMPLE`) and weights.
- **`simulation`**: Default scenario, default speed, random seed, PV enablement.
- **`ems`**: Closed-loop tolerance threshold (`soc_tolerance_pct`), optimization horizon, and step.

## 4. Data Ingestion & Series (`/api/data`)
- `POST /api/data/generate`: Generate 2-year synthetic datasets for prices and industrial load.
- `POST /api/data/import`: Multipart CSV upload (`type=price` or `type=load`).
- `GET /api/data/series?type=&from=&to=&step=`: Query historical/synthetic time series with optional resampling (`1h` or `15min`).

## 5. Optimization & Schedules (`/api/schedules`, `/api/optimize`)
- `POST /api/optimize/run`: Trigger on-demand MILP optimization for horizon (24–72h) with selected strategy (`ARBITRAGE`, `PEAK_SHAVING`, `SELF_CONSUMPTION`, `BACKUP_RESERVE`).
  **Payload Schema:**
  ```json
  {
    "horizon_h": 24,
    "strategy": "ARBITRAGE | PEAK_SHAVING | SELF_CONSUMPTION | BACKUP_RESERVE",
    "use_perfect_foresight": false,
    "initial_soc_pct": 50.0
  }
  ```
- `GET /api/schedules?from=&to=&limit=`: List generated dispatch schedules with metadata (strategy, horizon, expected profit, solve time).
- `GET /api/schedules/{id}`: Detailed view of a single schedule including all hourly slots, setpoints, and decision reasons.

## 6. Realtime Dispatch & Commands
- `GET /api/dispatch/log?from=&to=&limit=`: Retrieve decisions executed by the Dispatcher (setpoint, actual power, reason, schedule reference, override flag).
- `GET /api/events?from=&to=&limit=`: Retrieve operational events and alarms (e.g., `SAFE_MODE_ENTER`, `SAFE_MODE_EXIT`).
- `POST /api/bess/command`: Send control commands to BESS hardware via MQTT (`reset_alarm`, `standby`, `start`).
  **Payload Schema:**
  ```json
  {
    "cmd": "reset_alarm | standby | start"
  }
  ```

## 7. Realtime WebSocket Transport (`/ws/telemetry`)
- `WS /ws/telemetry`: Streaming bidirectional WebSocket endpoint.
  - Server pushes tick payload on each simulation tick:
    ```json
    {
      "type": "tick",
      "clock": { "ts_sim": "2026-03-01T00:00:00Z", "speed": 60, "is_paused": false },
      "bess": { "soc_pct": 50.0, "soh_pct": 100.0, "power_kw": -180.0, "state": "DISCHARGING" },
      "site": { "load_kw": 340.0, "pv_kw": 45.0 },
      "grid": { "import_kw": 115.0, "export_kw": 0.0 },
      "market": { "price_dam": 6850.0, "price_buy": 9120.0, "price_sell": 6165.0 },
      "ems": { "setpoint_kw": -180.0, "reason": "schedule", "schedule_id": "...", "state": "DISPATCHING" },
      "finance": { "today_net_uah": 12430.0, "today_baseline_uah": 41200.0 }
    }
    ```
  - Operational events are published immediately with `type: "event"` (unthrottled).
  - High-speed simulation rate limiting: When simulation speed $\ge 600\times$, ticks are throttled to $\le 10\text{ msg/s}$ with client keep-alive pings.

## 8. Machine Learning & Forecasting (`/api/ml`, `/api/forecasts`) (SPEC §8, §11)
- `GET /api/ml/models`: List registered ML models, versions, active flag, and walk-forward validation metrics (`mae`, `mape`, `rmse`, `spearman_rank_corr`).
- `POST /api/ml/train`: Launch model training job in the background.
  **Payload Schema:**
  ```json
  {
    "target": "price | load",
    "model": "lightgbm | naive | lstm",
    "version": "v1.0.0",
    "from_date": "2024-01-01",
    "to_date": "2025-12-31"
  }
  ```
- `POST /api/ml/models/{name}/{version}/activate`: Set specified model as active for online 11:00 preliminary forecasting.
- `GET /api/ml/backtest`: Run / retrieve economic backtesting comparison between Naive, LightGBM, and Perfect Foresight.
- `GET /api/forecasts?target=price&limit=48`: Query recent forecasts with quantile prediction intervals (`p10` and `p90`).
- `POST /api/forecasts/run?target=price`: Trigger immediate 24h ahead forecast generation.

## 9. Reports & Strategy Comparison (`/api/reports`) (SPEC §10.1(5), §11)
- `GET /api/reports/summary?from=&to=&format=json|xlsx|csv`: Financial KPI summary (baseline cost, cost with BESS, export revenue, degradation, net UAH, cycles, payback years) and hourly breakdown. Supports multi-sheet Excel `.xlsx` and standard `.csv` download.
- `GET /api/reports/compare-strategies?date=YYYY-MM-DD`: Pure in-memory 24h comparative simulation across `TOU_SIMPLE`, `ARBITRAGE`, `PEAK_SHAVING`, and `SELF_CONSUMPTION` without modifying live simulation state.

## 10. Extended Settings, Data & Diagnostics (SPEC §10.1, §11)
- `GET /api/settings/{section}/schema`: Dynamic JSON Schema of the settings section for client form generation, annotated with `requires_restart` attributes.
- `POST /api/data/preview`: Multipart CSV upload returning the first 20 rows, detected data type (`price` or `load`), and structural validation errors without committing to DB.
- `GET /api/data/heatmap?type=price|load&from=&to=`: 24-hour $\times$ 7-day average distribution matrix for temporal analysis.
- `POST /api/bess/fault-injection`: Trigger diagnostic fault simulation via MQTT (`force_overheat`, `comms_dropout`, `soc_noise`, `power_limit_50`, `clear_all`).
- `GET /api/dispatch/log?page=1&limit=50&reason=&override=&schedule_id=`: Paginated and filterable dispatcher activity history.
