# System Architecture: BESS ↔ EMS Simulator

**Version:** 2.0  
**Compliance:** SPEC §4, §5, §6, §12  

## 1. Overview
The simulator models the physical and economic operation of an industrial Battery Energy Storage System (BESS) paired with an on-site solar PV plant, commercial facility load, and an Energy Management System (EMS) participating in the Ukrainian wholesale electricity market (Day-Ahead Market - РДН and Balancing Market).

---

## 2. Core Architectural Principles
1. **Decoupled Architecture:** BESS and EMS are completely independent processes interacting exclusively via network protocols (MQTT messaging and optional Modbus TCP). Neither service has direct access to the internal memory, process space, or private storage of the other.
2. **Simulation Time Authority:** A single authoritative `SimulationClock` is maintained by the EMS core. The clock publishes time advances to MQTT topic `sim/clock`, synchronizing all physical, dispatch, and market actors.
3. **Power Flow Sign Convention:**
   - `power_kw > 0`: **Charging** (consuming electrical power from grid or site).
   - `power_kw < 0`: **Discharging** (injecting electrical power into grid or site).
4. **Deterministic Execution:** Fixed random seeds yield bitwise identical simulation trajectories across synthetic market prices, load profiles, and battery physical responses.

---

## 3. Communication Topology & Interfaces

```
               +--------------------------------------------+
               |        Web Dashboard (React 18 + TS)       |
               +--------------------------------------------+
                       | REST API              ^ WebSocket
                       v                       | (/ws/telemetry)
               +--------------------------------------------+
               |                  EMS Core                  |
               |  FastAPI • MILP Solver • ML Forecasting    |
               |  Market Simulator • SimulationClock        |
               +--------------------------------------------+
                       |                               ^
        Topic: ems/{id}/setpoint                       | Topic: bess/{id}/telemetry
        Topic: ems/{id}/command                        | Topic: bess/{id}/status
        Topic: sim/clock                               | Topic: bess/{id}/alarm
                       v                               |
               +--------------------------------------------+
               |             MQTT Broker (Mosquitto)        |
               +--------------------------------------------+
                       |                               ^
                       +---------------+---------------+
                                       |
                                       v
               +--------------------------------------------+
               |             BESS Simulator                 |
               |  LFP OCV • Thévenin Circuit • Arrhenius   |
               |  6-State BMS FSM • Thermal Dissipation     |
               |  Modbus TCP Server (Port 5020)             |
               +--------------------------------------------+
```

### 3.1. MQTT Protocol (Primary Interface)
- `sim/clock`: Simulation timestamps broadcast each simulated minute.
- `ems/{bess_id}/setpoint`: Active power dispatch commands dispatched by EMS.
- `ems/{bess_id}/command`: Supervisory commands (`start`, `standby`, `reset_alarm`, fault injection).
- `bess/{bess_id}/telemetry`: High-frequency physical telemetry (SoC, SoH, power, voltage, current, temperature).
- `bess/{bess_id}/status`: FSM state transitions (`INIT`, `STANDBY`, `CHARGING`, `DISCHARGING`, `FAULT`, `DEGRADED`).
- `bess/{bess_id}/alarm`: Protective trip alerts (over-temperature, over-voltage, under-voltage).

### 3.2. Modbus TCP Gateway (Industrial Interface)
The BESS simulator embeds an industrial Modbus TCP server (default port `5020`):
- **Holding Registers:**
  - `40001` (Offset 0): State of Charge in 0.01% resolution (`0..10000`).
  - `40002` (Offset 1): Active Power in kW (signed 16-bit int, `-32768..32767`).
  - `40003` (Offset 2): DC Bus Voltage in Volts (`uint16`).
  - `40004` (Offset 3): Cell Pack Temperature in °C (signed 16-bit int).
  - `40005` (Offset 4): BMS FSM State enum (`1=INIT, 2=STANDBY, 3=CHARGING, 4=DISCHARGING, 5=FAULT, 6=DEGRADED`).
  - `40006` (Offset 5): Active Power Setpoint in kW (Read/Write, signed 16-bit int).

---

## 4. Storage Architecture
- **TimescaleDB / PostgreSQL:** Time-series tables partitioned by timestamp (`ts`) storing telemetry samples, market price settlements, load profiles, model forecasts, and hourly financial accounting.
- **Relational Tables:** Parameter configurations (`settings`), dispatch schedules, and event audit trails.
- **Automatic Initialization:** The system auto-initializes schemas and seeds 2 years of synthetic energy market data on startup without requiring manual migration commands.

---

## 5. Control & Optimization Pipeline
1. **11:00 Sim-Time (Preliminary Day-Ahead):** EMS runs the active ML forecasting model (LightGBM or LSTM) to predict D+1 prices and load. A preliminary 24-hour dispatch schedule is formed.
2. **13:00 Sim-Time (Market Gate Closure):** Market Simulator publishes official Day-Ahead Market (РДН) clearing prices with Ukrainian price caps applied.
3. **13:05 Sim-Time (Schedule Dispatch):** EMS runs MILP optimization with definitive tariffs, generating the finalized 24-hour setpoint schedule.
4. **Closed-Loop Real-Time Dispatch:**
   - Every simulation tick, Dispatcher reads active schedule setpoint.
   - Applies reactive priority overrides: emergency shutdown, power derating near SoC bounds, anti-islanding grid limits.
   - Initiates rolling re-optimization if closed-loop SoC deviation exceeds tolerance ($\pm 5\%$).
   - Enters autonomous `SAFE_MODE` if BESS telemetry drops for $> 3$ consecutive ticks or enters `FAULT`.
