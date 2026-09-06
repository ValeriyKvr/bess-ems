"""Tests for Stage 2: Generator profiles, Market calculations, Financials, and Clock."""

from datetime import UTC, datetime

import pytest

from ems.core.clock import SimulationClock
from ems.ingestion.generator import SyntheticDataGenerator
from ems.ingestion.importer import CsvDataImporter, CsvValidationError
from ems.market.financials import compute_hourly_financials
from ems.market.simulator import MarketTariffs, calculate_buy_price, calculate_sell_price


def test_generator_price_profile_shape() -> None:
    """Requirement: середня ціна 19–22 год > середньої 01–05 год."""
    gen = SyntheticDataGenerator(seed=42)
    start_dt = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    end_dt = datetime(2025, 1, 31, 23, 0, 0, tzinfo=UTC)

    df_prices = gen.generate_dam_prices(start_dt, end_dt)
    df_prices["hour"] = df_prices["ts"].dt.hour

    # Peak hours: 19, 20, 21, 22
    peak_prices = df_prices[df_prices["hour"].isin([19, 20, 21, 22])]["price_uah_mwh"]
    # Night hours: 1, 2, 3, 4, 5
    night_prices = df_prices[df_prices["hour"].isin([1, 2, 3, 4, 5])]["price_uah_mwh"]

    avg_peak = peak_prices.mean()
    avg_night = night_prices.mean()

    assert avg_peak > avg_night
    # Evening peak is typically > 1.8x higher than night in Ukrainian market
    assert avg_peak >= 1.5 * avg_night


def test_hourly_financials_baseline_cost() -> None:
    """Requirement: за годину з load 100 кВт, price_buy 5000 грн/МВт·год → cost 500 грн."""
    ts = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
    result = compute_hourly_financials(
        ts=ts,
        load_kwh=100.0,
        pv_kwh=0.0,
        charge_kwh=0.0,
        discharge_kwh=0.0,
        price_buy_uah_mwh=5000.0,
        price_sell_uah_mwh=3000.0,
    )

    assert result.cost_baseline_uah == pytest.approx(500.0, abs=0.01)
    assert result.cost_actual_uah == pytest.approx(500.0, abs=0.01)
    assert result.import_kwh == pytest.approx(100.0, abs=0.01)
    assert result.export_kwh == 0.0
    assert result.revenue_uah == 0.0
    assert result.net_uah == 0.0


def test_market_tariffs_buy_and_sell_prices() -> None:
    """Verify buy and sell price formulation according to SPEC §3.1."""
    tariffs = MarketTariffs(
        transmission_tariff_uah_mwh=500.0,
        distribution_tariff_uah_mwh=1200.0,
        supplier_margin_uah_mwh=100.0,
        export_price_coeff=0.9,
        export_allowed=True,
    )
    price_dam = 4000.0

    # Buy = DAM + 500 + 1200 + 100 = 5800 UAH/MWh
    p_buy = calculate_buy_price(price_dam, tariffs)
    assert p_buy == 5800.0

    # Sell = DAM * 0.9 = 3600 UAH/MWh
    p_sell = calculate_sell_price(price_dam, tariffs)
    assert p_sell == 3600.0


def test_csv_importer_dam_prices_and_resampling() -> None:
    """Test CSV importing and resampling to 15min and 1h."""
    csv_content = """date,hour,price_uah_mwh,zone
2026-03-01,1,3200.0,OES
2026-03-01,2,3100.0,OES
2026-03-01,3,3000.0,OES
"""
    importer = CsvDataImporter()
    df = importer.import_dam_prices(csv_content)
    assert len(df) == 3
    assert df.iloc[0]["price_uah_mwh"] == 3200.0

    # Resample to 15-min
    resampled_15m = importer.resample_series(df, target_step="15min", value_cols=["price_uah_mwh"])
    assert len(resampled_15m) > len(df)


def test_csv_importer_validation_error() -> None:
    """Test validation errors on malformed CSV."""
    invalid_csv = """date,price_uah_mwh
2026-03-01,3200.0
"""
    importer = CsvDataImporter()
    with pytest.raises(CsvValidationError):
        importer.import_dam_prices(invalid_csv)


def test_simulation_clock_transitions_and_13h_gate() -> None:
    """Test clock hour transition and 13:00 gate closure hooks."""
    clock = SimulationClock(start_time="2026-03-01T12:30:00Z", speed=60)

    hourly_calls = []
    gate_13h_calls = []

    clock.register_hourly_callback(lambda dt: hourly_calls.append(dt))
    clock.register_13h_callback(lambda dt: gate_13h_calls.append(dt))

    # Advance 40 minutes (from 12:30 to 13:10)
    clock.advance(2400.0)

    assert len(hourly_calls) == 1
    assert hourly_calls[0].hour == 13
    assert len(gate_13h_calls) == 1
