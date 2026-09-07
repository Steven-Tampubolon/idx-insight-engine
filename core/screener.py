import pandas as pd, numpy as np

VALID_METRICS = ["forward_pe", "pb", "roe", "dividend_yield", "market_cap", "revenue_growth"]

def normalize(series: pd.Series, method: str = "minmax") -> pd.Series:
    if method == "minmax":
        mn, mx = series.min(), series.max()
        return (series - mn) / (mx - mn + 1e-9)
    return (series - series.mean()) / (series.std() + 1e-9)   # z-score

def build_score(df: pd.DataFrame, metrics: list, weights: dict,
                method: str = "minmax", invert: list = None) -> pd.DataFrame:
    invert = invert or ["forward_pe", "pb"]   # lower = better for these
    scored = df.copy()
    total_weight = sum(weights[m] for m in metrics)
    scored["score"] = 0.0
    for m in metrics:
        norm = normalize(scored[m].fillna(scored[m].median()), method)
        if m in invert:
            norm = 1 - norm
        scored["score"] += norm * (weights[m] / total_weight)
    return scored.sort_values("score", ascending=False).reset_index(drop=True)