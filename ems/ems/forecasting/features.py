"""Feature engineering for time-series forecasting without future leakage (SPEC §8.2).

Extracts:
- Cyclic calendar features: hour, day of week, month, day of year (sin/cos).
- Ukrainian holiday calendar and weekend indicators.
- Heating season indicator (Oct 15 to Apr 15).
- Historical target lags: t, t-1, t-2, t-23, t-47, t-167, t-335 (1h, 2h, 24h, 48h, 7d, 14d ago).
- Rolling window statistics (24h and 168h): mean, std, min, max, ratios.
- Exogenous weather and load features when available.

Strict invariant:
All features at cutoff time T_0 are strictly computed using observations at or before T_0.
Future target values (T_0 + 1 ... T_0 + horizon) are never accessed when building X.
"""

import math
from datetime import date, datetime
from typing import Any

import pandas as pd

# Ukrainian official state holidays (month, day)
UKRAINIAN_FIXED_HOLIDAYS = {
    (1, 1),  # New Year
    (1, 7),  # Christmas (Julian)
    (3, 8),  # International Women's Day
    (5, 1),  # International Workers' Day
    (5, 8),  # Day of Remembrance and Reconciliation
    (5, 9),  # Victory Day
    (6, 28),  # Constitution Day
    (7, 15),  # Statehood Day (new)
    (7, 28),  # Statehood Day (old)
    (8, 24),  # Independence Day
    (10, 1),  # Defenders Day (new)
    (10, 14),  # Defenders Day (old)
    (12, 25),  # Christmas (Gregorian)
}


def is_ukrainian_holiday(d: date | datetime) -> bool:
    """Check if date is an official Ukrainian public holiday."""
    return (d.month, d.day) in UKRAINIAN_FIXED_HOLIDAYS


def is_heating_season(d: date | datetime) -> bool:
    """Check if date falls within Ukraine's heating season (Oct 15 - Apr 15)."""
    m, day = d.month, d.day
    if m in (11, 12, 1, 2, 3):
        return True
    if m == 10 and day >= 15:
        return True
    if m == 4 and day <= 15:
        return True
    return False


def get_calendar_features(dt: datetime) -> dict[str, float]:
    """Compute cyclic calendar features for a given datetime."""
    h = dt.hour
    dow = dt.weekday()  # 0 = Monday, 6 = Sunday
    m = dt.month - 1  # 0..11
    doy = dt.timetuple().tm_yday - 1  # 0..365

    is_wknd = 1.0 if dow in (5, 6) else 0.0
    is_hol = 1.0 if is_ukrainian_holiday(dt) else 0.0
    is_heat = 1.0 if is_heating_season(dt) else 0.0

    return {
        "hour_sin": math.sin(2.0 * math.pi * h / 24.0),
        "hour_cos": math.cos(2.0 * math.pi * h / 24.0),
        "dow_sin": math.sin(2.0 * math.pi * dow / 7.0),
        "dow_cos": math.cos(2.0 * math.pi * dow / 7.0),
        "month_sin": math.sin(2.0 * math.pi * m / 12.0),
        "month_cos": math.cos(2.0 * math.pi * m / 12.0),
        "doy_sin": math.sin(2.0 * math.pi * doy / 365.25),
        "doy_cos": math.cos(2.0 * math.pi * doy / 365.25),
        "is_weekend": is_wknd,
        "is_holiday": is_hol,
        "is_non_working": max(is_wknd, is_hol),
        "is_heating_season": is_heat,
    }


def build_cutoff_features(
    series: pd.Series,
    cutoff_idx: int,
    exog_series: pd.Series | None = None,
) -> dict[str, float]:
    """Build feature vector for a specific cutoff index strictly using data <= cutoff_idx."""
    cutoff_val = float(series.iloc[cutoff_idx])
    cutoff_ts = series.index[cutoff_idx]

    feats = get_calendar_features(cutoff_ts)

    # 1. Historical target lags (relative to cutoff time t)
    # lag 0 = current value at cutoff
    feats["lag_0"] = cutoff_val
    for k in range(1, 25):
        feats[f"lag_{k}"] = float(series.iloc[cutoff_idx - k]) if cutoff_idx >= k else cutoff_val
    feats["lag_48"] = float(series.iloc[cutoff_idx - 48]) if cutoff_idx >= 48 else cutoff_val
    feats["lag_168"] = float(series.iloc[cutoff_idx - 168]) if cutoff_idx >= 168 else cutoff_val
    feats["lag_336"] = float(series.iloc[cutoff_idx - 336]) if cutoff_idx >= 336 else cutoff_val

    # 2. Rolling statistics over past 24 hours (ending at cutoff_idx inclusive)
    start_24 = max(0, cutoff_idx - 23)
    w24 = series.iloc[start_24 : cutoff_idx + 1]
    mean_24 = float(w24.mean())
    std_24 = float(w24.std()) if len(w24) > 1 else 0.0
    min_24 = float(w24.min())
    max_24 = float(w24.max())

    feats["rolling_mean_24"] = mean_24
    feats["rolling_std_24"] = std_24
    feats["rolling_min_24"] = min_24
    feats["rolling_max_24"] = max_24
    feats["ratio_val_to_mean24"] = (cutoff_val / mean_24) if mean_24 > 1e-3 else 1.0

    # 3. Rolling statistics over past 168 hours (7 days)
    start_168 = max(0, cutoff_idx - 167)
    w168 = series.iloc[start_168 : cutoff_idx + 1]
    mean_168 = float(w168.mean())
    std_168 = float(w168.std()) if len(w168) > 1 else 0.0

    feats["rolling_mean_168"] = mean_168
    feats["rolling_std_168"] = std_168
    feats["ratio_val_to_mean168"] = (cutoff_val / mean_168) if mean_168 > 1e-3 else 1.0

    # 4. Optional exogenous feature
    if exog_series is not None and len(exog_series) > cutoff_idx:
        exog_val = float(exog_series.iloc[cutoff_idx])
        exog_w24 = exog_series.iloc[start_24 : cutoff_idx + 1]
        feats["exog_lag_0"] = exog_val
        feats["exog_mean_24"] = float(exog_w24.mean())

    return feats


def build_features_and_targets(
    df: pd.DataFrame,
    target_col: str,
    horizon_h: int = 24,
    exog_col: str | None = None,
    min_history_steps: int = 336,  # At least 2 weeks of history before first cutoff
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Construct full feature matrix X and multi-step target matrix Y for training.

    X has shape (N, num_features)
    Y has shape (N, horizon_h) where Y[i, h-1] = target at step (cutoff + h)
    """
    clean_df = df.copy().sort_values("ts").reset_index(drop=True)
    if "ts" in clean_df.columns:
        clean_df = clean_df.set_index("ts")

    target_s = clean_df[target_col]
    exog_s = clean_df[exog_col] if exog_col and exog_col in clean_df.columns else None

    n_total = len(target_s)
    x_rows: list[dict[str, float]] = []
    y_rows: list[list[float]] = []
    cutoff_indices: list[Any] = []

    for i in range(min_history_steps, n_total - horizon_h):
        cutoff_feats = build_cutoff_features(target_s, i, exog_s)
        x_rows.append(cutoff_feats)

        # Target values for t+1 to t+horizon
        y_future = [float(target_s.iloc[i + h]) for h in range(1, horizon_h + 1)]
        y_rows.append(y_future)
        cutoff_indices.append(target_s.index[i])

    X = pd.DataFrame(x_rows, index=cutoff_indices)
    Y = pd.DataFrame(
        y_rows,
        index=cutoff_indices,
        columns=[f"h_{h}" for h in range(1, horizon_h + 1)],
    )

    feature_names = list(X.columns)
    return X, Y, feature_names


def build_inference_features(
    history_df: pd.DataFrame,
    target_col: str,
    exog_col: str | None = None,
) -> pd.DataFrame:
    """Build single-row feature dataframe X for inference at the latest available point in history_df."""
    clean_df = history_df.copy().sort_values("ts").reset_index(drop=True)
    if "ts" in clean_df.columns:
        clean_df = clean_df.set_index("ts")

    target_s = clean_df[target_col]
    exog_s = clean_df[exog_col] if exog_col and exog_col in clean_df.columns else None

    latest_idx = len(target_s) - 1
    feats = build_cutoff_features(target_s, latest_idx, exog_s)
    return pd.DataFrame([feats])
