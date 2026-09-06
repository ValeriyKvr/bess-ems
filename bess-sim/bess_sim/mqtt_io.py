"""MQTT Communication Layer for BESS Simulator (SPEC §4.3)."""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from bess_sim.config import BessConfig

logger = logging.getLogger(__name__)


class BessMqttClient:
    """Handles MQTT connection, subscriptions, and telemetry publishing for BESS."""

    def __init__(
        self,
        config: BessConfig,
        on_clock_tick: Callable[[dict[str, Any]], None] | None = None,
        on_setpoint: Callable[[dict[str, Any]], None] | None = None,
        on_command: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.on_clock_tick = on_clock_tick
        self.on_setpoint = on_setpoint
        self.on_command = on_command

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"bess-sim-{self.config.bess_id}",
        )
        self.is_connected = False

        # Fault injection state for communications dropout (§5.3)
        self.comms_dropout_until_ts: float = 0.0

        self._setup_callbacks()

    def _setup_callbacks(self) -> None:
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        rc: mqtt.ReasonCode,
        properties: Any = None,
    ) -> None:
        if rc.is_failure:
            logger.error("Failed to connect to MQTT broker, code: %s", rc)
            self.is_connected = False
            return

        logger.info(
            "Connected to MQTT broker at %s:%s",
            self.config.mqtt_broker_host,
            self.config.mqtt_broker_port,
        )
        self.is_connected = True

        try:
            Path("/tmp/healthy").touch()
        except OSError:
            pass

        # Subscribe to topics defined in SPEC §4.3
        topics = [
            ("sim/clock", 0),
            (f"ems/{self.config.bess_id}/setpoint", 1),
            (f"ems/{self.config.bess_id}/command", 1),
        ]
        self.client.subscribe(topics)
        logger.info("BESS subscribed to topics: %s", topics)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        rc: mqtt.ReasonCode,
        properties: Any = None,
    ) -> None:
        logger.warning("Disconnected from MQTT broker: %s", rc)
        self.is_connected = False

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            logger.error("Failed to decode JSON on topic %s: %s", msg.topic, e)
            return

        if msg.topic == "sim/clock" and self.on_clock_tick:
            self.on_clock_tick(payload)
        elif msg.topic == f"ems/{self.config.bess_id}/setpoint" and self.on_setpoint:
            self.on_setpoint(payload)
        elif msg.topic == f"ems/{self.config.bess_id}/command" and self.on_command:
            self.on_command(payload)

    def connect(self) -> None:
        """Connect to MQTT broker and start network loop."""
        try:
            self.client.connect(
                self.config.mqtt_broker_host,
                self.config.mqtt_broker_port,
                self.config.mqtt_keepalive,
            )
            self.client.loop_start()
        except Exception as e:
            logger.warning(
                "Could not immediately connect to MQTT broker (%s). Will retry in background.", e
            )

    def disconnect(self) -> None:
        """Stop network loop and disconnect cleanly."""
        self.client.loop_stop()
        self.client.disconnect()
        self.is_connected = False
        try:
            healthy_file = Path("/tmp/healthy")
            if healthy_file.exists():
                healthy_file.unlink()
        except OSError:
            pass

    def trigger_comms_dropout(self, duration_seconds: float) -> None:
        """Simulate communication dropout for duration_seconds (§5.3)."""
        logger.warning("Triggering comms dropout for %.1f seconds", duration_seconds)
        self.comms_dropout_until_ts = time.time() + duration_seconds

    def is_comms_dropped(self) -> bool:
        """Check if comms dropout fault is active."""
        return time.time() < self.comms_dropout_until_ts

    def publish_telemetry(self, data: dict[str, Any]) -> None:
        """Publish telemetry to bess/{id}/telemetry if comms are active."""
        if self.is_comms_dropped():
            logger.debug("Telemetry suppressed due to simulated comms dropout")
            return

        topic = f"bess/{self.config.bess_id}/telemetry"
        self.client.publish(topic, json.dumps(data), qos=0)

    def publish_status(self, state: str, message: str = "") -> None:
        """Publish state change to bess/{id}/status (SPEC §4.3)."""
        topic = f"bess/{self.config.bess_id}/status"
        payload = {
            "bess_id": self.config.bess_id,
            "state": state,
            "message": message,
            "ts_wall": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.client.publish(topic, json.dumps(payload), qos=1, retain=True)

    def publish_alarm(self, alarm_type: str, details: str = "") -> None:
        """Publish alarm event to bess/{id}/alarm (SPEC §4.3)."""
        topic = f"bess/{self.config.bess_id}/alarm"
        payload = {
            "bess_id": self.config.bess_id,
            "alarm": alarm_type,
            "details": details,
            "ts_wall": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.client.publish(topic, json.dumps(payload), qos=1)
