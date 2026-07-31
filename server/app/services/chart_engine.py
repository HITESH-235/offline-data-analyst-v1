import os
import uuid
import logging
import pandas as pd
import plotly.express as px
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.dataset import DBDataset
from app.services.project_service import ProjectService
from app.utils.workspace import get_project_dir

logger = logging.getLogger(__name__)

class ChartEngine:
    @staticmethod
    def generate_and_save_chart(
        db: Session,
        project_id: str,
        df: pd.DataFrame,
        chart_type: str,
        x_col: str,
        y_col: Optional[str] = None,
        color_col: Optional[str] = None,
        title: Optional[str] = None
    ) -> str:
        """
        Generates a Plotly chart and saves it as an interactive HTML file.
        Returns the absolute filesystem path to the saved HTML file.
        """
        # Validate Project
        project = ProjectService.get_project(db, project_id)
        if not project:
            raise ValueError("Project not found.")
            
        if df.empty:
            raise ValueError("Cannot plot an empty DataFrame.")
            
        if x_col not in df.columns:
            raise ValueError(f"X column '{x_col}' does not exist in DataFrame.")
            
        if y_col and y_col not in df.columns:
            raise ValueError(f"Y column '{y_col}' does not exist in DataFrame.")
            
        if color_col and color_col not in df.columns:
            raise ValueError(f"Color column '{color_col}' does not exist in DataFrame.")

        # Match chart type
        chart_type = chart_type.lower()
        fig = None
        
        try:
            if chart_type == "bar":
                fig = px.bar(df, x=x_col, y=y_col, color=color_col, title=title)
            elif chart_type == "line":
                fig = px.line(df, x=x_col, y=y_col, color=color_col, title=title)
            elif chart_type == "scatter":
                fig = px.scatter(df, x=x_col, y=y_col, color=color_col, title=title)
            elif chart_type == "histogram":
                fig = px.histogram(df, x=x_col, y=y_col, color=color_col, title=title)
            elif chart_type == "box":
                fig = px.box(df, x=x_col, y=y_col, color=color_col, title=title)
            elif chart_type == "heatmap":
                # For correlation or pivots
                if y_col:
                    pivot = df.pivot(index=x_col, columns=y_col, values=color_col)
                    fig = px.imshow(pivot, title=title)
                else:
                    numeric_df = df.select_dtypes(include=["number"])
                    if not numeric_df.empty:
                        corr = numeric_df.corr().fillna(0)
                        fig = px.imshow(corr, text_auto=True, title=title or "Correlation Heatmap")
                    else:
                        raise ValueError("Heatmap requires numeric columns for correlation.")
            else:
                raise ValueError(f"Unsupported chart type '{chart_type}'. Supported: bar, line, scatter, histogram, box, heatmap")
        except Exception as e:
            logger.error(f"Plotly generation failed: {e}")
            raise ValueError(f"Plotly generation failed: {e}")
            
        # Customize styling for dark mode
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(30, 30, 30, 0.5)",
            plot_bgcolor="rgba(30, 30, 30, 0.5)",
            font=dict(family="Inter, sans-serif", size=12)
        )
        
        # Save HTML file inside project workspace
        project_dir = get_project_dir(project.name)
        charts_dir = os.path.join(project_dir, "charts")
        os.makedirs(charts_dir, exist_ok=True)
        
        filename = f"chart_{chart_type}_{uuid.uuid4().hex[:8]}.html"
        file_path = os.path.join(charts_dir, filename)
        
        try:
            # include_plotlyjs=True bundles Plotly.js inside the HTML for offline usage
            fig.write_html(file_path, include_plotlyjs=True, full_html=True)
            logger.info(f"Interactive HTML chart saved at: {file_path}")
        except Exception as e:
            logger.error(f"Failed to write chart file: {e}")
            raise IOError(f"Failed to write chart HTML file: {e}")
            
        return file_path
