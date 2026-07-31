import os
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.storage.sqlite.session import get_db
from app.analysis_engine import AnalysisEngine

router = APIRouter(prefix="/analysis", tags=["Analysis"])

@router.post("/execute-plan", status_code=status.HTTP_200_OK)
def execute_analysis_plan(
    plan_request: Dict[str, Any], 
    db: Session = Depends(get_db)
):
    dataset_id = plan_request.get("dataset_id")
    plan = plan_request.get("plan")
    
    if not dataset_id or not plan:
        raise HTTPException(status_code=400, detail="Missing dataset_id or plan in request.")
        
    try:
        results = AnalysisEngine.execute_plan(db, dataset_id=dataset_id, plan=plan)
        return results
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis calculation error: {e}")

@router.post("/charts/generate", status_code=status.HTTP_201_CREATED)
def generate_chart(
    chart_request: Dict[str, Any],
    db: Session = Depends(get_db)
):
    from app.services.dataset_manager import DatasetManager
    from app.services.chart_engine import ChartEngine
    
    project_id = chart_request.get("project_id")
    dataset_id = chart_request.get("dataset_id")
    chart_type = chart_request.get("chart_type")
    x_col = chart_request.get("x")
    y_col = chart_request.get("y")
    color_col = chart_request.get("color")
    title = chart_request.get("title")
    
    if not project_id or not dataset_id or not chart_type or not x_col:
        raise HTTPException(status_code=400, detail="Missing required parameters: project_id, dataset_id, chart_type, and x are required.")
        
    db_dataset = DatasetManager.get_dataset(db, dataset_id=dataset_id)
    if not db_dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
        
    try:
        df = DatasetManager.load_dataset_dataframe(db_dataset)
        file_path = ChartEngine.generate_and_save_chart(
            db=db,
            project_id=project_id,
            df=df,
            chart_type=chart_type,
            x_col=x_col,
            y_col=y_col,
            color_col=color_col,
            title=title
        )
        return {"status": "success", "chart_path": file_path, "filename": os.path.basename(file_path)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate chart: {e}")

@router.post("/reports/generate", status_code=status.HTTP_201_CREATED)
def generate_report(
    report_request: Dict[str, Any],
    db: Session = Depends(get_db)
):
    from app.services.report_service import ReportService
    
    project_id = report_request.get("project_id")
    title = report_request.get("title")
    content = report_request.get("content")
    
    if not project_id or not title or not content:
        raise HTTPException(status_code=400, detail="Missing required parameters: project_id, title, and content are required.")
        
    try:
        report_data = ReportService.generate_report(
            db=db,
            project_id=project_id,
            title=title,
            content_markdown=content
        )
        return {
            "status": "success",
            "markdown_filename": report_data["markdown_filename"],
            "pdf_filename": report_data["pdf_filename"]
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {e}")
