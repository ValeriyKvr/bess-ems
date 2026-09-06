"""Application settings for EMS Core."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmsSettings(BaseSettings):
    """EMS configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ems",
        alias="DATABASE_URL",
    )

    # MQTT
    mqtt_broker_host: str = Field(default="localhost", alias="MQTT_BROKER_HOST")
    mqtt_broker_port: int = Field(default=1883, alias="MQTT_BROKER_PORT")
    mqtt_keepalive: int = Field(default=60, alias="MQTT_KEEPALIVE")
    bess_id: str = Field(default="bess-01", alias="BESS_ID")

    # HTTP & App
    ems_host: str = Field(default="0.0.0.0", alias="EMS_HOST")
    ems_port: int = Field(default=8000, alias="EMS_PORT")
    ems_api_prefix: str = Field(default="/api", alias="EMS_API_PREFIX")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:80", "http://localhost"],
        alias="CORS_ORIGINS",
    )

    # Simulation Clock (SPEC §4.2, §6.6)
    sim_speed: int = Field(default=60, alias="SIM_SPEED")
    sim_start_time: str = Field(default="2026-03-01T00:00:00Z", alias="SIM_START_TIME")
    sim_tick_seconds: int = Field(default=60, alias="SIM_TICK_SECONDS")

    # ML & Forecasting (SPEC §6.3, §8)
    forecast_error_threshold: float = Field(default=25.0, alias="FORECAST_ERROR_THRESHOLD")
