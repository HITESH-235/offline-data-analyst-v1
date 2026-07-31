import pandas as pd
from typing import Dict, Any, List

def compute_correlation(df: pd.DataFrame, method: str = "pearson") -> Dict[str, Any]:
    """
    Computes numerical correlation matrices (Pearson/Spearman) on numeric columns.
    """
    if df.empty:
        return {}
        
    numeric_df = df.select_dtypes(include=["number"])
    if numeric_df.empty or len(numeric_df.columns) < 2:
        return {
            "columns": list(numeric_df.columns),
            "matrix": []
        }
        
    # Calculate matrix
    corr_matrix = numeric_df.corr(method=method)
    
    # Replace NaN values with 0 so they can be JSON serialized cleanly
    corr_matrix = corr_matrix.fillna(0)
    
    return {
        "columns": list(corr_matrix.columns),
        "matrix": corr_matrix.values.tolist()
    }
