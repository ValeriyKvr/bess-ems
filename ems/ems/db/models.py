"""SQLAlchemy 2 declarative database models matching SPEC §7."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarative class."""

    pass


class BessTelemetry(Base):
    """Raw BESS telemetry time series from MQTT."""

    __tablename__ = "bess_telemetry"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bess_id: Mapped[str] = mapped_column(String(64), nullable=False)
    soc_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    soh_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    soe_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    voltage_v: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    alarms: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("ts", "bess_id", name="pk_bess_telemetry"),
        Index("ix_bess_telemetry_ts", "ts"),
    )


class SiteLoad(Base):
    """Industrial site load and onsite generation."""

    __tablename__ = "site_load"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    load_kw: Mapped[float] = mapped_column(Float, nullable=False)
    pv_kw: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("ts", name="pk_site_load"),
        Index("ix_site_load_ts", "ts"),
    )


class DamPrice(Base):
    """Day-Ahead Market hourly clearing prices."""

    __tablename__ = "dam_prices"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    zone: Mapped[str] = mapped_column(String(32), default="OES", nullable=False)
    price_uah_mwh: Mapped[float] = mapped_column(Float, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("ts", "zone", name="pk_dam_prices"),
        Index("ix_dam_prices_ts", "ts"),
    )


class Forecast(Base):
    """Generated ML/DL forecasts."""

    __tablename__ = "forecasts"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target: Mapped[str] = mapped_column(String(32), nullable=False)  # 'price' | 'load'
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at_sim: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_h: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    p10: Mapped[float | None] = mapped_column(Float, nullable=True)
    p90: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint(
            "ts", "target", "model_name", "model_version", "created_at_sim", name="pk_forecasts"
        ),
        Index("ix_forecasts_ts", "ts"),
        Index("ix_forecasts_target", "target"),
    )


class Schedule(Base):
    """MILP optimization schedules."""

    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at_sim: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    strategy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    horizon_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_profit_uah: Mapped[float | None] = mapped_column(Float, nullable=True)
    solver_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    solve_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


class DispatchLog(Base):
    """Realtime dispatcher actions and explainability log."""

    __tablename__ = "dispatch_log"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    setpoint_kw: Mapped[float] = mapped_column(Float, nullable=False)
    actual_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    schedule_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("ts", name="pk_dispatch_log"),
        Index("ix_dispatch_log_ts", "ts"),
    )


class Financial(Base):
    """Hourly financial results and settlement."""

    __tablename__ = "financials"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    import_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    export_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    price_buy: Mapped[float] = mapped_column(Float, nullable=False)
    price_sell: Mapped[float] = mapped_column(Float, nullable=False)
    cost_baseline_uah: Mapped[float] = mapped_column(Float, nullable=False)
    cost_actual_uah: Mapped[float] = mapped_column(Float, nullable=False)
    revenue_uah: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    degradation_uah: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    net_uah: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("ts", name="pk_financials"),
        Index("ix_financials_ts", "ts"),
    )


class Setting(Base):
    """System configuration parameters."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MlModel(Base):
    """Machine learning model registry."""

    __tablename__ = "ml_models"

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(String(32), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(256), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (PrimaryKeyConstraint("name", "version", name="pk_ml_models"),)
