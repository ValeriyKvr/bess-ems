"""Stage 3 tests: TOU_SIMPLE strategy, Dispatcher, SAFE_MODE (SPEC §6.5, §6.7)."""

from datetime import UTC, datetime, timedelta

from ems.dispatch.dispatcher import (
    DISPATCHING,
    NO_SCHEDULE,
    SAFE_MODE,
    Dispatcher,
    DispatcherConfig,
)
from ems.optimization.strategies import (
    Schedule,
    ScheduleContext,
    ScheduleItem,
    TouSimpleStrategy,
)

# ──────────────────────────────── TOU_SIMPLE Strategy ────────────────────────────────


class TestTouSimpleStrategy:
    """Tests for TOU_SIMPLE schedule building."""

    def _make_prices(self, base_date: datetime, hourly_prices: list[float]) -> list[dict]:
        """Build a price list from hourly price values."""
        prices = []
        for i, price in enumerate(hourly_prices):
            ts = base_date + timedelta(hours=i)
            prices.append(
                {
                    "ts": ts,
                    "price_dam": price,
                    "price_buy": price + 1928.57,  # transmission + distribution + supplier
                    "price_sell": price * 0.9,
                }
            )
        return prices

    def test_selects_cheapest_hours_for_charge(self) -> None:
        """TOU_SIMPLE should select the N cheapest hours for charging."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        # 24 hourly prices: cheap at night (hours 0-5), expensive at peak (hours 17-21)
        hourly = [
            2000,
            2100,
            1800,
            1900,
            2200,
            2500,  # 0-5: nighttime (cheap)
            3500,
            4000,
            4200,
            4500,
            4800,
            5000,  # 6-11: morning ramp
            5200,
            5500,
            5800,
            6000,
            6500,
            7000,  # 12-17: afternoon
            7500,
            7200,
            6800,
            6200,
            5000,
            3000,  # 18-23: evening peak + decline
        ]
        prices = self._make_prices(base, hourly)

        strategy = TouSimpleStrategy(n_charge_hours=4, n_discharge_hours=4)
        context = ScheduleContext(
            current_time=base,
            horizon_start=base,
            horizon_end=base + timedelta(hours=23),
            soc_pct=50.0,
            capacity_kwh=2000.0,
            max_charge_kw=500.0,
            max_discharge_kw=500.0,
            soc_min_pct=10.0,
            soc_max_pct=90.0,
            prices=prices,
        )

        schedule = strategy.build_schedule(context)
        assert schedule.strategy == "TOU_SIMPLE"
        assert schedule.solver_status == "OPTIMAL"
        assert len(schedule.items) == 24

        # The 4 cheapest hours should have positive setpoint (charge)
        charge_items = [item for item in schedule.items if item.setpoint_kw > 0]
        assert len(charge_items) >= 1  # At least some charging

        # The 4 most expensive hours should have negative setpoint (discharge)
        discharge_items = [item for item in schedule.items if item.setpoint_kw < 0]
        assert len(discharge_items) >= 1  # At least some discharging

        # Charge hours should be among the cheapest
        charge_hours = {item.ts.hour for item in charge_items}
        # Hours 2, 3, 0, 1 are cheapest (1800, 1900, 2000, 2100)
        assert charge_hours.intersection({0, 1, 2, 3}), (
            f"Expected some charge hours among cheapest, got {charge_hours}"
        )

        # Discharge hours should be among the most expensive
        discharge_hours = {item.ts.hour for item in discharge_items}
        # Hours 18, 17, 16, 19 are most expensive (7500, 7000, 6500, 7200)
        assert discharge_hours.intersection({16, 17, 18, 19}), (
            f"Expected some discharge hours among most expensive, got {discharge_hours}"
        )

    def test_empty_prices_returns_no_data(self) -> None:
        """TOU_SIMPLE with no price data should return NO_DATA status."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        strategy = TouSimpleStrategy()
        context = ScheduleContext(
            current_time=base,
            horizon_start=base,
            horizon_end=base + timedelta(hours=23),
            prices=[],
        )
        schedule = strategy.build_schedule(context)
        assert schedule.solver_status == "NO_DATA"
        assert len(schedule.items) == 0

    def test_schedule_respects_sign_convention(self) -> None:
        """Charge setpoints must be > 0, discharge < 0 (SPEC §4.3)."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        hourly = [2000 + i * 200 for i in range(24)]
        prices = self._make_prices(base, hourly)

        strategy = TouSimpleStrategy(n_charge_hours=4, n_discharge_hours=4)
        context = ScheduleContext(
            current_time=base,
            horizon_start=base,
            horizon_end=base + timedelta(hours=23),
            soc_pct=50.0,
            prices=prices,
        )
        schedule = strategy.build_schedule(context)

        for item in schedule.items:
            if item.reason.startswith("TOU charge"):
                assert item.setpoint_kw >= 0, f"Charge item has negative setpoint: {item}"
            if item.reason.startswith("TOU discharge"):
                assert item.setpoint_kw <= 0, f"Discharge item has positive setpoint: {item}"

    def test_expected_profit_calculated(self) -> None:
        """TOU_SIMPLE should compute expected profit estimate."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        hourly = [2000 + i * 200 for i in range(24)]
        prices = self._make_prices(base, hourly)

        strategy = TouSimpleStrategy(n_charge_hours=4, n_discharge_hours=4)
        context = ScheduleContext(
            current_time=base,
            horizon_start=base,
            horizon_end=base + timedelta(hours=23),
            soc_pct=50.0,
            prices=prices,
        )
        schedule = strategy.build_schedule(context)
        assert schedule.expected_profit_uah is not None


# ──────────────────────────────── Dispatcher ────────────────────────────────


class TestDispatcher:
    """Tests for the realtime Dispatcher (SPEC §6.5)."""

    def _make_dispatcher(self, **kwargs) -> Dispatcher:
        config = DispatcherConfig(**kwargs)
        return Dispatcher(config)

    def _make_schedule(self, base: datetime) -> Schedule:
        """Create a simple test schedule with 24 hourly items."""
        items = []
        for h in range(24):
            ts = base.replace(hour=h, minute=0, second=0)
            if h < 6:  # Night: charge
                items.append(ScheduleItem(ts=ts, setpoint_kw=400.0, reason="charge"))
            elif 17 <= h < 21:  # Peak: discharge
                items.append(ScheduleItem(ts=ts, setpoint_kw=-400.0, reason="discharge"))
            else:
                items.append(ScheduleItem(ts=ts, setpoint_kw=0.0, reason="idle"))

        return Schedule(
            strategy="TOU_SIMPLE",
            created_at_sim=base,
            horizon_start=base.replace(hour=0),
            horizon_end=base.replace(hour=23),
            items=items,
        )

    def test_dispatcher_follows_schedule(self) -> None:
        """Dispatcher should output setpoint from active schedule."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        dispatcher = self._make_dispatcher()
        schedule = self._make_schedule(base)

        dispatcher.set_schedule(schedule)

        # Tick at hour 2 (charge period) — telemetry must be fresh
        tick_time_2 = base.replace(hour=2, minute=30)
        dispatcher.update_telemetry(tick_time_2, soc_pct=50.0, state="CHARGING", power_kw=400.0)
        decision = dispatcher.tick(tick_time_2)
        assert decision.setpoint_kw == 400.0
        assert decision.state == DISPATCHING

        # Tick at hour 18 (discharge period)
        tick_time_18 = base.replace(hour=18, minute=15)
        dispatcher.update_telemetry(
            tick_time_18, soc_pct=50.0, state="DISCHARGING", power_kw=-400.0
        )
        decision = dispatcher.tick(tick_time_18)
        assert decision.setpoint_kw == -400.0

    def test_rule_a_forbids_discharge_at_soc_min(self) -> None:
        """Rule (a): SoC ≤ soc_min → discharge forbidden (setpoint ≥ 0)."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        dispatcher = self._make_dispatcher(soc_min_pct=10.0)
        schedule = self._make_schedule(base)
        dispatcher.set_schedule(schedule)

        # Set SoC at minimum — telemetry at tick time
        tick_time = base.replace(hour=18, minute=0)
        dispatcher.update_telemetry(tick_time, soc_pct=10.0, state="DISCHARGING", power_kw=-400.0)

        # Tick at discharge hour — should be overridden to 0
        decision = dispatcher.tick(tick_time)
        assert decision.setpoint_kw >= 0, (
            f"Discharge should be forbidden at SoC min, got {decision.setpoint_kw}"
        )
        assert decision.override is True
        assert "rule_a" in decision.reason

    def test_rule_a_below_soc_min(self) -> None:
        """Rule (a): SoC below soc_min → discharge definitely forbidden."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        dispatcher = self._make_dispatcher(soc_min_pct=10.0)
        schedule = self._make_schedule(base)
        dispatcher.set_schedule(schedule)

        dispatcher.update_telemetry(base, soc_pct=5.0, state="DISCHARGING", power_kw=-400.0)

        decision = dispatcher.tick(base.replace(hour=19, minute=0))
        assert decision.setpoint_kw >= 0
        assert decision.override is True

    def test_safe_mode_on_fault(self) -> None:
        """Rule (c): BESS in FAULT → SAFE_MODE, setpoint = 0."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        dispatcher = self._make_dispatcher()
        schedule = self._make_schedule(base)
        dispatcher.set_schedule(schedule)

        # BESS in FAULT state
        dispatcher.update_telemetry(base, soc_pct=50.0, state="FAULT", power_kw=0.0)

        decision = dispatcher.tick(base.replace(hour=2, minute=0))
        assert decision.setpoint_kw == 0.0
        assert decision.state == SAFE_MODE
        assert "FAULT" in decision.reason
        assert decision.override is True

    def test_safe_mode_on_telemetry_timeout(self) -> None:
        """Rule (c): No telemetry > 3 sim-min → SAFE_MODE."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        dispatcher = self._make_dispatcher(telemetry_timeout_sim_minutes=3.0)
        schedule = self._make_schedule(base)
        dispatcher.set_schedule(schedule)

        # Set telemetry at t=0
        dispatcher.update_telemetry(base, soc_pct=50.0, state="CHARGING", power_kw=400.0)

        # Tick at t=1 min — OK
        decision = dispatcher.tick(base + timedelta(minutes=1))
        assert decision.state == DISPATCHING

        # Tick at t=4 min (> 3 min since last telemetry) — SAFE_MODE
        decision = dispatcher.tick(base + timedelta(minutes=4))
        assert decision.state == SAFE_MODE
        assert decision.setpoint_kw == 0.0
        assert "rule_c" in decision.reason

    def test_safe_mode_exit_on_telemetry_restore(self) -> None:
        """Dispatcher should exit SAFE_MODE when telemetry is restored."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        dispatcher = self._make_dispatcher(telemetry_timeout_sim_minutes=3.0)
        schedule = self._make_schedule(base)
        dispatcher.set_schedule(schedule)

        # Telemetry at t=0
        dispatcher.update_telemetry(base, soc_pct=50.0, state="CHARGING", power_kw=400.0)

        # Trigger SAFE_MODE at t=4 min
        decision = dispatcher.tick(base + timedelta(minutes=4))
        assert decision.state == SAFE_MODE

        # Restore telemetry
        restored_time = base + timedelta(minutes=5)
        dispatcher.update_telemetry(restored_time, soc_pct=51.0, state="CHARGING", power_kw=400.0)

        # Next tick should exit SAFE_MODE
        decision = dispatcher.tick(restored_time + timedelta(minutes=1))
        assert decision.state != SAFE_MODE

    def test_safe_mode_event_logged(self) -> None:
        """Entering SAFE_MODE should create an alarm event."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        dispatcher = self._make_dispatcher()
        schedule = self._make_schedule(base)
        dispatcher.set_schedule(schedule)

        # Trigger FAULT
        dispatcher.update_telemetry(base, soc_pct=50.0, state="FAULT", power_kw=0.0)
        dispatcher.tick(base + timedelta(minutes=1))

        events = dispatcher.event_log
        assert len(events) >= 1
        assert events[0]["event"] == "SAFE_MODE_ENTER"
        assert events[0]["severity"] == "ALARM"

    def test_no_schedule_state(self) -> None:
        """Without a schedule, dispatcher should be in NO_SCHEDULE state."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        dispatcher = self._make_dispatcher()
        dispatcher.update_telemetry(base, soc_pct=50.0, state="STANDBY", power_kw=0.0)

        decision = dispatcher.tick(base)
        assert decision.state == NO_SCHEDULE
        assert decision.setpoint_kw == 0.0

    def test_peak_shaving_rule_b(self) -> None:
        """Rule (b): When load exceeds peak_limit, dispatcher increases discharge."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        dispatcher = self._make_dispatcher(peak_limit_kw=800.0)
        schedule = self._make_schedule(base)
        dispatcher.set_schedule(schedule)

        tick_time = base.replace(hour=10, minute=0)
        dispatcher.update_telemetry(tick_time, soc_pct=50.0, state="IDLE", power_kw=0.0)
        dispatcher.update_site_load(1000.0)  # 200 kW over limit

        # Tick at an idle hour — should get peak-shaving discharge
        decision = dispatcher.tick(tick_time)
        assert decision.setpoint_kw < 0, "Should trigger discharge for peak-shaving"
        assert decision.override is True
        assert "rule_b" in decision.reason

    def test_decision_log_populated(self) -> None:
        """Every tick should add a decision to the log."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        dispatcher = self._make_dispatcher()
        dispatcher.update_telemetry(base, soc_pct=50.0, state="STANDBY", power_kw=0.0)

        for i in range(5):
            dispatcher.tick(base + timedelta(minutes=i))

        assert len(dispatcher.decision_log) == 5


# ──────────────────────────────── Schedule Model ────────────────────────────────


class TestScheduleModel:
    """Tests for Schedule data structure."""

    def test_get_setpoint_for_within_horizon(self) -> None:
        """get_setpoint_for should match the correct hourly slot."""
        base = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)
        schedule = Schedule(
            items=[
                ScheduleItem(ts=base, setpoint_kw=300.0),
                ScheduleItem(ts=base + timedelta(hours=1), setpoint_kw=-200.0),
            ]
        )
        assert schedule.get_setpoint_for(base + timedelta(minutes=30)) == 300.0
        assert schedule.get_setpoint_for(base + timedelta(hours=1, minutes=15)) == -200.0

    def test_get_setpoint_for_outside_horizon(self) -> None:
        """get_setpoint_for should return None outside all schedule slots."""
        base = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)
        schedule = Schedule(items=[ScheduleItem(ts=base, setpoint_kw=300.0)])
        assert schedule.get_setpoint_for(base + timedelta(hours=5)) is None

    def test_to_db_dict(self) -> None:
        """Schedule serialization for DB persistence."""
        base = datetime(2026, 3, 15, 0, 0, 0, tzinfo=UTC)
        schedule = Schedule(
            strategy="TOU_SIMPLE",
            created_at_sim=base,
            horizon_start=base,
            horizon_end=base + timedelta(hours=23),
            items=[ScheduleItem(ts=base, setpoint_kw=500.0, reason="charge")],
        )
        db_dict = schedule.to_db_dict()
        assert db_dict["strategy"]["name"] == "TOU_SIMPLE"
        assert db_dict["strategy"]["capacity_kwh"] == 1000.0
        assert len(db_dict["items"]) == 1
        assert db_dict["items"][0]["setpoint_kw"] == 500.0
