import pandas as pd
from typing import List, Dict, Any

def filter_data(df: pd.DataFrame, filters: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Applies logic filters to the DataFrame.
    Filters format: [{"column": "Age", "operator": ">", "value": 30}]
    Operators supported: "==", "!=", ">", "<", ">=", "<=", "contains", "in"
    """
    # Normalize filters if passed as a dictionary wrap
    if isinstance(filters, dict):
        filters = filters.get("filters") or filters.get("conditions") or []
        
    if df.empty or not filters or not isinstance(filters, list):
        return df
        
    result_df = df.copy()
    
    for f in filters:
        col = f.get("column")
        op = f.get("operator")
        val = f.get("value")
        
        if col not in result_df.columns:
            continue
            
        try:
            if op == "==":
                result_df = result_df[result_df[col] == val]
            elif op == "!=":
                result_df = result_df[result_df[col] != val]
            elif op == ">":
                result_df = result_df[result_df[col] > float(val)]
            elif op == "<":
                result_df = result_df[result_df[col] < float(val)]
            elif op == ">=":
                result_df = result_df[result_df[col] >= float(val)]
            elif op == "<=":
                result_df = result_df[result_df[col] <= float(val)]
            elif op == "contains":
                result_df = result_df[result_df[col].astype(str).str.contains(str(val), case=False, na=False)]
            elif op == "in":
                if isinstance(val, list):
                    result_df = result_df[result_df[col].isin(val)]
        except Exception as e:
            # Catch type mismatch/parsing errors and skip that filter
            continue
            
    return result_df
