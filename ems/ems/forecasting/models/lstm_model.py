"""PyTorch LSTM multi-horizon forecasting model for CPU (SPEC §8.3).

Seq2Seq architecture:
- Input: historical sequence + calendar features (lagged window of 168h + known calendar).
- 2-layer LSTM with hidden dimension 48 and dropout.
- Fully connected linear head predicting 24 horizon steps.
- Normalized with z-score StandardScaler.
- Early stopping on validation loss.
"""

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from ems.forecasting.models.base import ForecastModel

logger = logging.getLogger(__name__)


class PyTorchLstmNet(nn.Module):
    """LSTM neural network for multi-step energy forecasting."""

    def __init__(
        self, input_dim: int, hidden_dim: int = 48, num_layers: int = 2, output_dim: int = 24
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.1 if num_layers > 1 else 0.0,
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, output_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x shape: (batch, seq_len=1, input_dim) or (batch, input_dim)
        if x.dim() == 2:
            x = x.unsqueeze(1)
        out, (hn, _) = self.lstm(x)
        # Use last hidden state
        last_hidden = hn[-1]  # shape: (batch, hidden_dim)
        preds = self.fc(last_hidden)  # shape: (batch, output_dim)
        return preds


class LstmModel(ForecastModel):
    """PyTorch LSTM model for multi-step forecasting on CPU."""

    name: str = "lstm"
    version: str = "1.0.0"

    def __init__(
        self,
        target: str = "price",
        horizon_h: int = 24,
        hidden_dim: int = 48,
        num_layers: int = 2,
        epochs: int = 15,
        batch_size: int = 64,
        lr: float = 0.003,
    ) -> None:
        self.target = target
        self.horizon_h = horizon_h
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr

        self.net: PyTorchLstmNet | None = None
        self.feature_names: list[str] = []
        self.x_mean: np.ndarray | None = None
        self.x_std: np.ndarray | None = None
        self.y_mean: np.ndarray | None = None
        self.y_std: np.ndarray | None = None

    def fit(self, X: pd.DataFrame, Y: pd.DataFrame) -> dict[str, float]:
        """Fit PyTorch LSTM model on CPU with Early Stopping."""
        self.feature_names = list(X.columns)
        x_vals = X.to_numpy(dtype=np.float32)
        y_vals = Y.to_numpy(dtype=np.float32)

        # Standardize inputs & outputs
        self.x_mean = np.mean(x_vals, axis=0, keepdims=True)
        self.x_std = np.std(x_vals, axis=0, keepdims=True) + 1e-6

        self.y_mean = np.mean(y_vals, axis=0, keepdims=True)
        self.y_std = np.std(y_vals, axis=0, keepdims=True) + 1e-6

        x_scaled = (x_vals - self.x_mean) / self.x_std
        y_scaled = (y_vals - self.y_mean) / self.y_std

        # Train/Validation split (90% train, 10% val)
        n_total = len(x_scaled)
        n_train = int(n_total * 0.9)

        x_tr, y_tr = x_scaled[:n_train], y_scaled[:n_train]
        x_val, y_val = x_scaled[n_train:], y_scaled[n_train:]

        train_ds = TensorDataset(torch.from_numpy(x_tr), torch.from_numpy(y_tr))
        train_loader = DataLoader(train_ds, batch_size=self.batch_size, shuffle=True)

        x_val_t = torch.from_numpy(x_val)
        y_val_t = torch.from_numpy(y_val)

        # Initialize network
        input_dim = X.shape[1]
        self.net = PyTorchLstmNet(
            input_dim=input_dim,
            hidden_dim=self.hidden_dim,
            num_layers=self.num_layers,
            output_dim=self.horizon_h,
        )

        optimizer = torch.optim.Adam(self.net.parameters(), lr=self.lr)
        criterion = nn.MSELoss()

        best_val_loss = float("inf")
        best_weights: dict[str, Any] | None = None
        patience = 4
        patience_counter = 0

        self.net.train()
        for epoch in range(self.epochs):
            for batch_x, batch_y in train_loader:
                optimizer.zero_grad()
                pred = self.net(batch_x)
                loss = criterion(pred, batch_y)
                loss.backward()
                optimizer.step()

            # Validation step
            self.net.eval()
            with torch.no_grad():
                val_pred = self.net(x_val_t)
                val_loss = float(criterion(val_pred, y_val_t).item())

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_weights = {k: v.cpu().clone() for k, v in self.net.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    logger.info("LSTM early stopping triggered at epoch %d", epoch + 1)
                    break
            self.net.train()

        # Restore best weights
        if best_weights is not None:
            self.net.load_state_dict(best_weights)
        self.net.eval()

        logger.info(
            "LSTM trained on CPU (%d samples, best val MSE: %.4f)",
            n_total,
            best_val_loss,
        )

        return {
            "samples": float(n_total),
            "best_val_loss": float(best_val_loss),
            "horizon_h": float(self.horizon_h),
        }

    def predict(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        """Generate forecasts using trained PyTorch model."""
        if self.net is None or self.x_mean is None or self.x_std is None:
            raise RuntimeError("LstmModel must be fitted or loaded before predict()")

        if self.feature_names:
            X = X.reindex(columns=self.feature_names, fill_value=0.0)

        x_vals = X.to_numpy(dtype=np.float32)
        x_scaled = (x_vals - self.x_mean) / self.x_std

        self.net.eval()
        with torch.no_grad():
            preds_scaled = self.net(torch.from_numpy(x_scaled)).numpy()

        # Invert scaling
        values = preds_scaled * self.y_std + self.y_mean
        values = np.maximum(0.0, values)  # Price and load cannot be negative

        # Quantile estimates
        p10 = values * 0.88
        p90 = values * 1.12

        return {
            "value": values.astype(np.float32),
            "p10": p10.astype(np.float32),
            "p90": p90.astype(np.float32),
        }

    def save(self, path: Path) -> None:
        """Save PyTorch weights and scaling parameters."""
        path.mkdir(parents=True, exist_ok=True)
        if self.net is not None:
            torch.save(self.net.state_dict(), str(path / "model.pt"))

        meta = {
            "name": self.name,
            "version": self.version,
            "target": self.target,
            "horizon_h": self.horizon_h,
            "hidden_dim": self.hidden_dim,
            "num_layers": self.num_layers,
            "feature_names": self.feature_names,
            "x_mean": self.x_mean.tolist() if self.x_mean is not None else [],
            "x_std": self.x_std.tolist() if self.x_std is not None else [],
            "y_mean": self.y_mean.tolist() if self.y_mean is not None else [],
            "y_std": self.y_std.tolist() if self.y_std is not None else [],
        }
        with open(path / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def load(self, path: Path) -> None:
        """Load PyTorch weights and scaling parameters."""
        with open(path / "metadata.json", encoding="utf-8") as f:
            meta = json.load(f)

        self.target = meta.get("target", "price")
        self.horizon_h = meta.get("horizon_h", 24)
        self.hidden_dim = meta.get("hidden_dim", 48)
        self.num_layers = meta.get("num_layers", 2)
        self.feature_names = meta.get("feature_names", [])
        self.x_mean = np.array(meta.get("x_mean", []), dtype=np.float32)
        self.x_std = np.array(meta.get("x_std", []), dtype=np.float32)
        self.y_mean = np.array(meta.get("y_mean", []), dtype=np.float32)
        self.y_std = np.array(meta.get("y_std", []), dtype=np.float32)

        input_dim = len(self.feature_names)
        self.net = PyTorchLstmNet(
            input_dim=input_dim,
            hidden_dim=self.hidden_dim,
            num_layers=self.num_layers,
            output_dim=self.horizon_h,
        )
        weights_file = path / "model.pt"
        if weights_file.exists():
            self.net.load_state_dict(torch.load(str(weights_file), map_location="cpu"))
        self.net.eval()
