"""
AnalysisEngine: Executes structured analysis operations against a dataset.

The agent sends tool parameters in a known format (defined in prompts.py),
so we trust the structure and just pass it through with minimal cleanup.
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

        # 1. Apply Filtering
        filters = plan.get("filters")
        if filters:
            df = ana.filter_data(df, filters)

        # 2. Compute Statistics
        stats = plan.get("statistics")
        if stats:
            cols = stats.get("columns", []) if isinstance(stats, dict) else []
            results["statistics"] = ana.compute_statistics(df, cols)

        # 3. Compute Correlation
        if plan.get("correlation"):
            method = plan.get("correlation_method", "pearson")
            results["correlation"] = ana.compute_correlation(df, method=method)

        # 4. Apply Aggregation
        aggregation = plan.get("aggregation")
        if validate_tool_arguments and "aggregation" in plan:
            cls.validate_aggregation(aggregation, df.columns)
        if aggregation:
            df = ana.aggregate_data(
                df,
                group_by=aggregation.get("group_by"),
                aggregations=aggregation.get("aggregations"),
                sort_by=aggregation.get("sort_by"),
                ascending=aggregation.get("ascending", True)
            )

        # 5. Visualization blueprint
        viz = plan.get("visualization")
        if viz and viz.get("chart_type") and viz.get("x"):
            results["visualization_blueprint"] = ana.prepare_chart_blueprint(
                chart_type=viz["chart_type"],
                x_col=viz["x"],
                y_col=viz.get("y"),
                color_col=viz.get("color"),
                title=viz.get("title"),
            )

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
