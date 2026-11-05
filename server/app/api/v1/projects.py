import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session
from app.storage.sqlite.session import get_db
from app.models.chat import DBChatHistory
from app.models.project import Project, ProjectCreate, ProjectRename
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])

@router.post("/", response_model=Project, status_code=status.HTTP_201_CREATED)
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    db_project = ProjectService.get_project_by_name(db, name=project.name)
    if db_project:
         raise HTTPException(status_code=400, detail="Project with this name already exists")
    return ProjectService.create_project(db, name=project.name)

@router.get("/", response_model=List[Project])
def list_projects(db: Session = Depends(get_db)):
    return ProjectService.list_projects(db)

@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str, db: Session = Depends(get_db)):
    db_project = ProjectService.get_project(db, project_id=project_id)
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")
    return db_project

@router.put("/{project_id}", response_model=Project)
def rename_project(project_id: str, update_data: ProjectRename, db: Session = Depends(get_db)):
    try:
        updated = ProjectService.rename_project(db, project_id=project_id, new_name=update_data.new_name)
        if not updated:
            raise HTTPException(status_code=404, detail="Project not found")
        return updated
    except FileExistsError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, db: Session = Depends(get_db)):
    success = ProjectService.delete_project(db, project_id=project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return None


@router.get("/{project_id}/analyses")
def list_saved_analyses(project_id: str, db: Session = Depends(get_db)):
    # Opening a saved result is local, so bound each snapshot loaded by the list.
    max_snapshot_bytes = 8 * 1024 * 1024
    metadata = case(
        (func.length(DBChatHistory.metadata_json) <= max_snapshot_bytes, DBChatHistory.metadata_json),
        else_=None,
    ).label("metadata")
    messages = db.query(DBChatHistory.id, DBChatHistory.content, DBChatHistory.created_at, metadata).filter(
        DBChatHistory.project_id == project_id,
        DBChatHistory.role == "assistant",
        DBChatHistory.metadata_json.isnot(None),
    ).order_by(DBChatHistory.created_at.desc()).all()
    snapshots = []
    for message in messages:
        if message.metadata is None:
            snapshots.append({"id": message.id, "unavailable": "Snapshot exceeds the 8 MiB workspace limit."})
            continue
        try:
            metadata = json.loads(message.metadata)
        except (TypeError, ValueError):
            continue
        if not isinstance(metadata, dict):
            continue
        result = metadata.get("results")
        if not isinstance(result, dict) or not result.get("columns") or not isinstance(result.get("data"), list):
            continue
        calculation = metadata.get("calculation") or {}
        step = next((
            step for step in reversed(calculation.get("steps", []))
            if step.get("status") == "succeeded" and step.get("tool") != "run_code"
        ), {})
        # Legacy statistics responses included the input rows, not a result table.
        if step.get("tool") == "statistics" and step.get("parameters", {}).get("return_table") is not True:
            continue
        snapshots.append({
            "id": message.id,
            "content": message.content,
            "question": metadata.get("question"),
            "saved_at": message.created_at.isoformat() + "Z" if message.created_at else None,
            "result": result,
            "tables": step.get("tables", []),
            "calculation": calculation,
        })
    return snapshots
