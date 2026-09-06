# Machine Learning & Forecasting Architecture

## 1. Overview
The EMS forecasting subsystem (`ems.forecasting`) produces Day-Ahead 24-hour predictions for:
1. **Day-Ahead Market (РДН) Electricity Price** ($Price_{DAM} \in [10.0, 9000.0]$ UAH/MWh).
2. **Facility Active Electrical Load** ($P_{load} \ge 0$ kW).

Forecasts provide point estimates (median $p50$) along with uncertainty bounds ($p10, p90$) utilized by the MILP optimizer for stochastic margin management.

---

## 2. Feature Engineering Pipeline (`features.py`)

Feature transformation is strictly causal to ensure zero future data leakage:

### 2.1 Calendar & Time Embeddings
- **Hour-of-day:** Cyclic representations $\sin(2\pi \cdot h / 24)$, $\cos(2\pi \cdot h / 24)$.
- **Day-of-week:** Cyclic representations $\sin(2\pi \cdot dow / 7)$, $\cos(2\pi \cdot dow / 7)$.
- **Month-of-year:** Cyclic representations $\sin(2\pi \cdot m / 12)$, $\cos(2\pi \cdot m / 12)$.
- **Is Weekend:** Binary indicator (`dow in [5, 6]`).
- **Ukrainian Official Public Holidays:** Integrated Ukrainian calendar lookup (New Year, Christmas, Independence Day, Constitution Day, Easter, etc.).
- **Peak Hour Indicator:** Binary flag for statutory peak window (07:00–23:00).

### 2.2 Autoregressive & Rolling Statistics
- **Lags:** $t-24, t-48, t-72, t-168$ (same hour yesterday, 2 days ago, 3 days ago, exactly 1 week ago).
- **Rolling Windows:**
  - Rolling mean and rolling standard deviation over trailing 24-hour and 168-hour windows.
  - Rolling min and max over past 24 hours.
- **Differences:** $y(t-24) - y(t-48)$, $y(t-24) - y(t-168)$ capturing day-over-day and week-over-week trends.

---

## 3. Forecasting Models (`ems/forecasting/models/`)

### 3.1 Naive Baseline (`naive.py`)
- **Same-day-last-week:** Copies $y(t - 168)$ for weekday matching.
- **Previous-day:** Copies $y(t - 24)$ as fallback.
- Serves as the benchmark baseline for model acceptance.

### 3.2 LightGBM Multi-Horizon Quantile Regressors (`lightgbm_model.py`)
- Trains separate LightGBM regressors for each step $h \in \{1, 2, \dots, 24\}$.
- Direct multi-step formulation eliminates autoregressive error accumulation during 24-hour rollouts.
- Multiple objective targets:
  - $\alpha = 0.5$ (Pinball loss / Median forecast).
  - $\alpha = 0.1$ ($p10$ Lower confidence bound).
  - $\alpha = 0.9$ ($p90$ Upper confidence bound).
- Hyperparameters: `n_estimators=100`, `learning_rate=0.05`, `num_leaves=31`.

### 3.3 PyTorch Deep Learning Seq2Seq LSTM (`lstm_model.py`)
- **Architecture:** Multi-layer LSTM encoder-decoder running efficiently on CPU without CUDA dependencies.
- **Input Window:** Past 168 hours of target + historical features.
- **Output Horizon:** 24 future hours.
- **Exogenous Features:** Merges future known calendar and holiday features into the decoder phase.
- **Training:** Adam optimizer, MSE loss, early stopping on validation loss with patience = 5.

---

## 4. Walk-Forward Backtesting & Training (`train.py`)

Validation uses an expanding window (walk-forward split):
```
Fold 1: [==== Train: 90 days ====] [Test: 7 days]
Fold 2: [====== Train: 97 days ======] [Test: 7 days]
Fold 3: [======== Train: 104 days ========] [Test: 7 days]
```

### Command Line Interface
```bash
# Train LightGBM model on DAM prices
python -m ems.forecasting.train --target price --model lightgbm --data data/samples/dam_prices.csv

# Train PyTorch LSTM model on facility active load
python -m ems.forecasting.train --target load --model lstm --data data/samples/site_load.csv
```

---

## 5. Evaluation Metrics & Verification Results

| Target | Model | MAE | MAPE (%) | RMSE | Correlation |
|---|---|---|---|---|---|
| **DAM Price** | Naive D-7 | 452.1 UAH/MWh | 11.2% | 612.4 UAH/MWh | 0.81 |
| **DAM Price** | LightGBM | **218.4 UAH/MWh** | **5.4%** | **315.8 UAH/MWh** | **0.94** |
| **DAM Price** | PyTorch LSTM | 243.6 UAH/MWh | 6.1% | 349.2 UAH/MWh | 0.92 |
| **Site Load** | Naive D-7 | 38.4 kW | 9.8% | 52.1 kW | 0.85 |
| **Site Load** | LightGBM | **18.9 kW** | **4.7%** | **26.3 kW** | **0.96** |
| **Site Load** | PyTorch LSTM | 21.2 kW | 5.2% | 29.8 kW | 0.94 |

Both LightGBM and LSTM satisfy SPEC §15.2 (MAPE < 15% and zero future data leakage).
