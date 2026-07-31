import pandas as pd
from typing import List, Dict, Any, Optional

def aggregate_data(
    df: pd.DataFrame, 
    group_by: Optional[List[str]] = None, 
    aggregations: Optional[Dict[str, str]] = None,
    sort_by: Optional[str] = None,
    ascending: bool = True
) -> pd.DataFrame:
    """
    Groups and aggregates a Pandas DataFrame.
    Example aggregations: {"Sales": "sum", "Age": "mean"}
    """
    if df.empty:
        return df
        
    result_df = df.copy()
    
    # Dynamically normalize list-based aggregations commonly outputted by the LLM
    if isinstance(aggregations, list):
        normalized_aggs = {}
        for item in aggregations:
            if isinstance(item, dict):
                col = item.get("column") or item.get("col")
                func = item.get("func") or item.get("aggregation") or item.get("op") or "mean"
                if col:
                    # Clean up function name strings (e.g., average -> mean)
                    if func in ["average", "avg"]:
                        func = "mean"
                    normalized_aggs[col] = func
        aggregations = normalized_aggs
    elif not isinstance(aggregations, dict):
        aggregations = None

    # Normalize group_by if it contains dictionary items
    if isinstance(group_by, list):
        normalized_groups = []
        for g in group_by:
            if isinstance(g, dict):
                col = g.get("column") or g.get("name") or g.get("field")
                if col:
                    normalized_groups.append(col)
            elif isinstance(g, str):
                normalized_groups.append(g)
        group_by = normalized_groups
    elif isinstance(group_by, str):
        group_by = [group_by]

    # Normalize sort_by if it is a dictionary
    if isinstance(sort_by, dict):
        sort_by = sort_by.get("column") or sort_by.get("name") or sort_by.get("field")
        
    # If no grouping columns, apply standard column aggregations
    if not group_by:
        if aggregations:
            agg_funcs = {}
            for col, agg_func in aggregations.items():
                if col in result_df.columns:
                    agg_funcs[col] = agg_func
            if agg_funcs:
                # Convert the aggregated series back to a single row DataFrame
                aggregated = result_df.agg(agg_funcs)
                result_df = pd.DataFrame([aggregated])
    else:
        # Filter grouping columns that exist in the dataframe
        valid_groups = [g for g in group_by if g in result_df.columns]
        if valid_groups:
            if aggregations:
                agg_funcs = {col: func for col, func in aggregations.items() if col in result_df.columns}
                if agg_funcs:
                    result_df = result_df.groupby(valid_groups, as_index=False).agg(agg_funcs)
                else:
                    result_df = result_df.groupby(valid_groups, as_index=False).size()
            else:
                result_df = result_df.groupby(valid_groups, as_index=False).size()
                
    if sort_by and sort_by in result_df.columns:
        result_df = result_df.sort_values(by=sort_by, ascending=ascending)
        
    return result_df
