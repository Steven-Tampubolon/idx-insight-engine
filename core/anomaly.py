# core/anomaly.py
import pandas as pd
import numpy as np
from scipy import stats

DEFAULT_METRICS = ["forward_pe", "pb", "roe", "dividend_yield"]

def detect_anomalies(
    df        : pd.DataFrame,
    metrics   : list  = None,
    threshold : float = 2.0
) -> pd.DataFrame:
    """
    Z-score per sub-sektor (bukan global) untuk setiap metrik.
    Reads dari DataFrame yang sudah di-load dari SQLite — 0 Sectors credits.

    Returns df dengan kolom tambahan:
        z_{metric}      float   z-score vs median sub-sektor
        anomaly_score   float   total |z-score| dari semua metrik yang flagged
        anomaly_flags   list    nama metrik yang melewati threshold
        is_anomaly      bool    True jika minimal 1 flag
    """
    metrics   = metrics or DEFAULT_METRICS
    result    = df.copy()

    # Hanya proses metric yang ada di DataFrame
    avail = [m for m in metrics if m in result.columns]

    # Inisialisasi kolom — pakai list comprehension agar tiap row punya list baru
    for m in avail:
        result[f"z_{m}"] = 0.0
    result["anomaly_score"] = 0.0
    result["anomaly_flags"] = [[] for _ in range(len(result))]

    for metric in avail:
        for subsector, group in result.groupby("sub_sector"):
            col = group[metric].dropna()
            if len(col) < 3:          # skip jika peer terlalu sedikit
                continue

            z_vals = stats.zscore(col, nan_policy="omit")
            result.loc[col.index, f"z_{metric}"] = np.round(z_vals, 3)
            result.loc[col.index, "anomaly_score"] += np.abs(z_vals)

            # Flag perusahaan yang melewati threshold di metrik ini
            flagged = col.index[np.abs(z_vals) > threshold]
            for idx in flagged:
                result.at[idx, "anomaly_flags"] = (
                    result.at[idx, "anomaly_flags"] + [metric]
                )

    result["is_anomaly"] = result["anomaly_flags"].apply(bool)
    return result.reset_index(drop=True)