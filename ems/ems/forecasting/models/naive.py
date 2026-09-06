"""Baseline naive persistence forecasting model (SPEC §8.3)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ems.forecasting.models.base import ForecastModel


class NaiveModel(ForecastModel):
    """Seasonal naive model: tomorrow's value equals yesterday's value at same hour."""

    name: str = "naive"
    version: str = "1.0.0"

    def __init__(self, target: str = "price", horizon_h: int = 24) -> None:
        self.target = target
        self.horizon_h = horizon_h

    def fit(self, X: pd.DataFrame, Y: pd.DataFrame) -> dict[str, float]:
        """Naive model has no parameters to fit."""
        return {"fitted_samples": float(len(X))}

    def predict(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Predict using seasonal hourly lags (yesterday at the same hour)."""
        n = len(X)
        res = np.zeros((n, self.horizon_h), dtype=np.float32)

        for h in range(1, self.horizon_h + 1):
            lag_col = f"lag_{24 - h}"
            if lag_col in X.columns:
                res[:, h - 1] = X[lag_col].to_numpy()
            elif "lag_0" in X.columns:
                res[:, h - 1] = X["lag_0"].to_numpy()
            else:
                res[:, h - 1] = 4500.0

        return {
            "value": res,
            "p10": res * 0.85,
            "p90": res * 1.15,
        }

    def save(self, path: Path) -> None:
        """Save configuration metadata."""
        path.mkdir(parents=True, exist_ok=True)
        meta = {
            "name": self.name,
            "version": self.version,
            "target": self.target,
            "horizon_h": self.horizon_h,
        }
        with open(path / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def load(self, path: Path) -> None:
        """Load configuration metadata."""
        with open(path / "metadata.json", encoding="utf-8") as f:
            meta = json.load(f)
            self.target = meta.get("target", "price")
            self.horizon_h = meta.get("horizon_h", 24)
