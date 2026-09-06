"""Stage 7 tests: Settings schema & updates, Data preview & heatmap, Reports & XLSX, Logs pagination & Fault injection."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

import ems.api.optimize
import ems.api.settings
import ems.db.session
from ems.core.clock import SimulationClock
from ems.db.models import DispatchLog, Financial
from ems.db.session import get_db
from ems.main import app, app_state
from ems.market.simulator import MarketSimulator


class SettingRow:
    def __init__(self, val: dict) -> None:
        self.value = val


class MockDbSession:
    """Mock database session that handles settings persistence, queries, and commits."""

    def __init__(self) -> None:
        self.settings_store: dict[str, dict] = {}
        self.committed = False

    async def execute(self, statement: object) -> object:
        stmt_str = str(statement)

        class MockResult:
            def __init__(self, store: dict) -> None:
                self.store = store

            def scalar(self) -> int:
                return 48

            def scalar_one(self) -> int:
                return 10

            def scalar_one_or_none(self) -> object:
                # Setting table queries (Setting.key == ...)
                for sec, val in self.store.items():
                    if f"'{sec}'" in stmt_str or f'"{sec}"' in stmt_str or ":key_1" in stmt_str:
                        return SettingRow(val)
                return None

            def all(self) -> list:
                # Heatmap sample rows: (ts, value)
                base = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
                return [(base + timedelta(hours=i), 3500.0 + (i % 24) * 50) for i in range(24 * 7)]

            def scalars(self) -> object:
                class ScalarList:
                    def all(self) -> list:
                        base = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
                        if "dam_price" in stmt_str.lower():
                            from ems.db.models import DamPrice

                            return [
                                DamPrice(
                                    ts=base + timedelta(hours=i),
                                    price_uah_mwh=3000.0 + (i % 24) * 100.0,
                                )
                                for i in range(48)
                            ]
                        if "financial" in stmt_str.lower():
                            return [
                                Financial(
                                    ts=base + timedelta(hours=i),
                                    cost_baseline_uah=100.0,
                                    cost_actual_uah=80.0,
                                    revenue_uah=10.0,
                                    degradation_uah=2.0,
                                    net_uah=28.0,
                                    import_kwh=50.0,
                                    export_kwh=10.0,
                                    price_buy=2000.0,
                                    price_sell=1800.0,
                                )
                                for i in range(24)
                            ]
                        # Dummy DispatchLog rows
                        return [
                            DispatchLog(
                                ts=base + timedelta(minutes=i),
                                setpoint_kw=250.0,
                                actual_kw=248.0,
                                reason="SCHEDULE_SETPOINT",
                                schedule_id="sched-test-01",
                                override=False,
                            )
                            for i in range(5)
                        ]

                return ScalarList()

        return MockResult(self.settings_store)

    def add(self, obj: object) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True


_shared_mock_db = MockDbSession()


class MockSessionFactory:
    def __call__(self) -> "MockSessionFactory":
        return self

    async def __aenter__(self) -> MockDbSession:
        return _shared_mock_db

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        pass


async def override_get_db() -> MockDbSession:
    return _shared_mock_db


@pytest.fixture(autouse=True)
def setup_app_state(monkeypatch: pytest.MonkeyPatch) -> None:
    if not app_state.clock:
        app_state.clock = SimulationClock()
    if not app_state.market:
        app_state.market = MarketSimulator()
    mock_mqtt = MagicMock()
    mock_mqtt.is_connected = True
    app_state.mqtt = mock_mqtt
    app.dependency_overrides[get_db] = override_get_db

    mock_fac = MockSessionFactory()
    monkeypatch.setattr(ems.db.session, "async_session_factory", mock_fac)
    monkeypatch.setattr(ems.api.optimize, "async_session_factory", mock_fac)


@pytest.mark.asyncio
async def test_settings_schema_and_update() -> None:
    """Test schema extraction, updating battery settings, and propagation to optimization."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET /api/settings/battery/schema
        res = await client.get("/api/settings/battery/schema")
        assert res.status_code == 200
        data = res.json()
        assert data["section"] == "battery"
        assert "properties" in data["schema"]
        assert "capacity_kwh" in data["schema"]["properties"]
        assert "capacity_kwh" in data["requires_restart"]

        # 2. PUT /api/settings/battery with new capacity
        put_res = await client.put(
            "/api/settings/battery",
            json={
                "capacity_kwh": 1500.0,
                "power_max_kw": 400.0,
                "soc_min_pct": 10.0,
                "soc_max_pct": 90.0,
                "reserve_soc_pct": 20.0,
                "roundtrip_efficiency": 0.88,
            },
        )
        assert put_res.status_code == 200
        put_data = put_res.json()
        assert put_data["status"] == "updated"
        assert put_data["settings"]["capacity_kwh"] == 1500.0

        # Save into mock db store for helper lookups
        _shared_mock_db.settings_store["battery"] = put_data["settings"]

        # 3. Trigger optimization to verify capacity_kwh propagation into Schedule
        now_iso = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC).isoformat()
        opt_res = await client.post(
            "/api/optimize/run",
            json={
                "strategy": "ARBITRAGE",
                "target_date": now_iso,
                "forecast_source": "oracle",
            },
        )
        assert opt_res.status_code == 200
        opt_data = opt_res.json()
        assert opt_data["strategy"] == "ARBITRAGE"
        assert opt_data["capacity_kwh"] == 1500.0
        assert opt_data["items_count"] == 48


@pytest.mark.asyncio
async def test_data_preview_and_import() -> None:
    """Test CSV preview and import endpoints using sample files."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Sample DAM prices
        sample_dam = Path("../data/samples/sample_dam_prices.csv")
        if not sample_dam.exists():
            sample_dam = Path("data/samples/sample_dam_prices.csv")
        assert sample_dam.exists()

        with open(sample_dam, "rb") as f:
            files = {"file": ("sample_dam_prices.csv", f.read(), "text/csv")}

        preview_res = await client.post("/api/data/preview", files=files)
        assert preview_res.status_code == 200
        p_data = preview_res.json()
        assert p_data["is_valid"] is True
        assert p_data["detected_type"] == "price"
        assert p_data["total_rows"] == 48
        assert len(p_data["preview_rows"]) == 20

        # Import endpoint
        with open(sample_dam, "rb") as f:
            files = {"file": ("sample_dam_prices.csv", f.read(), "text/csv")}
        import_res = await client.post("/api/data/import?type=price", files=files)
        assert import_res.status_code == 200
        i_data = import_res.json()
        assert i_data["imported_rows"] == 48

        # 2. Sample Load
        sample_load = Path("../data/samples/sample_site_load.csv")
        if not sample_load.exists():
            sample_load = Path("data/samples/sample_site_load.csv")
        assert sample_load.exists()

        with open(sample_load, "rb") as f:
            files = {"file": ("sample_site_load.csv", f.read(), "text/csv")}

        preview_load = await client.post("/api/data/preview", files=files)
        assert preview_load.status_code == 200
        pl_data = preview_load.json()
        assert pl_data["is_valid"] is True
        assert pl_data["detected_type"] == "load"
        assert pl_data["total_rows"] == 48


@pytest.mark.asyncio
async def test_data_heatmap() -> None:
    """Test 24h x 7d heatmap endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/data/heatmap?type=price")
        assert res.status_code == 200
        data = res.json()
        assert len(data["x_categories"]) == 24
        assert len(data["y_categories"]) == 7
        assert len(data["data"]) == 24 * 7
        assert data["unit"] == "грн/МВт·год"


@pytest.mark.asyncio
async def test_reports_summary_and_export() -> None:
    """Test reports JSON summary and XLSX / CSV exports."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # JSON format
        res_json = await client.get("/api/reports/summary?format=json")
        assert res_json.status_code == 200
        data = res_json.json()
        assert "summary" in data
        assert "hourly" in data
        assert data["summary"]["total_cost_baseline_uah"] >= 0

        # XLSX export
        res_xlsx = await client.get("/api/reports/summary?format=xlsx")
        assert res_xlsx.status_code == 200
        assert "spreadsheetml" in res_xlsx.headers.get("content-type", "")
        assert len(res_xlsx.content) > 1000  # Valid binary Excel file

        # CSV export
        res_csv = await client.get("/api/reports/summary?format=csv")
        assert res_csv.status_code == 200
        assert "text/csv" in res_csv.headers.get("content-type", "")
        text = res_csv.text
        assert "Базова вартість" in text or "Чистий ефект" in text


@pytest.mark.asyncio
async def test_compare_strategies() -> None:
    """Test strategy comparison tool across optimization strategies."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/reports/compare-strategies?date=2026-03-01")
        assert res.status_code == 200
        data = res.json()
        assert data["date"] == "2026-03-01"
        assert len(data["comparison"]) == 4
        strategy_names = [item["strategy"] for item in data["comparison"]]
        assert "TOU_SIMPLE" in strategy_names
        assert "ARBITRAGE" in strategy_names
        assert "PEAK_SHAVING" in strategy_names
        assert "SELF_CONSUMPTION" in strategy_names


@pytest.mark.asyncio
async def test_dispatch_log_pagination_and_filter() -> None:
    """Test paginated dispatch log endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/dispatch/log?page=1&limit=5&override=false")
        assert res.status_code == 200
        data = res.json()
        assert data["page"] == 1
        assert data["limit"] == 5
        assert len(data["items"]) == 5
        assert data["total"] >= 5


@pytest.mark.asyncio
async def test_fault_injection_endpoint() -> None:
    """Test fault injection command submission over MQTT."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/bess/fault-injection",
            json={"type": "force_overheat", "bess_id": "bess-01"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["type"] == "force_overheat"
        assert data["bess_id"] == "bess-01"
        # Verify MQTT publish_command was called
        app_state.mqtt.publish_command.assert_called_once()
