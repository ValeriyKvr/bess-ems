"""LightGBM multi-horizon forecasting model with quantile intervals (SPEC §8.3).

Trains independent LightGBM regressors for each step h in 1..24:
- Point prediction (L2 / Huber regression)
- Lower quantile p10 (alpha=0.1)
- Upper quantile p90 (alpha=0.9)
"""

import json
import logging
import os
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from ems.forecasting.models.base import ForecastModel

logger = logging.getLogger(__name__)


class LightGbmModel(ForecastModel):
    """Multi-output direct LightGBM model for 24h horizon forecasting."""

    name: str = "lightgbm"
    version: str = "1.0.0"

    def __init__(
        self,
        target: str = "price",
        horizon_h: int = 24,
        n_estimators: int = 60,
        learning_rate: float = 0.08,
        num_leaves: int = 24,
    ) -> None:
        self.target = target
        self.horizon_h = horizon_h
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.num_leaves = num_leaves

        self.models_point: list[lgb.LGBMRegressor] = []
        self.models_p10: list[lgb.LGBMRegressor] = []
        self.models_p90: list[lgb.LGBMRegressor] = []
        self.feature_names: list[str] = []

    def fit(self, X: pd.DataFrame, Y: pd.DataFrame) -> dict[str, float]:
        """Fit 24 separate models for each step of the forecasting horizon."""
        self.feature_names = list(X.columns)
        self.models_point = []
        self.models_p10 = []
        self.models_p90 = []

        total_mae = 0.0
        n_samples = len(X)
        # Cap n_jobs to prevent CPU thrashing / thread starvation in containerized environments
        effective_n_jobs = min(4, max(1, (os.cpu_count() or 1) // 2 or 1))

        for h in range(1, self.horizon_h + 1):
            target_col = f"h_{h}"
            y_h = Y[target_col] if target_col in Y.columns else Y.iloc[:, h - 1]

            # 1. Point regressor
            m_point = lgb.LGBMRegressor(
                objective="regression",
                n_estimators=self.n_estimators,
                learning_rate=self.learning_rate,
                num_leaves=self.num_leaves,
                verbosity=-1,
                n_jobs=effective_n_jobs,
                random_state=42,
            )
            m_point.fit(X, y_h)
            self.models_point.append(m_point)

            preds = m_point.predict(X)
            mae_h = float(np.mean(np.abs(preds - y_h)))
            total_mae += mae_h

            # 2. Quantile p10 regressor
            m_p10 = lgb.LGBMRegressor(
                objective="quantile",
                alpha=0.10,
                n_estimators=max(20, self.n_estimators // 2),
                learning_rate=self.learning_rate,
                num_leaves=max(12, self.num_leaves // 2),
                verbosity=-1,
                n_jobs=effective_n_jobs,
                random_state=42,
            )
            m_p10.fit(X, y_h)
            self.models_p10.append(m_p10)

            # 3. Quantile p90 regressor
            m_p90 = lgb.LGBMRegressor(
                objective="quantile",
                alpha=0.90,
                n_estimators=max(20, self.n_estimators // 2),
                learning_rate=self.learning_rate,
                num_leaves=max(12, self.num_leaves // 2),
                verbosity=-1,
                n_jobs=effective_n_jobs,
                random_state=42,
            )
            m_p90.fit(X, y_h)
            self.models_p90.append(m_p90)

        avg_train_mae = total_mae / self.horizon_h
        logger.info(
            "LightGBM trained %d horizon models on %d samples (avg train MAE: %.2f)",
            self.horizon_h,
            n_samples,
            avg_train_mae,
        )

        return {
            "samples": float(n_samples),
            "train_mae": float(avg_train_mae),
            "horizon_h": float(self.horizon_h),
        }

    def predict(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Generate point and quantile forecasts for input feature dataframe X."""
        if not self.models_point:
            raise RuntimeError("LightGbmModel must be fitted or loaded before predict()")

        # Ensure consistent column ordering
        if self.feature_names:
            X = X.reindex(columns=self.feature_names, fill_value=0.0)

        n = len(X)
        values = np.zeros((n, self.horizon_h), dtype=np.float32)
        p10 = np.zeros((n, self.horizon_h), dtype=np.float32)
        p90 = np.zeros((n, self.horizon_h), dtype=np.float32)

        for h in range(self.horizon_h):
            values[:, h] = self.models_point[h].predict(X)
            p10[:, h] = self.models_p10[h].predict(X)
            p90[:, h] = self.models_p90[h].predict(X)

        # Enforce logical consistency: p10 <= value <= p90
        p10 = np.minimum(p10, values)
        p90 = np.maximum(p90, values)

        return {
            "value": values,
            "p10": p10,
            "p90": p90,
        }

    def save(self, path: Path) -> None:
        """Save model binaries and metadata into directory path."""
        import joblib

        path.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "point": self.models_point,
                "p10": self.models_p10,
                "p90": self.models_p90,
                "feature_names": self.feature_names,
                "target": self.target,
                "horizon_h": self.horizon_h,
            },
            path / "models.joblib",
        )

        metadata = {
            "name": self.name,
            "version": self.version,
            "target": self.target,
            "horizon_h": self.horizon_h,
            "n_estimators": self.n_estimators,
            "learning_rate": self.learning_rate,
            "num_leaves": self.num_leaves,
            "feature_names": self.feature_names,
        }
        with open(path / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

    def load(self, path: Path) -> None:
        """Load model binaries and metadata from directory path."""
        import joblib

        bundle_path = path / "models.joblib"
        if bundle_path.exists():
            bundle = joblib.load(bundle_path)
            self.models_point = bundle["point"]
            self.models_p10 = bundle["p10"]
            self.models_p90 = bundle["p90"]
            self.feature_names = bundle.get("feature_names", [])
            self.target = bundle.get("target", "price")
            self.horizon_h = bundle.get("horizon_h", 24)
        else:
            with open(path / "metadata.json", encoding="utf-8") as f:
                metadata = json.load(f)
            self.target = metadata.get("target", "price")
            self.horizon_h = metadata.get("horizon_h", 24)
            self.feature_names = metadata.get("feature_names", [])
