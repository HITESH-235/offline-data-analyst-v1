import numpy as np
import pandas as pd
from typing import Dict, Any, List

def compute_statistics(df: pd.DataFrame, columns: List[str]) -> Dict[str, Any]:
    """
    Computes statistical profiles including mean, standard deviation, quartiles, and outliers.
    """
    stats = {}
    if df.empty:
        return stats
        
    for col in columns:
        if col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]):
            continue
            
        series = df[col].dropna()
        if series.empty:
            continue
            
        # Standard statistics
        mean_val = float(series.mean())
        std_val = float(series.std())
        min_val = float(series.min())
        max_val = float(series.max())
        median_val = float(series.median())
        q25 = float(series.quantile(0.25))
        q75 = float(series.quantile(0.75))
        
        # Outlier calculation via IQR
        iqr = q75 - q25
        lower_bound = q25 - (1.5 * iqr)
        upper_bound = q75 + (1.5 * iqr)
        outliers = series[(series < lower_bound) | (series > upper_bound)]
        
        stats[col] = {
            "mean": mean_val,
            "std": std_val,
            "min": min_val,
            "max": max_val,
            "median": median_val,
            "q25": q25,
            "q75": q75,
            "iqr": iqr,
            "outliers_count": len(outliers),
            "outliers_percentage": float(len(outliers) / len(series) * 100) if not series.empty else 0.0,
            "outlier_values": [float(x) for x in outliers.tolist()]
        }
        
    return stats
