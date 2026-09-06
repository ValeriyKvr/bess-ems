"""CSV Importer, validator, resampler, and gap-filler (SPEC §6.1)."""

import io
from datetime import UTC, datetime
from typing import BinaryIO

import pandas as pd


class CsvValidationError(ValueError):
    """Raised when CSV structure or values fail validation."""

    pass


class CsvDataImporter:
    """Imports, validates, resamples, and imputes energy data from CSV files."""

    @staticmethod
    def import_dam_prices(file_input: str | bytes | BinaryIO, zone: str = "OES") -> pd.DataFrame:
        """Import Day-Ahead Market prices from CSV matching docs/data-formats.md.

        Expected CSV columns: date, hour, price_uah_mwh, zone (optional)
        """
        if isinstance(file_input, bytes):
            stream = io.BytesIO(file_input)
        elif isinstance(file_input, str):
            stream = io.StringIO(file_input)
        else:
            stream = file_input

        try:
            df = pd.read_csv(stream)
        except Exception as e:
            raise CsvValidationError(f"Cannot parse CSV file: {e}") from e

        # Normalize column names
        df.columns = [col.strip().lower() for col in df.columns]
        required = {"date", "hour", "price_uah_mwh"}
        if not required.issubset(set(df.columns)):
            raise CsvValidationError(f"Missing required columns: {required - set(df.columns)}")

        # Convert date & hour to UTC timestamps
        timestamps: list[datetime] = []
        for _, row in df.iterrows():
            try:
                d = pd.to_datetime(row["date"]).date()
                h = int(row["hour"])
                if not (1 <= h <= 24):
                    raise ValueError(f"Hour must be between 1 and 24, got {h}")
                ts = datetime(d.year, d.month, d.day, h - 1, 0, 0, tzinfo=UTC)
                timestamps.append(ts)
            except Exception as e:
                raise CsvValidationError(f"Invalid date/hour row ({row.to_dict()}): {e}") from e

        df["ts"] = timestamps
        df["price_uah_mwh"] = pd.to_numeric(df["price_uah_mwh"], errors="coerce")

        if df["price_uah_mwh"].isnull().any():
            # Interpolate missing prices
            df["price_uah_mwh"] = df["price_uah_mwh"].interpolate(method="linear").bfill().ffill()

        if "zone" not in df.columns:
            df["zone"] = zone
        else:
            df["zone"] = df["zone"].fillna(zone)

        # Published timestamp (at 13:00 previous day)
        df["published_at"] = df["ts"] - pd.to_timedelta(df["ts"].dt.hour + 11, unit="h")
        df["source"] = "csv_import"

        return df[["ts", "zone", "price_uah_mwh", "published_at", "source"]].sort_values("ts")

    @staticmethod
    def import_site_load(file_input: str | bytes | BinaryIO) -> pd.DataFrame:
        """Import site load and optional PV from CSV.

        Expected columns: ts, load_kw, pv_kw (optional)
        """
        if isinstance(file_input, bytes):
            stream = io.BytesIO(file_input)
        elif isinstance(file_input, str):
            stream = io.StringIO(file_input)
        else:
            stream = file_input

        try:
            df = pd.read_csv(stream)
        except Exception as e:
            raise CsvValidationError(f"Cannot parse CSV: {e}") from e

        df.columns = [col.strip().lower() for col in df.columns]
        if "ts" not in df.columns or "load_kw" not in df.columns:
            raise CsvValidationError("CSV must contain at least 'ts' and 'load_kw' columns.")

        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df["load_kw"] = pd.to_numeric(df["load_kw"], errors="coerce")

        if "pv_kw" in df.columns:
            df["pv_kw"] = pd.to_numeric(df["pv_kw"], errors="coerce").fillna(0.0)
        else:
            df["pv_kw"] = 0.0

        # Validate non-negativity and impute missing
        if df["load_kw"].isnull().any():
            df["load_kw"] = df["load_kw"].interpolate(method="linear").bfill().ffill()

        df["load_kw"] = df["load_kw"].clip(lower=0.0)
        df["pv_kw"] = df["pv_kw"].clip(lower=0.0)
        df["source"] = "csv_import"

        return df[["ts", "load_kw", "pv_kw", "source"]].sort_values("ts")

    @staticmethod
    def resample_series(
        df: pd.DataFrame,
        target_step: str = "1h",
        value_cols: list[str] | None = None,
    ) -> pd.DataFrame:
        """Resample a time series dataframe to target step ('1h' or '15min')."""
        if "ts" not in df.columns:
            raise ValueError("DataFrame must have a 'ts' column to resample.")

        freq = "1h" if target_step == "1h" else "15min"
        df_indexed = df.set_index("ts")

        if value_cols is None:
            value_cols = [
                c for c in df_indexed.columns if pd.api.types.is_numeric_dtype(df_indexed[c])
            ]

        resampled = df_indexed[value_cols].resample(freq).mean().interpolate(method="time")
        resampled = resampled.reset_index()

        # Re-attach categorical columns by forward filling
        cat_cols = [c for c in df.columns if c not in value_cols and c != "ts"]
        for col in cat_cols:
            resampled[col] = df_indexed[col].resample(freq).ffill().values

        return resampled
