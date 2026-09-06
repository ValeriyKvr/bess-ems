# MQTT Communication Protocol Specification

**Version:** 1.0  
**Compliance:** SPEC §4.3, §5.3, GEMINI.md  

## 1. Overview

The Battery Energy Storage System (BESS) and Energy Management System (EMS) are completely decoupled
processes that communicate strictly via MQTT (Mosquitto broker, port 1883).

---

## 2. Topic Summary

| Topic | Direction | Frequency | QoS | Retain | Description |
|---|---|---|---|---|---|
| `sim/clock` | EMS → All | Each simulation tick | 0 | No | Broadcast of unified simulation time |
| `ems/{id}/setpoint` | EMS → BESS | On schedule change / dispatch | 1 | No | Active power setpoint command |
| `ems/{id}/command` | EMS → BESS | On supervisory event / test | 1 | No | Operational commands & fault injection |
| `bess/{id}/telemetry` | BESS → EMS | Each simulation tick (1 min default) | 0 | No | Complete electrical & thermal state |
| `bess/{id}/status` | BESS → EMS | On state transition / periodic | 1 | Yes | FSM operational state |
| `bess/{id}/alarm` | BESS → EMS | On protective trip event | 1 | No | Safety & threshold violation alarms |

---

## 3. Message Schemas

### 3.1. Telemetry (`bess/{id}/telemetry`)
Published every tick by the BESS simulator.

```json
{
  "ts_sim": "2026-03-14T18:00:00Z",
  "ts_wall": "2026-09-06T14:22:31.120Z",
  "bess_id": "bess-01",
  "soc_pct": 63.4,
  "soh_pct": 98.7,
  "soe_kwh": 634.0,
  "power_kw": -180.0,
  "voltage_v": 782.4,
  "current_a": -230.1,
  "temp_c": 31.2,
  "cycles_total": 412.5,
  "throughput_kwh": 825000.0,
  "state": "DISCHARGING",
  "available_charge_kw": 250.0,
  "available_discharge_kw": 250.0,
  "alarms": []
}
```

#### Fields Description
- `ts_sim` *(string, ISO 8601 UTC)*: Current simulation timestamp.
- `ts_wall` *(string, ISO 8601 UTC)*: Wall-clock generation timestamp.
- `bess_id` *(string)*: Unique identifier of the BESS unit.
- `soc_pct` *(float, %)*: State of Charge (0.0 to 100.0).
- `soh_pct` *(float, %)*: State of Health (capacity retention, % of nominal).
- `soe_kwh` *(float, kWh)*: State of Energy remaining.
- `power_kw` *(float, kW)*: Active power flow. **Sign convention: `> 0` = Charging, `< 0` = Discharging**.
- `voltage_v` *(float, V)*: DC bus voltage computed from 10-point LFP Open Circuit Voltage (OCV) curve.
- `current_a` *(float, A)*: DC current ($I = P \cdot 1000 / V$).
- `temp_c` *(float, °C)*: Cell temperature governed by thermodynamic heat balance.
- `cycles_total` *(float)*: Cumulative equivalent full cycles ($|\Delta E| / (2 \cdot \text{Capacity})$).
- `throughput_kwh` *(float, kWh)*: Cumulative absolute energy processed across battery terminals.
- `state` *(string)*: Operational state (`OFFLINE`, `STANDBY`, `CHARGING`, `DISCHARGING`, `IDLE`, `FAULT`).
- `available_charge_kw` *(float, kW)*: Dynamic charging limit taking linear SoC de-rating into account.
- `available_discharge_kw` *(float, kW)*: Dynamic discharging limit taking linear SoC de-rating into account.
- `alarms` *(array of strings)*: List of currently active protection alarm codes.

---

### 3.2. Active Setpoint (`ems/{id}/setpoint`)
Published by the EMS dispatcher to command active power.

```json
{
  "ts_sim": "2026-03-14T18:00:00Z",
  "setpoint_kw": -180.0,
  "mode": "P_CONST",
  "valid_until_sim": "2026-03-14T19:00:00Z",
  "reason": "SCHEDULE_DISCHARGE_ARBITRAGE",
  "schedule_id": "sch_20260314_v2"
}
```

---

### 3.3. Status Update (`bess/{id}/status`)
Published on operational state change with retained flag.

```json
{
  "bess_id": "bess-01",
  "state": "STANDBY",
  "message": "BESS Simulator Online",
  "ts_wall": "2026-09-06T14:22:31Z"
}
```

---

### 3.4. Alarms (`bess/{id}/alarm`)
Published whenever protective thresholds are breached.

```json
{
  "bess_id": "bess-01",
  "alarm": "OVERHEAT: 46.2°C > 45.0°C",
  "details": "Protective trip at SoC=63.4%",
  "ts_wall": "2026-09-06T14:22:31Z"
}
```

---

### 3.5. Simulation Clock (`sim/clock`)
Published by EMS master clock every simulation tick.

```json
{
  "ts_sim": "2026-03-14T18:00:00Z",
  "speed": 60,
  "is_paused": false
}
```

---

### 3.6. Supervisory Commands & Fault Injection (`ems/{id}/command`)

#### Standard Lifecycle Commands
- `{"cmd": "start"}`: Move from `OFFLINE` to `STANDBY`.
- `{"cmd": "stop"}`: Move from operational state to `OFFLINE`.
- `{"cmd": "standby"}`: Move to `STANDBY` (zero power idle).
- `{"cmd": "reset_alarm"}`: Attempt recovery from `FAULT` to `STANDBY` (succeeds only if temperatures and SoC are within safe ranges).

#### Fault Injection Commands (SPEC §5.3)
- **Forced Overheat:**
  ```json
  {"cmd": "fault_injection", "type": "force_overheat"}
  ```
  Immediately forces temperature above `temp_max_c`, tripping FSM into `FAULT` and triggering alarm.
- **Communication Dropout:**
  ```json
  {"cmd": "fault_injection", "type": "comms_dropout", "duration_s": 60.0}
  ```
  Suppresses all telemetry publication for the specified duration to test EMS timeout handling.
- **SoC Noise:**
  ```json
  {"cmd": "fault_injection", "type": "soc_noise", "enabled": true}
  ```
  Injects Gaussian noise ($\pm 0.5\%$) into reported SoC.
- **Power Derating Limit:**
  ```json
  {"cmd": "fault_injection", "type": "power_limit_50", "enabled": true}
  ```
  Caps PCS active power rating by 50%.
- **Clear Faults:**
  ```json
  {"cmd": "fault_injection", "type": "clear_all"}
  ```
