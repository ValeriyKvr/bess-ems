"""Unit and integration tests for Stage 6: Forecasting (ML/DL) (SPEC §8, §14)."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ems.forecasting.features import (
    build_cutoff_features,
    build_features_and_targets,
    get_calendar_features,
)
from ems.forecasting.models.lightgbm_model import LightGbmModel
from ems.forecasting.models.lstm_model import LstmModel
from ems.forecasting.models.naive import NaiveModel
from ems.forecasting.train import compute_metrics
from ems.ingestion.generator import SyntheticDataGenerator


def test_calendar_features() -> None:
    """Verify cyclic calendar feature encoding."""
    dt = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    feats = get_calendar_features(dt)

    assert "hour_sin" in feats and "hour_cos" in feats
    assert "dow_sin" in feats and "dow_cos" in feats
    assert "is_weekend" in feats
    assert feats["is_weekend"] == 1.0  # March 1, 2026 is Sunday


def test_features_no_future_leakage() -> None:
    """Strictly verify that altering future target values does NOT alter feature vector at cutoff T_0."""
    start_dt = datetime(2025, 1, 1, tzinfo=UTC)
    dates = [start_dt + timedelta(hours=i) for i in range(500)]

    np.random.seed(42)
    base_values = np.random.uniform(2000.0, 6000.0, size=500)
    df1 = pd.DataFrame({"ts": dates, "price": base_values.copy()})

    cutoff_idx = 400
    s1 = df1.set_index("ts")["price"]
    feats1 = build_cutoff_features(s1, cutoff_idx)

    # Modify future values (indices 401..499) drastically
    df2 = df1.copy()
    df2.loc[401:, "price"] = df2.loc[401:, "price"] * 10.0 + 99999.0
    s2 = df2.set_index("ts")["price"]
    feats2 = build_cutoff_features(s2, cutoff_idx)

    # Features at cutoff MUST be completely identical
    for k in feats1:
        assert feats1[k] == pytest.approx(feats2[k], rel=1e-6), f"Feature {k} leaked future data!"


def test_naive_model() -> None:
    """Verify seasonal Naive model behaviour, intervals, and error bounds."""
    gen = SyntheticDataGenerator(seed=42)
    df = gen.generate_dam_prices(
        datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 15, tzinfo=UTC)
    )
    df = df.rename(columns={"price_uah_mwh": "price"})

    X, Y, _ = build_features_and_targets(df, target_col="price", horizon_h=24)
    model = NaiveModel(target="price", horizon_h=24)
    model.fit(X, Y)

    preds = model.predict(X)
    assert preds["value"].shape == (len(X), 24)
    assert preds["p10"].shape == (len(X), 24)
    assert preds["p90"].shape == (len(X), 24)

    # Quantile ordering
    assert np.all(preds["p10"] <= preds["value"])
    assert np.all(preds["value"] <= preds["p90"])

    metrics = compute_metrics(Y.to_numpy(), preds["value"])
    assert metrics["mape"] < 100.0, f"Naive MAPE too high: {metrics['mape']}%"


def test_lightgbm_beats_naive() -> None:
    """Verify LightGBM achieves lower MAE than Naive on synthetic DAM prices."""
    gen = SyntheticDataGenerator(seed=42)
    df = gen.generate_dam_prices(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC))
    df = df.rename(columns={"price_uah_mwh": "price"})

    X, Y, _ = build_features_and_targets(df, target_col="price", horizon_h=24)

    # 80/20 split
    split = int(len(X) * 0.8)
    X_train, Y_train = X.iloc[:split], Y.iloc[:split]
    X_test, Y_test = X.iloc[split:], Y.iloc[split:]

    naive = NaiveModel(target="price", horizon_h=24)
    naive.fit(X_train, Y_train)
    preds_naive = naive.predict(X_test)
    metrics_naive = compute_metrics(Y_test.to_numpy(), preds_naive["value"])

    lgb_model = LightGbmModel(target="price", horizon_h=24, n_estimators=30, learning_rate=0.1)
    lgb_model.fit(X_train, Y_train)
    preds_lgb = lgb_model.predict(X_test)
    metrics_lgb = compute_metrics(Y_test.to_numpy(), preds_lgb["value"])

    assert metrics_lgb["mae"] < metrics_naive["mae"], (
        f"LightGBM MAE ({metrics_lgb['mae']}) should beat Naive MAE ({metrics_naive['mae']})"
    )
    assert metrics_lgb["spearman_rank_corr"] > 0.5, "LightGBM should capture daily price shape"


def test_model_save_load() -> None:
    """Verify saving and loading model artifacts preserves weights and predictions."""
    gen = SyntheticDataGenerator(seed=42)
    df = gen.generate_dam_prices(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC))
    df = df.rename(columns={"price_uah_mwh": "price"})
    X, Y, _ = build_features_and_targets(df, target_col="price", horizon_h=24)

    model1 = LightGbmModel(target="price", horizon_h=24, n_estimators=10)
    model1.fit(X.iloc[:100], Y.iloc[:100])
    orig_preds = model1.predict(X.iloc[100:110])

    with tempfile.TemporaryDirectory() as tmpdir:
        save_path = Path(tmpdir) / "lgb_test"
        model1.save(save_path)

        model2 = LightGbmModel(target="price", horizon_h=24)
        model2.load(save_path)
        loaded_preds = model2.predict(X.iloc[100:110])

        np.testing.assert_allclose(orig_preds["value"], loaded_preds["value"], rtol=1e-5)
        np.testing.assert_allclose(orig_preds["p10"], loaded_preds["p10"], rtol=1e-5)
        np.testing.assert_allclose(orig_preds["p90"], loaded_preds["p90"], rtol=1e-5)


def test_lstm_model_cpu() -> None:
    """Verify PyTorch Seq2Seq LSTM trains and predicts on CPU."""
    gen = SyntheticDataGenerator(seed=42)
    df = gen.generate_dam_prices(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC))
    df = df.rename(columns={"price_uah_mwh": "price"})
    X, Y, _ = build_features_and_targets(df, target_col="price", horizon_h=24)

    lstm = LstmModel(target="price", horizon_h=24, epochs=2, hidden_dim=32, batch_size=32)
    lstm.fit(X.iloc[:150], Y.iloc[:150])

    preds = lstm.predict(X.iloc[150:160])
    assert preds["value"].shape == (10, 24)
    assert preds["p10"].shape == (10, 24)
    assert preds["p90"].shape == (10, 24)
