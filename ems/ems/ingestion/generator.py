"""Synthetic time series generator for prices, load, PV and weather (SPEC §3.3, §6.1)."""

import math
import random
from datetime import datetime, timedelta
from typing import Any

import pandas as pd


class SyntheticDataGenerator:
    """Deterministic synthetic data generator modeling Ukrainian electricity market profiles."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self._rng = random.Random(seed)

    def _hourly_price_profile(self, hour: int) -> float:
        """Daily hourly shape of Ukrainian Day-Ahead Market (UES profile §3.3).

        Night dip (00:00-06:00), morning peak (07:00-11:00), afternoon dip (12:00-16:00),
        and highest evening peak (17:00-23:00, especially 19:00-22:00).
        """
        shape = {
            0: 0.70,
            1: 0.65,
            2: 0.62,
            3: 0.60,
            4: 0.62,
            5: 0.68,
            6: 0.85,
            7: 1.10,
            8: 1.22,
            9: 1.25,
            10: 1.20,
            11: 1.12,
            12: 0.98,
            13: 0.92,
            14: 0.90,
            15: 0.95,
            16: 1.08,
            17: 1.30,
            18: 1.48,
            19: 1.65,
            20: 1.70,
            21: 1.62,
            22: 1.45,
            23: 1.05,
        }
        return shape.get(hour, 1.0)

    def _seasonality_factor(self, month: int) -> float:
        """Seasonal adjustment: winter highest (heating/scarcity), spring lowest."""
        # Jan=1 .. Dec=12
        factors = {
            1: 1.25,
            2: 1.22,
            3: 1.05,
            4: 0.92,
            5: 0.88,
            6: 0.95,
            7: 1.02,
            8: 1.05,
            9: 0.98,
            10: 1.04,
            11: 1.15,
            12: 1.28,
        }
        return factors.get(month, 1.0)

    def generate_dam_prices(
        self,
        start_dt: datetime,
        end_dt: datetime,
        zone: str = "OES",
        base_price_uah_mwh: float = 4600.0,
        price_cap_min: float = 10.0,
        price_cap_max: float = 9000.0,
    ) -> pd.DataFrame:
        """Generate hourly DAM prices matching SPEC §3.3."""
        current = start_dt.replace(minute=0, second=0, microsecond=0)
        rows: list[dict[str, Any]] = []

        while current <= end_dt:
            hour = current.hour
            month = current.month
            is_weekend = current.weekday() >= 5

            # Base components
            shape = self._hourly_price_profile(hour)
            season = self._seasonality_factor(month)
            weekend_adj = 0.82 if is_weekend else 1.0

            # Random noise (normal distribution ±4%)
            noise = self._rng.gauss(0.0, 0.04)

            # Random market shocks (1.5% probability of positive price spike)
            shock = 0.0
            if self._rng.random() < 0.015:
                shock = self._rng.uniform(1500.0, 3000.0)

            price = (base_price_uah_mwh * shape * season * weekend_adj * (1.0 + noise)) + shock
            price = max(price_cap_min, min(price_cap_max, price))

            rows.append(
                {
                    "ts": current,
                    "zone": zone,
                    "price_uah_mwh": round(price, 2),
                    "published_at": current
                    - timedelta(hours=hour + 11),  # Published previous day at 13:00
                    "source": "synthetic",
                }
            )
            current += timedelta(hours=1)

        return pd.DataFrame(rows)

    def generate_site_load(
        self,
        start_dt: datetime,
        end_dt: datetime,
        pv_peak_kw: float = 200.0,
    ) -> pd.DataFrame:
        """Generate industrial site load profile and PV generation matching SPEC §6.1."""
        current = start_dt.replace(minute=0, second=0, microsecond=0)
        rows: list[dict[str, Any]] = []

        while current <= end_dt:
            hour = current.hour
            month = current.month
            is_weekend = current.weekday() >= 5

            # 1. Industrial Load
            base_load = 100.0  # continuous baseload kW
            if not is_weekend:
                # Working shift 07:00 - 19:00
                if 7 <= hour <= 19:
                    work_load = 220.0 + self._rng.gauss(0.0, 15.0)
                else:
                    work_load = 15.0 + self._rng.gauss(0.0, 5.0)
            else:
                # Weekend reduced activity (~30% of weekday peak)
                work_load = 30.0 + self._rng.gauss(0.0, 8.0)

            # Seasonal heating / HVAC
            temp_adj = 15.0 if month in (12, 1, 2) else (10.0 if month in (6, 7, 8) else 0.0)
            total_load = max(30.0, base_load + work_load + temp_adj)

            # 2. PV Solar Generation (SPEC 200 kW peak)
            # Daylight hours dependent on month
            daylight_hours = {
                1: (8, 16),
                2: (7, 17),
                3: (6, 18),
                4: (6, 19),
                5: (5, 20),
                6: (5, 21),
                7: (5, 21),
                8: (6, 20),
                9: (6, 19),
                10: (7, 18),
                11: (7, 16),
                12: (8, 16),
            }
            sunrise, sunset = daylight_hours.get(month, (6, 18))

            pv_kw = 0.0
            if sunrise <= hour <= sunset:
                day_fraction = (hour - sunrise) / (sunset - sunrise)
                # Sine bell curve
                solar_intensity = math.sin(math.pi * day_fraction)
                # Seasonal intensity (summer peak 1.0, winter peak 0.45)
                seasonal_intensity = 0.45 + 0.55 * math.sin(math.pi * (month - 1) / 11)
                # Simulated cloud attenuation factor
                cloud_attenuation = self._rng.uniform(0.65, 1.0)
                pv_kw = pv_peak_kw * solar_intensity * seasonal_intensity * cloud_attenuation

            rows.append(
                {
                    "ts": current,
                    "load_kw": round(total_load, 2),
                    "pv_kw": round(max(0.0, pv_kw), 2),
                    "source": "synthetic",
                }
            )
            current += timedelta(hours=1)

        return pd.DataFrame(rows)

    def generate_weather(
        self,
        start_dt: datetime,
        end_dt: datetime,
    ) -> pd.DataFrame:
        """Generate weather series (temperature, cloud cover, wind)."""
        current = start_dt.replace(minute=0, second=0, microsecond=0)
        rows: list[dict[str, Any]] = []

        while current <= end_dt:
            hour = current.hour
            month = current.month

            # Temperature: monthly annual sine + diurnal daily sine
            month_t = 10.0 + 14.0 * math.sin(2 * math.pi * (month - 4) / 12)
            hour_t = 4.0 * math.sin(2 * math.pi * (hour - 9) / 24)
            temp = month_t + hour_t + self._rng.gauss(0.0, 1.5)

            cloud = min(1.0, max(0.0, self._rng.betavariate(2, 2)))
            wind = max(0.5, min(20.0, self._rng.weibullvariate(5.0, 2.0)))

            rows.append(
                {
                    "ts": current,
                    "temp_c": round(temp, 1),
                    "cloud_cover": round(cloud, 2),
                    "wind_speed_ms": round(wind, 1),
                }
            )
            current += timedelta(hours=1)

        return pd.DataFrame(rows)

    def generate_all(
        self,
        start_dt: datetime,
        end_dt: datetime,
    ) -> dict[str, pd.DataFrame]:
        """Generate all series over the requested time horizon."""
        return {
            "dam_prices": self.generate_dam_prices(start_dt, end_dt),
            "site_load": self.generate_site_load(start_dt, end_dt),
            "weather": self.generate_weather(start_dt, end_dt),
        }
