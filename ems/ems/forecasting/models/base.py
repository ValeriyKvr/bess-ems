"""Abstract base class for forecasting models (SPEC §8.3)."""

from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import pandas as pd


class ForecastModel(ABC):
    """Abstract interface for multi-step time-series forecasting models."""

    name: str = "base"
    version: str = "0.1.0"
    target: str = "price"

    @abstractmethod
    def fit(self, X: pd.DataFrame, Y: pd.DataFrame) -> dict[str, float]:
        """Train model on features X and multi-step target matrix Y.

        Y has shape (N, horizon_h).
        Returns training metrics dict.
        """
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Generate forecasts for input feature dataframe X.

        Returns dict with keys:
          - 'value': np.ndarray of shape (N, horizon_h)
          - 'p10': np.ndarray of shape (N, horizon_h)
          - 'p90': np.ndarray of shape (N, horizon_h)
        """
        ...

    @abstractmethod
    def save(self, path: Path) -> None:
        """Persist model artifacts into directory path."""
        ...

    @abstractmethod
    def load(self, path: Path) -> None:
        """Load model artifacts from directory path."""
        ...
