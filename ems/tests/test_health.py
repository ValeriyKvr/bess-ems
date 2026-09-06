"""Test health and status endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from ems.db.session import get_db
from ems.main import app


class DummyDbSession:
    """Mock session for offline unit testing."""

    async def execute(self, statement: object) -> object:
        class DummyResult:
            def scalar(self) -> int:
                return 1

        return DummyResult()


async def override_get_db() -> DummyDbSession:
    return DummyDbSession()


@pytest.mark.asyncio
async def test_api_health_endpoint() -> None:
    """Verify /api/health returns healthy with mocked db."""
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ems-core"
        assert data["database"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_status_endpoint() -> None:
    """Verify /api/status returns valid JSON structure."""
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "clock" in data
    app.dependency_overrides.clear()
