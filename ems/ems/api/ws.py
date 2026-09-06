"""WebSocket /ws/telemetry endpoint (SPEC §10.2).

Pushes tick data to connected clients each simulation tick.
When speed ≥ 600, throttles to ≤10 messages/second to avoid flooding.
Events (type: "event") are separate messages.
"""

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


class WebSocketManager:
    """Manages WebSocket connections and broadcasts tick/event messages."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

        # Throttling state for high-speed simulation
        self._last_send_wall: float = 0.0
        self._min_send_interval: float = 0.0  # 0 = no throttle
        self._pending_tick: dict[str, Any] | None = None

    @property
    def connection_count(self) -> int:
        """Number of active WebSocket connections."""
        return len(self._connections)

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        logger.info("WebSocket client connected (total: %d)", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        """Unregister a disconnected WebSocket client."""
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        logger.info("WebSocket client disconnected (total: %d)", len(self._connections))

    def update_throttle(self, speed: int) -> None:
        """Adjust send throttle based on simulation speed.

        For speed ≥ 600, limit to ≤10 messages/second (100ms interval).
        """
        if speed >= 600:
            self._min_send_interval = 0.1  # 10 msg/s max
        else:
            self._min_send_interval = 0.0

    async def broadcast_tick(self, payload: dict[str, Any]) -> None:
        """Broadcast a tick message to all connected clients.

        Respects throttle: if too fast, stores payload and skips broadcast.
        """
        if not self._connections:
            return

        now = time.monotonic()
        if self._min_send_interval > 0:
            elapsed = now - self._last_send_wall
            if elapsed < self._min_send_interval:
                # Store latest tick but don't send yet — throttled
                self._pending_tick = payload
                return

        self._last_send_wall = now
        self._pending_tick = None

        msg = json.dumps({"type": "tick", **payload})
        await self._broadcast_raw(msg)

    async def broadcast_event(self, event: dict[str, Any]) -> None:
        """Broadcast an event message to all connected clients.

        Events are never throttled — they are always sent immediately.
        """
        if not self._connections:
            return
        msg = json.dumps({"type": "event", **event})
        await self._broadcast_raw(msg)

    async def flush_pending(self) -> None:
        """Flush any pending throttled tick to all clients."""
        if self._pending_tick and self._connections:
            msg = json.dumps({"type": "tick", **self._pending_tick})
            self._pending_tick = None
            self._last_send_wall = time.monotonic()
            await self._broadcast_raw(msg)

    async def _broadcast_raw(self, msg: str) -> None:
        """Send raw message string to all connected clients, removing broken ones."""
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    if ws in self._connections:
                        self._connections.remove(ws)
            logger.debug("Removed %d dead WebSocket connections", len(dead))

    async def close_all(self) -> None:
        """Close all active WebSocket connections (shutdown)."""
        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.close()
                except Exception:
                    pass
            self._connections.clear()


# Singleton instance
ws_manager = WebSocketManager()


@router.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time telemetry (SPEC §10.2).

    Server pushes tick data on each simulation tick.
    Client can send JSON messages for control (future use).
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; handle client messages if any
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Client heartbeat / control messages (future)
                logger.debug("WS client sent: %s", data[:100])
            except TimeoutError:
                # Send ping to keep alive
                try:
                    await websocket.send_json(
                        {"type": "ping", "ts": datetime.now(tz=UTC).isoformat()}
                    )
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("WebSocket error: %s", e)
    finally:
        await ws_manager.disconnect(websocket)
