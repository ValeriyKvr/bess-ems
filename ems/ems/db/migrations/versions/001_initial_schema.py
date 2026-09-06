"""Initial schema and TimescaleDB hypertables.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-09-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Attempt to enable TimescaleDB extension if supported
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

    # 1. bess_telemetry
    op.create_table(
        "bess_telemetry",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bess_id", sa.String(length=64), nullable=False),
        sa.Column("soc_pct", sa.Float(), nullable=True),
        sa.Column("soh_pct", sa.Float(), nullable=True),
        sa.Column("soe_kwh", sa.Float(), nullable=True),
        sa.Column("power_kw", sa.Float(), nullable=True),
        sa.Column("voltage_v", sa.Float(), nullable=True),
        sa.Column("current_a", sa.Float(), nullable=True),
        sa.Column("temp_c", sa.Float(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=True),
        sa.Column("alarms", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("ts", "bess_id", name="pk_bess_telemetry"),
    )
    op.create_index("ix_bess_telemetry_ts", "bess_telemetry", ["ts"])

    # 2. site_load
    op.create_table(
        "site_load",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("load_kw", sa.Float(), nullable=False),
        sa.Column("pv_kw", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("ts", name="pk_site_load"),
    )
    op.create_index("ix_site_load_ts", "site_load", ["ts"])

    # 3. dam_prices
    op.create_table(
        "dam_prices",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("zone", sa.String(length=32), server_default="OES", nullable=False),
        sa.Column("price_uah_mwh", sa.Float(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("ts", "zone", name="pk_dam_prices"),
    )
    op.create_index("ix_dam_prices_ts", "dam_prices", ["ts"])

    # 4. forecasts
    op.create_table(
        "forecasts",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("created_at_sim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_h", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("p10", sa.Float(), nullable=True),
        sa.Column("p90", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint(
            "ts", "target", "model_name", "model_version", "created_at_sim", name="pk_forecasts"
        ),
    )
    op.create_index("ix_forecasts_ts", "forecasts", ["ts"])
    op.create_index("ix_forecasts_target", "forecasts", ["target"])

    # 5. schedules
    op.create_table(
        "schedules",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at_sim", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy", sa.JSON(), nullable=False),
        sa.Column("horizon_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_profit_uah", sa.Float(), nullable=True),
        sa.Column("solver_status", sa.String(length=32), nullable=True),
        sa.Column("solve_time_ms", sa.Integer(), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # 6. dispatch_log
    op.create_table(
        "dispatch_log",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("setpoint_kw", sa.Float(), nullable=False),
        sa.Column("actual_kw", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("schedule_id", sa.String(length=64), nullable=True),
        sa.Column("override", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("ts", name="pk_dispatch_log"),
    )
    op.create_index("ix_dispatch_log_ts", "dispatch_log", ["ts"])

    # 7. financials
    op.create_table(
        "financials",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("import_kwh", sa.Float(), nullable=False),
        sa.Column("export_kwh", sa.Float(), nullable=False),
        sa.Column("price_buy", sa.Float(), nullable=False),
        sa.Column("price_sell", sa.Float(), nullable=False),
        sa.Column("cost_baseline_uah", sa.Float(), nullable=False),
        sa.Column("cost_actual_uah", sa.Float(), nullable=False),
        sa.Column("revenue_uah", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("degradation_uah", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("net_uah", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("ts", name="pk_financials"),
    )
    op.create_index("ix_financials_ts", "financials", ["ts"])

    # 8. settings
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    # 9. ml_models
    op.create_table(
        "ml_models",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("artifact_path", sa.String(length=256), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("name", "version", name="pk_ml_models"),
    )

    # Convert time-series tables to TimescaleDB hypertables if on postgresql
    if bind.dialect.name == "postgresql":
        hypertables = [
            "bess_telemetry",
            "site_load",
            "dam_prices",
            "forecasts",
            "dispatch_log",
            "financials",
        ]
        for ht in hypertables:
            op.execute(f"SELECT create_hypertable('{ht}', 'ts', if_not_exists => TRUE);")


def downgrade() -> None:
    op.drop_table("ml_models")
    op.drop_table("settings")
    op.drop_table("financials")
    op.drop_table("dispatch_log")
    op.drop_table("schedules")
    op.drop_table("forecasts")
    op.drop_table("dam_prices")
    op.drop_table("site_load")
    op.drop_table("bess_telemetry")
