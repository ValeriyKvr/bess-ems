"""Unit tests for BESS configuration."""

from bess_sim.config import BessConfig


def test_bess_default_config() -> None:
    """Verify default parameters match SPEC §5.1 requirements."""
    config = BessConfig()
    assert config.capacity_kwh == 1000.0
    assert config.power_max_kw == 500.0
    assert config.soc_min_pct == 10.0
    assert config.soc_max_pct == 90.0
    assert config.soc_hard_min_pct == 5.0
    assert config.soc_hard_max_pct == 97.0
    assert config.eff_charge == 0.95
    assert config.eff_discharge == 0.95
    assert config.bess_id == "bess-01"
