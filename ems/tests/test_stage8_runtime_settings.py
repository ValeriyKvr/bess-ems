"""Tests for runtime propagation of settings and realistic settlement (SPEC §6.5, §7, §11).

Covers the defects that made the settings page write-only: saved parameters had to
reach the dispatcher, the market tariffs, the active strategy and the BESS
simulator, and the hourly settlement had to integrate energy instead of sampling
instantaneous power.
"""

from datetime import UTC, datetime, timedelta

import pytest

import ems.main as ems_main
from ems.api.settings import (
    BatterySettings,
    EmsCoreSettings,
    StrategySettings,
    apply_settings_to_runtime,
    battery_config_payload,
    get_settings_section,
)
from ems.dispatch.dispatcher import Dispatcher, DispatcherConfig
from ems.market.financials import compute_hourly_financials
from ems.market.simulator import MarketSimulator, MarketTariffs
from ems.optimization.strategies import Schedule, ScheduleItem


class FakeMqtt:
    """Minimal stand-in recording published configuration."""

    def __init__(self) -> None:
        self.is_connected = True
        self.published: list[tuple[str, dict]] = []
        self.latest_bess_telemetry: dict[str, dict] = {}

    def publish_config(self, bess_id: str, payload: dict) -> None:
        self.published.append((bess_id, payload))


@pytest.fixture()
def runtime():
    """Give app_state a clean dispatcher/market/mqtt trio and restore it afterwards."""
    state = ems_main.app_state
    saved = (state.dispatcher, state.market, state.mqtt, state._strategy_name)
    state.dispatcher = Dispatcher(DispatcherConfig())
    state.market = MarketSimulator()
    state.mqtt = FakeMqtt()
    try:
        yield state
    finally:
        state.dispatcher, state.market, state.mqtt, state._strategy_name = saved


# ─────────────────────────── settings → runtime ────────────────────────────


async def test_battery_settings_reach_dispatcher_and_simulator(runtime) -> None:
    """Saving the battery section retunes the dispatcher and pushes config over MQTT."""
    battery = BatterySettings(capacity_kwh=2000.0, power_max_kw=800.0, soc_min_pct=15.0)

    applied = await apply_settings_to_runtime("battery", battery)

    assert "dispatcher_soc_limits" in applied
    assert "bess_config_published" in applied
    assert runtime.dispatcher.config.soc_min_pct == 15.0
    assert runtime.deg_cost_uah_per_kwh == pytest.approx(battery.degradation_cost_uah_per_kwh())

    _, payload = runtime.mqtt.published[-1]
    assert payload["capacity_kwh"] == 2000.0
    assert payload["power_max_kw"] == 800.0


async def test_strategy_settings_change_active_strategy(runtime) -> None:
    """active_strategy is no longer hard-coded to ARBITRAGE."""
    applied = await apply_settings_to_runtime(
        "strategy", StrategySettings(active_strategy="PEAK_SHAVING", peak_limit_kw=650.0)
    )

    assert "active_strategy" in applied
    assert runtime._strategy_name == "PEAK_SHAVING"
    assert runtime.dispatcher.config.peak_limit_kw == 650.0


async def test_market_and_ems_sections_reach_runtime(runtime) -> None:
    """Tariffs and the SoC tolerance are live-applied."""
    await apply_settings_to_runtime(
        "market", MarketTariffs(distribution_tariff_uah_mwh=1900.0, export_allowed=False)
    )
    await apply_settings_to_runtime("ems", EmsCoreSettings(soc_tolerance_pct=7.5))

    assert runtime.market.tariffs.distribution_tariff_uah_mwh == 1900.0
    assert runtime.market.tariffs.export_allowed is False
    assert runtime.dispatcher.config.soc_tolerance_pct == 7.5


def test_battery_config_payload_only_exports_simulator_fields() -> None:
    """The MQTT config payload carries physical parameters the simulator understands."""
    payload = battery_config_payload(BatterySettings())
    assert "capacity_kwh" in payload and "thermal_loss_frac_rated" in payload
    assert "capex_uah" in payload
    # UI-only concepts must not leak into the physics config
    assert "soc_tolerance_pct" not in payload


def test_degradation_cost_is_derived_from_capex_and_cycle_life() -> None:
    """c_deg = capex / (2 · cycle_life · usable capacity), not a magic constant."""
    battery = BatterySettings(
        capacity_kwh=1000.0,
        soc_min_pct=10.0,
        soc_max_pct=90.0,
        cycle_life=6000.0,
        capex_uah=15_000_000.0,
    )
    # usable = 800 kWh ⇒ lifetime throughput = 2 · 6000 · 800 = 9.6 GWh
    assert battery.degradation_cost_uah_per_kwh() == pytest.approx(15_000_000.0 / 9_600_000.0)


def test_bess_auxiliaries_are_charged_to_the_actual_case() -> None:
    """Aux consumption exists only because of the BESS, so it must reduce net benefit."""
    common = dict(
        ts=datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC),
        load_kwh=400.0,
        pv_kwh=100.0,
        charge_kwh=0.0,
        discharge_kwh=0.0,
        price_buy_uah_mwh=6000.0,
        price_sell_uah_mwh=4000.0,
    )
    without_aux = compute_hourly_financials(**common)
    with_aux = compute_hourly_financials(**common, aux_kwh=5.0)

    # Baseline is the site without a battery — unchanged by the BESS auxiliaries
    assert with_aux.cost_baseline_uah == without_aux.cost_baseline_uah
    assert with_aux.import_kwh == pytest.approx(without_aux.import_kwh + 5.0)
    assert with_aux.net_uah < without_aux.net_uah


# ────────────────────── settings endpoint robustness ───────────────────────


class BrokenSession:
    """Session whose every query fails, mimicking an unreachable database."""

    async def execute(self, *args, **kwargs):
        raise ConnectionError("connection was closed in the middle of operation")


async def test_settings_get_falls_back_to_defaults_when_db_is_down() -> None:
    """The settings form must still render when the database is unreachable."""
    values = await get_settings_section("battery", db=BrokenSession())
    assert values["capacity_kwh"] == BatterySettings().capacity_kwh
    assert values["power_max_kw"] == BatterySettings().power_max_kw


# ───────────────────────── hourly energy settlement ─────────────────────────


def test_hour_accumulator_integrates_power_over_the_hour(runtime) -> None:
    """Energy is integrated tick by tick and rolled over at the hour boundary."""
    runtime._hour_acc = ems_main._new_hour_accumulator()
    runtime._prev_hour_acc = None
    runtime._acc_hour = None
    runtime.mqtt.latest_bess_telemetry = {
        runtime.settings.bess_id: {"power_kw": -300.0, "aux_kw": 4.0}
    }

    base = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    for i in range(4):  # four 15-minute ticks = one full hour
        ems_main._accumulate_hour_energy(
            base + timedelta(minutes=15 * i), 900.0, price_dam=5000.0, load_kw=400.0, pv_kw=100.0
        )

    acc = runtime._hour_acc
    assert acc["hours"] == pytest.approx(1.0)
    assert acc["discharge_kwh"] == pytest.approx(300.0)
    assert acc["charge_kwh"] == 0.0
    assert acc["load_kwh"] == pytest.approx(400.0)
    assert acc["aux_kwh"] == pytest.approx(4.0)
    assert acc["price_dam_weighted"] / acc["hours"] == pytest.approx(5000.0)

    # Crossing into the next hour freezes the completed hour for settlement
    ems_main._accumulate_hour_energy(
        base + timedelta(hours=1), 900.0, price_dam=5000.0, load_kw=400.0, pv_kw=100.0
    )
    assert runtime._prev_hour_acc is not None
    assert runtime._prev_hour_acc["discharge_kwh"] == pytest.approx(300.0)
    assert runtime._hour_acc["hours"] == pytest.approx(0.25)


# ─────────────────────── closed-loop SoC tracking ───────────────────────────


def test_planned_soc_follows_the_schedule(runtime) -> None:
    """The planned SoC trajectory is integrated from the active schedule."""
    base = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    schedule = Schedule(
        strategy="TOU_SIMPLE",
        capacity_kwh=1000.0,
        horizon_start=base,
        horizon_end=base + timedelta(hours=4),
        items=[
            ScheduleItem(ts=base, setpoint_kw=200.0),
            ScheduleItem(ts=base + timedelta(hours=1), setpoint_kw=200.0),
            ScheduleItem(ts=base + timedelta(hours=2), setpoint_kw=-100.0),
        ],
    )
    schedule.params["start_soc_pct"] = 50.0
    runtime.dispatcher.set_schedule(schedule)

    # After two charging hours at 200 kW: 500 + 400 = 900 kWh ⇒ 90%
    assert ems_main._planned_soc_pct(base + timedelta(hours=2)) == pytest.approx(90.0)
    # Half way through the discharging hour: 900 − 50 = 850 kWh ⇒ 85%
    assert ems_main._planned_soc_pct(base + timedelta(hours=2, minutes=30)) == pytest.approx(85.0)


def test_planned_soc_returns_none_without_anchor(runtime) -> None:
    """No anchor SoC means no trajectory — the caller must skip the deviation check."""
    base = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
    schedule = Schedule(
        strategy="TOU_SIMPLE",
        capacity_kwh=1000.0,
        horizon_start=base,
        horizon_end=base + timedelta(hours=1),
        items=[ScheduleItem(ts=base, setpoint_kw=100.0)],
    )
    runtime.dispatcher.set_schedule(schedule)
    assert ems_main._planned_soc_pct(base) is None


# ───────────────────────── market/site continuity ───────────────────────────


def test_site_profile_is_continuous_across_the_hour() -> None:
    """Load and PV are interpolated between hourly samples, price is a step function."""
    ems_main.app_state._price_cache.clear()
    ems_main.app_state._load_cache.clear()

    base = datetime(2026, 6, 15, 9, 0, 0, tzinfo=UTC)
    p0, load0, _ = ems_main._get_current_market_and_site(base)
    p_mid, load_mid, _ = ems_main._get_current_market_and_site(base + timedelta(minutes=30))
    _, load1, _ = ems_main._get_current_market_and_site(base + timedelta(minutes=59, seconds=59))

    assert p_mid == p0  # DAM price is constant within a settlement hour
    # The half-hour sample lies between the two hourly endpoints
    assert min(load0, load1) - 1e-6 <= load_mid <= max(load0, load1) + 1e-6
    assert abs(load_mid - load0) > 0.0
