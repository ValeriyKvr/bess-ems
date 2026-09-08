"""Tests for Simulation Templates and Reporting API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from ems.core.clock import SimulationClock
from ems.db.session import get_db
from ems.main import app, app_state


class DummyDbSession:
    """Mock database session for offline testing."""

    async def execute(self, statement: object) -> object:
        class DummyResult:
            def scalar(self) -> int:
                return 0

            def scalars(self) -> object:
                class ScalarList:
                    def all(self) -> list:
                        return []

                return ScalarList()

            def scalar_one_or_none(self) -> object:
                return None

            def all(self) -> list:
                return []

        return DummyResult()

    async def commit(self) -> None:
        pass


async def override_get_db() -> DummyDbSession:
    return DummyDbSession()


@pytest.mark.asyncio
async def test_get_templates_list() -> None:
    """Test GET /api/sim/templates returns built-in templates."""
    if not app_state.clock:
        app_state.clock = SimulationClock()
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/sim/templates")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        template_ids = [t["id"] for t in data]
        assert "enterprise_september_2026" in template_ids
        assert "march_baseline_2026" in template_ids


@pytest.mark.asyncio
async def test_get_template_details() -> None:
    """Test GET /api/sim/templates/{template_id}."""
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/sim/templates/enterprise_september_2026")
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == "enterprise_september_2026"
        assert data["battery_capacity_kwh"] == 2000.0
        assert data["battery_power_kw"] == 1000.0
        assert data["duration_days"] == 9
        assert data["is_default"] is True


@pytest.mark.asyncio
async def test_template_report_generation() -> None:
    """Test GET /api/sim/templates/{template_id}/report for enterprise template."""
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/sim/templates/enterprise_september_2026/report?days=2")
        assert res.status_code == 200
        data = res.json()
        assert data["template_id"] == "enterprise_september_2026"
        assert data["analyzed_days"] == 2
        assert "kpi" in data
        kpi = data["kpi"]
        assert kpi["baseline_cost_uah"] > 0
        assert kpi["actual_cost_uah"] > 0
        assert kpi["net_savings_uah"] > 0
        assert kpi["savings_pct"] > 0
        assert len(data["daily"]) == 2


@pytest.mark.asyncio
async def test_sim_control_loop_action() -> None:
    """Test POST /api/sim/control with action='loop'."""
    if not app_state.clock:
        app_state.clock = SimulationClock()
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/sim/control",
            json={
                "action": "loop",
                "loop_enabled": True,
                "loop_start": "2026-09-01T00:00:00Z",
                "loop_days": 5,
            },
        )
        assert res.status_code == 200
        clock_data = res.json()["clock"]
        assert clock_data["loop_enabled"] is True
        assert clock_data["loop_start"] == "2026-09-01T00:00:00Z"
        assert clock_data["loop_end"] == "2026-09-06T00:00:00Z"
