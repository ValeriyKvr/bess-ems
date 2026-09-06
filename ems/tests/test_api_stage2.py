"""Tests for Stage 2 API endpoints: sim control, settings, and data."""

import pytest
from httpx import ASGITransport, AsyncClient

from ems.core.clock import SimulationClock
from ems.db.session import get_db
from ems.main import app, app_state


class DummyDbSession:
    """Mock session for offline unit testing."""

    async def execute(self, statement: object) -> object:
        class DummyResult:
            def scalar(self) -> int:
                return 1

            def scalars(self) -> object:
                class ScalarList:
                    def all(self) -> list:
                        return []

                return ScalarList()

            def scalar_one_or_none(self) -> object:
                return None

        return DummyResult()

    async def commit(self) -> None:
        pass


async def override_get_db() -> DummyDbSession:
    return DummyDbSession()


@pytest.mark.asyncio
async def test_api_sim_control() -> None:
    """Test POST /api/sim/control actions."""
    if not app_state.clock:
        app_state.clock = SimulationClock()
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Pause
        res = await client.post("/api/sim/control", json={"action": "pause"})
        assert res.status_code == 200
        data = res.json()
        assert data["clock"]["is_paused"] is True

        # 2. Speed change
        res = await client.post("/api/sim/control", json={"action": "start", "speed": 600})
        assert res.status_code == 200
        data = res.json()
        assert data["clock"]["speed"] == 600
        assert data["clock"]["is_paused"] is False

        # 3. Step
        res = await client.post("/api/sim/control", json={"action": "step", "step_seconds": 60})
        assert res.status_code == 200

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_settings_get_and_put() -> None:
    """Test GET and PUT /api/settings/{section}."""
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET market settings
        res = await client.get("/api/settings/market")
        assert res.status_code == 200
        data = res.json()
        assert "transmission_tariff_uah_mwh" in data

        # PUT updated market settings
        data["supplier_margin_uah_mwh"] = 250.0
        res = await client.put("/api/settings/market", json=data)
        assert res.status_code == 200
        assert res.json()["settings"]["supplier_margin_uah_mwh"] == 250.0

    app.dependency_overrides.clear()
