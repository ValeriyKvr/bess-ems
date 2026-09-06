"""Verify SQLAlchemy declarative models against SPEC §7."""

from ems.db.models import (
    Base,
    BessTelemetry,
)


def test_models_metadata_registered() -> None:
    """Verify all 9 core tables are properly registered in Base.metadata."""
    expected_tables = {
        "bess_telemetry",
        "site_load",
        "dam_prices",
        "forecasts",
        "schedules",
        "dispatch_log",
        "financials",
        "settings",
        "ml_models",
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(actual_tables), (
        f"Missing tables: {expected_tables - actual_tables}"
    )


def test_bess_telemetry_columns() -> None:
    """Verify telemetry model columns."""
    table = BessTelemetry.__table__
    assert "ts" in table.columns
    assert "bess_id" in table.columns
    assert "soc_pct" in table.columns
    assert "power_kw" in table.columns
    assert "alarms" in table.columns
