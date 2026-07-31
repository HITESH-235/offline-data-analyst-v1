from typing import Dict, Any, Optional

def prepare_chart_blueprint(
    chart_type: str, 
    x_col: str, 
    y_col: Optional[str] = None, 
    title: Optional[str] = None,
    color_col: Optional[str] = None
) -> Dict[str, Any]:
    """
    Prepares a clean Plotly JSON config template.
    Supported chart types: bar, line, scatter, histogram, box
    """
    blueprint = {
        "chart_type": chart_type,
        "x": x_col,
        "y": y_col,
        "color": color_col,
        "layout": {
            "title": title or f"{chart_type.capitalize()} Chart: {x_col}" + (f" vs {y_col}" if y_col else ""),
            "xaxis": {"title": x_col},
            "yaxis": {"title": y_col or "Value"},
            "template": "plotly_dark",
            "responsive": True
        }
    }
    return blueprint
