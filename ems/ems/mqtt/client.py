"""MQTT Client integration for EMS Core with batched telemetry persistence."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from ems.core.config import EmsSettings
from ems.db.models import BessTelemetry

logger = logging.getLogger(__name__)


class EmsMqttClient:
    """Manages EMS interaction with the Mosquitto MQTT broker and telemetry ingestion."""

    def __init__(
        self,
        settings: EmsSettings,
        session_factory: async_sessionmaker | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="ems-core",
        )
        self.is_connected = False
        self.latest_bess_telemetry: dict[str, Any] = {}
        self.latest_bess_status: dict[str, Any] = {}

        # Telemetry ingestion batch queue
        self._telemetry_buffer: list[dict[str, Any]] = []
        self._buffer_lock = asyncio.Lock() if asyncio.get_event_loop().is_running() else None
        self._flush_task: asyncio.Task[None] | None = None

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
            logger.error("EMS failed to connect to MQTT broker, code: %s", rc)
            self.is_connected = False
            return

        logger.info(
            "EMS connected to MQTT broker at %s:%d",
            self.settings.mqtt_broker_host,
            self.settings.mqtt_broker_port,
        )
        self.is_connected = True

        # Subscribe to BESS topics (SPEC §4.3)
        topics = [
            ("bess/+/telemetry", 0),
            ("bess/+/status", 1),
            ("bess/+/alarm", 1),
        ]
        self.client.subscribe(topics)
        logger.info("EMS subscribed to topics: %s", topics)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        rc: mqtt.ReasonCode,
        properties: Any = None,
    ) -> None:
        logger.warning("EMS disconnected from MQTT broker: %s", rc)
        self.is_connected = False

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            logger.error("Failed to parse JSON on topic %s: %s", msg.topic, e)
            return

        if "/telemetry" in msg.topic:
            bess_id = payload.get("bess_id", "unknown")
            self.latest_bess_telemetry[bess_id] = payload
            self._telemetry_buffer.append(payload)
            logger.debug(
                "Received telemetry from %s: SoC=%.1f%%", bess_id, payload.get("soc_pct", 0.0)
            )
        elif "/status" in msg.topic:
            bess_id = payload.get("bess_id", "unknown")
            self.latest_bess_status[bess_id] = payload
            logger.info(
                "Received status update from %s: %s", bess_id, payload.get("state", "UNKNOWN")
            )

    def connect(self) -> None:
        """Connect to broker and start background network thread."""
        try:
            logger.info(
                "EMS connecting to MQTT broker at %s:%d...",
                self.settings.mqtt_broker_host,
                self.settings.mqtt_broker_port,
            )
            self.client.connect(
                self.settings.mqtt_broker_host,
                self.settings.mqtt_broker_port,
                self.settings.mqtt_keepalive,
            )
            self.client.loop_start()
        except Exception as e:
            logger.warning(
                "Could not immediately connect to MQTT broker (%s). Will retry in background.", e
            )

    def disconnect(self) -> None:
        """Stop background network loop and disconnect."""
        logger.info("EMS disconnecting MQTT...")
        self.client.loop_stop()
        self.client.disconnect()
        self.is_connected = False

    def publish_clock(self, clock_data: dict[str, Any]) -> None:
        """Broadcast simulation clock tick to sim/clock."""
        self.client.publish("sim/clock", json.dumps(clock_data), qos=0)

    def publish_setpoint(self, bess_id: str, setpoint_data: dict[str, Any]) -> None:
        """Publish dispatch setpoint to ems/{id}/setpoint."""
        topic = f"ems/{bess_id}/setpoint"
        self.client.publish(topic, json.dumps(setpoint_data), qos=1)

    def publish_config(self, bess_id: str, battery_params: dict[str, Any]) -> None:
        """Publish battery parameters to ems/{id}/config as a retained message.

        Retained so the simulator receives the operator's parameters on connect,
        regardless of which service starts first.
        """
        topic = f"ems/{bess_id}/config"
        self.client.publish(topic, json.dumps(battery_params), qos=1, retain=True)
        logger.info("Published BESS configuration to %s (%d fields)", topic, len(battery_params))

    def publish_command(self, bess_id: str, cmd_data: dict[str, Any] | str) -> None:
        """Publish control command to ems/{id}/command."""
        topic = f"ems/{bess_id}/command"
        payload = {"cmd": cmd_data} if isinstance(cmd_data, str) else cmd_data
        self.client.publish(topic, json.dumps(payload), qos=1)

    async def start_telemetry_flusher(self) -> None:
        """Background coroutine flushing telemetry buffer into TimescaleDB."""
        if not self.session_factory:
            return

        while True:
            await asyncio.sleep(1.0)
            if not self._telemetry_buffer:
                continue

            # Drain buffer
            batch = self._telemetry_buffer[:]
            self._telemetry_buffer.clear()

            try:
                async with self.session_factory() as session:
                    records = []
                    for item in batch:
                        ts_val = item.get("ts_sim") or item.get("ts_wall")
                        if not ts_val:
                            continue
                        dt = datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
                        records.append(
                            {
                                "ts": dt,
                                "bess_id": item.get("bess_id", "bess-01"),
                                "soc_pct": item.get("soc_pct"),
                                "soh_pct": item.get("soh_pct"),
                                "soe_kwh": item.get("soe_kwh"),
                                "power_kw": item.get("power_kw"),
                                "voltage_v": item.get("voltage_v"),
                                "current_a": item.get("current_a"),
                                "temp_c": item.get("temp_c"),
                                "state": item.get("state"),
                                "alarms": item.get("alarms"),
                            }
                        )

                    if records:
                        stmt = insert(BessTelemetry).values(records).on_conflict_do_nothing()
                        await session.execute(stmt)
                        await session.commit()
                        logger.debug("Flushed %d telemetry records to TimescaleDB", len(records))
            except Exception as e:
                logger.error("Failed to flush telemetry batch to database: %s", e)
