"""Configuration and physical parameters for BESS Simulator (SPEC §5.1).

Physical parameters are expressed in *scale-invariant* terms wherever possible
(loss fraction at rated power, design temperature rise, thermal mass per kWh)
and the absolute coefficients (r_internal, k_cooling, c_thermal, r_pack_ohm)
are derived from them at construction time. That way changing capacity_kwh or
power_max_kw from the UI keeps the thermal and electrical behaviour physically
consistent instead of silently tripping overheat protection.
"""

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 10-point Open Circuit Voltage (OCV) curve for Lithium Iron Phosphate (LFP) pack (nominal ~780V)
DEFAULT_LFP_OCV_TABLE: list[tuple[float, float]] = [
    (0.0, 672.0),  # Fully depleted (~2.80 V/cell)
    (5.0, 720.0),  # Cutoff threshold (~3.00 V/cell)
    (10.0, 744.0),  # Lower knee (~3.10 V/cell)
    (20.0, 768.0),  # Start of flat plateau (~3.20 V/cell)
    (40.0, 780.0),  # Flat plateau (~3.25 V/cell)
    (60.0, 785.0),  # Mid plateau (~3.27 V/cell)
    (80.0, 792.0),  # Upper plateau (~3.30 V/cell)
    (90.0, 804.0),  # Upper knee (~3.35 V/cell)
    (95.0, 828.0),  # High voltage curve (~3.45 V/cell)
    (100.0, 864.0),  # Full charge (~3.60 V/cell)
]

SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0


class BatteryConfig(BaseModel):
    """Electrochemical, electrical and thermal parameters for battery pack (SPEC §5.1)."""

    capacity_kwh: float = Field(
        default=1000.0, description="Nominal battery storage capacity in kWh"
    )
    power_max_kw: float = Field(
        default=500.0, description="Maximum continuous active power rating in kW"
    )
    soc_min_pct: float = Field(default=10.0, description="Operational lower SoC limit in %")
    soc_max_pct: float = Field(default=90.0, description="Operational upper SoC limit in %")
    soc_hard_min_pct: float = Field(
        default=5.0, description="Emergency low SoC trip limit -> FAULT in %"
    )
    soc_hard_max_pct: float = Field(
        default=97.0, description="Emergency high SoC trip limit -> FAULT in %"
    )
    soc_derate_charge_start_pct: float = Field(
        default=85.0, description="SoC where charge power derating starts"
    )
    soc_derate_discharge_start_pct: float = Field(
        default=15.0, description="SoC where discharge power derating starts"
    )

    eff_charge: float = Field(default=0.95, description="One-way charging efficiency (0.0 to 1.0)")
    eff_discharge: float = Field(
        default=0.95, description="One-way discharging efficiency (0.0 to 1.0)"
    )
    self_discharge_pct_day: float = Field(
        default=0.1, description="Calendar self-discharge rate in % per day"
    )
    aux_load_kw: float = Field(
        default=3.0, description="Continuous auxiliary system power (HVAC, BMS) in kW"
    )
    aux_from_ac: bool = Field(
        default=True,
        description=(
            "True: auxiliaries (HVAC/BMS/PCS idle) are fed from the AC bus through the "
            "auxiliary transformer — the realistic containerised BESS topology. "
            "False: auxiliaries drain the DC pack."
        ),
    )
    ramp_rate_kw_s: float = Field(default=50.0, description="Active power ramp limit in kW/s")

    temp_ambient_c: float = Field(default=25.0, description="Ambient temperature in °C")
    temp_max_c: float = Field(
        default=45.0, description="Maximum allowed cell temperature before FAULT in °C"
    )

    # ── Scale-invariant thermal / electrical design parameters ──────────────
    thermal_loss_frac_rated: float = Field(
        default=0.025,
        description="Ohmic pack loss at rated power, as a fraction of rated power (2.5% typical)",
    )
    cooling_design_delta_t_c: float = Field(
        default=10.0,
        description="Steady-state cell temperature rise above ambient at rated power, in K",
    )
    thermal_mass_kj_per_kwh: float = Field(
        default=5.0,
        description="Effective thermal mass of the pack, kJ/K per kWh of installed capacity",
    )
    v_nominal_v: float = Field(default=780.0, description="Nominal DC pack voltage in V")

    # Derived coefficients (auto-computed when left as None)
    r_internal: float | None = Field(
        default=None, description="Joule heating factor, kW per kW² (derived if None)"
    )
    k_cooling: float | None = Field(
        default=None, description="Heat dissipation coefficient in kW/K (derived if None)"
    )
    c_thermal: float | None = Field(
        default=None, description="Pack heat capacity in kJ/K (derived if None)"
    )
    r_pack_ohm: float | None = Field(
        default=None, description="DC pack ohmic resistance in Ω (derived if None)"
    )

    # ── Degradation ─────────────────────────────────────────────────────────
    cycle_life: float = Field(default=6000.0, description="Full equivalent cycles until 80% SoH")
    calendar_fade_pct_per_year: float = Field(
        default=1.5, description="Calendar capacity fade at reference temperature, % per year"
    )
    deg_temp_ref_c: float = Field(
        default=25.0, description="Reference temperature for calendar ageing in °C"
    )
    deg_temp_doubling_k: float = Field(
        default=10.0, description="Temperature rise in K that doubles the calendar fade rate"
    )
    capex_uah: float = Field(
        default=15000000.0, description="Capital expenditure in UAH for degradation accounting"
    )
    initial_soc_pct: float = Field(default=50.0, description="Starting State of Charge in %")
    ocv_table: list[tuple[float, float]] = Field(
        default=DEFAULT_LFP_OCV_TABLE, description="10-point OCV lookup curve"
    )
    seed: int = Field(default=42, description="Random seed for deterministic behavior")

    @model_validator(mode="after")
    def _derive_physical_coefficients(self) -> "BatteryConfig":
        """Derive absolute thermal/electrical coefficients from scale-invariant design inputs."""
        p_rated = max(1.0, self.power_max_kw)
        loss_at_rated_kw = self.thermal_loss_frac_rated * p_rated

        if self.r_internal is None:
            # heat_kw = P² · r_internal  ⇒  at rated power heat = loss_frac · P_rated
            self.r_internal = self.thermal_loss_frac_rated / p_rated
        if self.k_cooling is None:
            # Steady state: loss_at_rated = k · ΔT_design
            self.k_cooling = loss_at_rated_kw / max(0.5, self.cooling_design_delta_t_c)
        if self.c_thermal is None:
            self.c_thermal = self.thermal_mass_kj_per_kwh * max(1.0, self.capacity_kwh)
        if self.r_pack_ohm is None:
            # loss = I²·R with I = P_rated/V_nom  ⇒  R = loss · V_nom² / P_rated²
            v_nom = max(1.0, self.v_nominal_v)
            self.r_pack_ohm = (loss_at_rated_kw * 1000.0) * (v_nom**2) / ((p_rated * 1000.0) ** 2)
        return self

    def rederive(self) -> "BatteryConfig":
        """Return a copy with derived coefficients recomputed from current design inputs."""
        data = self.model_dump()
        for key in ("r_internal", "k_cooling", "c_thermal", "r_pack_ohm"):
            data[key] = None
        return BatteryConfig(**data)


class BessConfig(BaseSettings):
    """Runtime configuration for BESS Simulator process.

    Nested battery parameters can be overridden from the environment using the
    ``BATTERY__`` prefix, e.g. ``BATTERY__CAPACITY_KWH=2000``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    mqtt_broker_host: str = Field(default="localhost", alias="MQTT_BROKER_HOST")
    mqtt_broker_port: int = Field(default=1883, alias="MQTT_BROKER_PORT")
    mqtt_keepalive: int = Field(default=60, alias="MQTT_KEEPALIVE")
    bess_id: str = Field(default="bess-01", alias="BESS_ID")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    telemetry_interval_ms: int = Field(default=1000, alias="BESS_SIM_TELEMETRY_INTERVAL_MS")
    enable_modbus: bool = Field(default=True, alias="BESS_ENABLE_MODBUS")
    modbus_port: int = Field(default=5020, alias="BESS_MODBUS_PORT")

    # Embedded battery parameters
    battery: BatteryConfig = Field(default_factory=BatteryConfig)

    # Convenience proxies for top-level access
    @property
    def capacity_kwh(self) -> float:
        return self.battery.capacity_kwh

    @property
    def power_max_kw(self) -> float:
        return self.battery.power_max_kw

    @property
    def soc_min_pct(self) -> float:
        return self.battery.soc_min_pct

    @property
    def soc_max_pct(self) -> float:
        return self.battery.soc_max_pct

    @property
    def soc_hard_min_pct(self) -> float:
        return self.battery.soc_hard_min_pct

    @property
    def soc_hard_max_pct(self) -> float:
        return self.battery.soc_hard_max_pct

    @property
    def eff_charge(self) -> float:
        return self.battery.eff_charge

    @property
    def eff_discharge(self) -> float:
        return self.battery.eff_discharge

    @property
    def self_discharge_pct_day(self) -> float:
        return self.battery.self_discharge_pct_day

    @property
    def aux_load_kw(self) -> float:
        return self.battery.aux_load_kw

    @property
    def ramp_rate_kw_s(self) -> float:
        return self.battery.ramp_rate_kw_s

    @property
    def temp_ambient_c(self) -> float:
        return self.battery.temp_ambient_c

    @property
    def temp_max_c(self) -> float:
        return self.battery.temp_max_c

    @property
    def cycle_life(self) -> float:
        return self.battery.cycle_life

    @property
    def initial_soc_pct(self) -> float:
        return self.battery.initial_soc_pct
