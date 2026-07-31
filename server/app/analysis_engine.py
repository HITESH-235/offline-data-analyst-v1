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

    @classmethod
    def execute_plan(cls, db, dataset_id: str, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Loads the dataset and runs the requested operations in order:
        filters → statistics/correlation → aggregation → visualization blueprint
        """
        # Load dataset
        db_dataset = DatasetManager.get_dataset(db, dataset_id)
        if not db_dataset:
            raise ValueError("Dataset not found.")

        df = DatasetManager.load_dataset_dataframe(db_dataset)

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

        # Pack output
        results["data"] = df.fillna("").to_dict(orient="records")
        results["columns"] = list(df.columns)
        results["row_count"] = len(df)

        return results
