"""Main execution loop for BESS Simulator service (SPEC §4.3, §5)."""

import logging
import signal
import sys
import time
from datetime import UTC, datetime
from typing import Any

from bess_sim.battery import Battery
from bess_sim.config import BessConfig
from bess_sim.modbus import ModbusServer
from bess_sim.mqtt_io import BessMqttClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bess-sim")


class BessSimulatorApp:
    """Orchestrates BESS physical modeling, time stepping, and MQTT messaging."""

    def __init__(self, config: BessConfig | None = None) -> None:
        self.config = config or BessConfig()
        self.battery = Battery(config=self.config.battery, bess_id=self.config.bess_id)
        self.running = False

        self.current_setpoint_kw: float = 0.0
        self.last_sim_time: str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.last_sim_datetime: datetime = datetime.now(UTC)
        self.last_clock_msg_wall_ts: float = 0.0
        self.last_wall_tick_ts: float = time.time()
        self.last_published_state: str = ""
        self.last_known_alarms: set[str] = set()

        self.modbus: ModbusServer | None = None
        if self.config.enable_modbus:
            self.modbus = ModbusServer(
                port=self.config.modbus_port,
                on_setpoint_write=self._on_modbus_setpoint,
            )

        self.mqtt = BessMqttClient(
            config=self.config,
            on_clock_tick=self.on_clock_tick,
            on_setpoint=self.on_setpoint,
            on_command=self.on_command,
        )

    def _on_modbus_setpoint(self, setpoint_kw: float) -> None:
        """Handle active power setpoint received via Modbus TCP (SPEC §4.2)."""
        logger.info("Modbus setpoint received: %.2f kW", setpoint_kw)
        self.current_setpoint_kw = setpoint_kw

    def on_clock_tick(self, payload: dict[str, Any]) -> None:
        """Handle incoming clock tick from EMS (SPEC §4.3)."""
        self.last_clock_msg_wall_ts = time.time()
        ts_sim_str = payload.get("ts_sim")
        if not ts_sim_str:
            return

        try:
            current_sim_dt = datetime.fromisoformat(ts_sim_str.replace("Z", "+00:00"))
        except Exception:
            current_sim_dt = datetime.now(UTC)

        # Calculate simulation dt elapsed since previous tick
        dt_seconds = (current_sim_dt - self.last_sim_datetime).total_seconds()
        if dt_seconds <= 0 or dt_seconds > 3600.0:
            # First tick, clock jump or reset: clamp to standard 60s step
            dt_seconds = 60.0

        self.last_sim_datetime = current_sim_dt
        self.last_sim_time = ts_sim_str

        # Execute physical simulation step
        self._execute_step(dt_seconds=dt_seconds)

    def on_setpoint(self, payload: dict[str, Any]) -> None:
        """Handle active power setpoint dispatched from EMS (SPEC §4.3)."""
        try:
            setpoint_val = payload.get("setpoint_kw", payload.get("power_kw", 0.0))
            setpoint = float(setpoint_val)
            reason = payload.get("reason", "manual")
            logger.info("New setpoint: %.2f kW (reason: %s)", setpoint, reason)
            self.current_setpoint_kw = setpoint
        except (ValueError, TypeError) as e:
            logger.error("Failed to parse setpoint payload: %s", e)

    def on_command(self, payload: dict[str, Any]) -> None:
        """Handle supervisory commands and fault injection (SPEC §4.3, §5.3)."""
        cmd = payload.get("cmd", "")
        logger.info("Processing command: %s (payload=%s)", cmd, payload)

        # 1. Fault injection commands
        if cmd == "fault_injection":
            fault_type = payload.get("type", "")
            if fault_type == "comms_dropout":
                duration = float(payload.get("duration_s", 60.0))
                self.mqtt.trigger_comms_dropout(duration)
            elif fault_type == "force_overheat":
                self.battery.set_fault_injection("force_overheat", enabled=True)
            elif fault_type == "soc_noise":
                enabled = payload.get("enabled", True)
                self.battery.set_fault_injection("soc_noise", enabled=enabled)
            elif fault_type == "power_limit_50":
                enabled = payload.get("enabled", True)
                self.battery.set_fault_injection("power_limit_50", enabled=enabled)
            elif fault_type == "clear_all":
                self.battery.set_fault_injection("clear_all")

        elif cmd == "force_overheat":
            self.battery.set_fault_injection("force_overheat", enabled=True)

        elif cmd in ("reset_alarm", "start", "stop", "standby"):
            # Standard BMS FSM commands
            if cmd == "reset_alarm":
                # Also reset forced overheat if it was injected
                self.battery.set_fault_injection("clear_all")

            success = self.battery.handle_command(cmd)
            if success:
                self.mqtt.publish_status(str(self.battery.bms.state), f"Command {cmd} executed")

    def _execute_step(self, dt_seconds: float) -> None:
        """Execute physical model step and broadcast telemetry/status/alarms."""
        ts_wall = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        telemetry_data = self.battery.step(
            setpoint_kw=self.current_setpoint_kw,
            dt_seconds=dt_seconds,
            ts_sim=self.last_sim_time,
            ts_wall=ts_wall,
        )

        # Check for state changes -> publish to bess/{id}/status
        if telemetry_data.state != self.last_published_state:
            self.last_published_state = telemetry_data.state
            self.mqtt.publish_status(
                telemetry_data.state, f"State transitioned to {telemetry_data.state}"
            )

        # Check for new alarms -> publish to bess/{id}/alarm
        current_alarms = set(telemetry_data.alarms)
        new_alarms = current_alarms - self.last_known_alarms
        for alarm in new_alarms:
            self.mqtt.publish_alarm(alarm, f"Protective trip at SoC={telemetry_data.soc_pct:.1f}%")
        self.last_known_alarms = current_alarms

        # Publish telemetry to bess/{id}/telemetry
        self.mqtt.publish_telemetry(telemetry_data.to_dict())

        # Update Modbus holding registers
        if self.modbus:
            self.modbus.update_telemetry(
                soc_pct=telemetry_data.soc_pct,
                power_kw=telemetry_data.power_kw,
                voltage_v=telemetry_data.voltage_v,
                temp_c=telemetry_data.temp_c,
                state_str=telemetry_data.state,
            )

    def run_wall_clock_fallback(self) -> None:
        """Fallback stepping when sim/clock is not received from EMS."""
        now_ts = time.time()
        elapsed = now_ts - self.last_wall_tick_ts

        # Fallback period: default 1 second wall clock
        interval_seconds = max(0.5, self.config.telemetry_interval_ms / 1000.0)
        if elapsed >= interval_seconds:
            # If no external clock has been seen for > 2.0 seconds, advance in real time
            if (now_ts - self.last_clock_msg_wall_ts) > 2.0:
                self.last_sim_datetime = datetime.now(UTC)
                self.last_sim_time = self.last_sim_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
                self._execute_step(dt_seconds=elapsed)
            self.last_wall_tick_ts = now_ts

    def start(self) -> None:
        """Start BESS simulator loop."""
        logger.info("Starting BESS Simulator service (ID: %s)...", self.config.bess_id)
        self.running = True
        self.mqtt.connect()

        # Start Modbus server if enabled
        if self.modbus:
            self.modbus.start()

        # Publish initial status
        self.last_published_state = str(self.battery.bms.state)
        self.mqtt.publish_status(self.last_published_state, "BESS Simulator Online")

        while self.running:
            self.run_wall_clock_fallback()
            time.sleep(0.1)

    def stop(self) -> None:
        """Stop simulator and disconnect."""
        logger.info("Stopping BESS Simulator service...")
        self.running = False
        if self.modbus:
            self.modbus.stop()
        self.mqtt.disconnect()


def main() -> None:
    """Service entrypoint."""
    app = BessSimulatorApp()

    def handle_signal(sig: int, frame: Any) -> None:
        logger.info("Received signal %d, shutting down...", sig)
        app.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        app.start()
    except KeyboardInterrupt:
        app.stop()


if __name__ == "__main__":
    main()
