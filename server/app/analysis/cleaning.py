import pandas as pd
from typing import List, Dict, Any, Optional

def clean_data(
    df: pd.DataFrame, 
    fill_nulls: Optional[Dict[str, Any]] = None,
    drop_duplicates: bool = False,
    drop_duplicates_cols: Optional[List[str]] = None,
    cast_types: Optional[Dict[str, str]] = None
) -> pd.DataFrame:
    """
    Cleans DataFrame (filling null values, removing duplicates, type conversion).
    """
    if df.empty:
        return df
        
    result_df = df.copy()
    
    # Fill Nulls
    if fill_nulls:
        for col, val in fill_nulls.items():
            if col in result_df.columns:
                result_df[col] = result_df[col].fillna(val)
                
    # Drop Duplicates
    if drop_duplicates:
        valid_cols = None
        if drop_duplicates_cols:
            valid_cols = [c for c in drop_duplicates_cols if c in result_df.columns]
        result_df = result_df.drop_duplicates(subset=valid_cols)
        
    # Cast Types
    if cast_types:
        for col, target_type in cast_types.items():
            if col in result_df.columns:
                try:
                    if target_type == "int":
                        result_df[col] = pd.to_numeric(result_df[col], errors="coerce").fillna(0).astype(int)
                    elif target_type == "float":
                        result_df[col] = pd.to_numeric(result_df[col], errors="coerce")
                    elif target_type == "str":
                        result_df[col] = result_df[col].astype(str)
                    elif target_type == "datetime":
                        result_df[col] = pd.to_datetime(result_df[col], errors="coerce")
                except Exception:
                    continue
                    
    return result_df
