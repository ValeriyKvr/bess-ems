"""Health and initialization tests for BESS simulator."""

from bess_sim.battery import Battery
from bess_sim.bms import BessOperationalState, BmsManager
from bess_sim.config import BessConfig
from bess_sim.degradation import DegradationModel
from bess_sim.pcs import PcsModel
from bess_sim.thermal import ThermalModel


def test_components_initialization() -> None:
    """Verify BESS subcomponents initialize with valid state."""
    config = BessConfig()
    battery = Battery(config=config.battery)
    bms = BmsManager()
    pcs = PcsModel(config.power_max_kw, config.ramp_rate_kw_s)
    thermal = ThermalModel(config.temp_ambient_c)
    deg = DegradationModel(config.capacity_kwh, config.cycle_life)

    assert battery.soc_pct == 50.0
    assert bms.state == BessOperationalState.STANDBY
    assert pcs.actual_power_kw == 0.0
    assert thermal.temp_c == 25.0
    assert deg.soh_pct == 100.0
