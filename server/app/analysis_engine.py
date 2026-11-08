"""
AnalysisEngine: Executes structured analysis operations against a dataset.

The agent sends tool parameters in a known format (defined in prompts.py),
and arguments must be validated before any calculation is reported as successful.
"""

import pandas as pd
import logging
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.services.dataset_manager import DatasetManager
import app.analysis as ana

logger = logging.getLogger(__name__)


class AnalysisEngine:
    @classmethod
    def normalize_plan(cls, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Light cleanup of plan parameters.
        The agent prompt defines exact schemas, so we only handle
        a few common LLM quirks (e.g., "avg" instead of "mean").
        """
        if not isinstance(plan, dict):
            return {}

        # Fix common aggregation function aliases
        agg = plan.get("aggregation")
        if isinstance(agg, dict):
            aggs = agg.get("aggregations", {})
            if isinstance(aggs, dict):
                for col, func in aggs.items():
                    if func in ("average", "avg"):
                        aggs[col] = "mean"

            # Ensure group_by is always a list
            group_by = agg.get("group_by")
            if isinstance(group_by, str):
                agg["group_by"] = [group_by]

        return plan

    @staticmethod
    def validate_aggregation(aggregation, columns):
        example = 'Expected exact dataframe names, e.g. {"group_by":["ProductName"],"aggregations":{"Quantity":"sum"},"sort_by":"Quantity","ascending":false}.'
        if not isinstance(aggregation, dict):
            raise ValueError(f"Aggregation parameters must be an object. {example}")

        groups = aggregation.get("group_by", [])
        measures = aggregation.get("aggregations", {})
        if not isinstance(groups, list) or not isinstance(measures, dict):
            raise ValueError(f"group_by must be a list and aggregations must be a column-to-operation object. {example}")
        if not groups and not measures:
            raise ValueError(f"Specify grouping columns or aggregate measures. {example}")

        for column in [*groups, *measures]:
            if not isinstance(column, str) or column not in columns:
                raise ValueError(f"Unknown aggregation column {column!r}. Available columns: {', '.join(map(str, columns))}. {example}")

        operations = ("mean", "sum", "count", "min", "max")
        for column, operation in measures.items():
            if operation not in operations:
                raise ValueError(f"Unsupported operation {operation!r} for {column!r}. Supported operations: {', '.join(operations)}. {example}")

        sort_by = aggregation.get("sort_by")
        output_columns = [*groups, *measures] if measures else [*groups, "size"]
        if not isinstance(aggregation.get('output_names',{}),dict) or not isinstance(aggregation.get('transforms',[]),list):
            raise ValueError('output_names must be an object; transforms must be a list.')
        output_columns += list(aggregation.get('output_names',{}).values())
        output_columns += [t.get('as') for t in aggregation.get('transforms',[]) if isinstance(t,dict)]
        output_columns += [t.get('name') for t in aggregation.get('derived_measures',[]) if isinstance(t,dict)]
        if any(op=='count' for op in measures.values()):
            from app.analysis.result_operations import human
            import re
            output_columns += [human(re.sub(r'[_ .]?id$','',c,flags=re.I))+' Count' for c,op in measures.items() if op=='count']
            if len(measures)==1:output_columns.append('count')
        if sort_by is not None and sort_by not in output_columns:
            raise ValueError(f"Unknown sort column {sort_by!r}. Result columns: {', '.join(output_columns)}. {example}")
        if "ascending" in aggregation and not isinstance(aggregation["ascending"], bool):
            raise ValueError(f"ascending must be a boolean. {example}")

    @classmethod
    def execute_plan(cls, db, dataset_id: str, plan: Dict[str, Any], *, dataframe=None, validate_tool_arguments=False) -> Dict[str, Any]:
        """
        Loads the dataset and runs the requested operations in order:
        filters → statistics/correlation → aggregation → visualization blueprint
        """
        if dataframe is None:
            db_dataset = DatasetManager.get_dataset(db, dataset_id)
            if not db_dataset:
                raise ValueError("Dataset not found.")
            dataframe = DatasetManager.load_dataset_dataframe(db_dataset)
        df = dataframe.copy()

        # Light cleanup
        plan = cls.normalize_plan(plan)

        results = {}
        if 'comparison_summary' in plan:
            if set(plan)!={'comparison_summary'}:raise ValueError('comparison_summary must execute as a complete calculation.')
            from app.analysis.comparison_summary import calculate
            return calculate(df,plan['comparison_summary'])

        if "monthly_revenue" in plan:
            from app.analysis.monthly_revenue import calculate_monthly_revenue
            if set(plan) != {"monthly_revenue"}:
                raise ValueError('monthly_revenue cannot be combined with other plan operations.')
            return calculate_monthly_revenue(df,plan['monthly_revenue'])

        # Validation is mandatory even for empty/malformed predicates and empty input.
        filters = plan.get("filters")
        if "filters" in plan:
            df = ana.filter_data(df, filters)
            results["filter_audit"] = {"validated": True, "input_row_count":len(dataframe),
                                       "matched_row_count":len(df), "unchanged":len(df)==len(dataframe),
                                       "predicates":filters}

        # 2. Compute Statistics
        stats = plan.get("statistics")
        if stats:
            cols = stats.get("columns", []) if isinstance(stats, dict) else []
            results["statistics"] = ana.compute_statistics(df, cols)

        # 3. Compute Correlation
        if plan.get("correlation"):
            if plan.get('aggregation') or plan.get('statistics') or plan.get('visualization'):
                raise ValueError('Request correlation as its own calculation; its result is the matrix, not raw rows.')
            method = plan.get("correlation_method", "pearson")
            from app.analysis.correlation import correlation_result
            correlation = ana.compute_correlation(df, method=method, columns=plan.get('correlation_columns'))
            return {**results, **correlation_result(correlation)}

        # 4. Apply Aggregation
        aggregation = plan.get("aggregation")
        if validate_tool_arguments and "aggregation" in plan:
            cls.validate_aggregation(aggregation, df.columns)
        if aggregation:
            from app.analysis.result_operations import apply_aggregation
            return {**results,**apply_aggregation(df,aggregation)}

        # 5. Visualization blueprint
        viz = plan.get("visualization")
        if viz and viz.get("chart_type") and viz.get("x"):
            raise ValueError('Visualization is presentation-only: attach it to an existing calculated output instead of reloading source rows.')

        # Statistics inform the narrative; they must not expose the unchanged
        # input dataframe as a newly calculated table.
        if "statistics" in plan and not aggregation and not filters and not viz:
            if isinstance(stats, dict) and stats.get("return_table") is True:
                metrics = ["mean", "std", "min", "median", "max", "q25", "q75", "outliers_count"]
                summary = pd.DataFrame([
                    {"column": column, **{metric: values.get(metric) for metric in metrics}}
                    for column, values in results["statistics"].items()
                ], columns=["column", *metrics])
                results["columns"] = list(summary.columns)
                results["data"] = summary.astype(object).where(pd.notna(summary), None).to_dict(orient="records")
                results["row_count"] = len(summary)
            return results

        # Pack output
        results["data"] = df.fillna("").to_dict(orient="records")
        results["columns"] = list(df.columns)
        results["row_count"] = len(df)

        return results
