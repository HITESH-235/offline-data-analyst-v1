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
        if metadata.get('analysis_deleted'):continue
        result = metadata.get("results")
        artifacts = metadata.get("artifacts", [])
        if not artifacts and (not isinstance(result, dict) or not result.get("columns") or not isinstance(result.get("data"), list)):
            continue
        calculation = metadata.get("calculation") or {}
        step = next((
            step for step in reversed(calculation.get("steps", []))
            if step.get("status") == "succeeded" and (artifacts or step.get("tool") != "run_code" or (isinstance(result, dict) and result.get('analysis_kind') == 'correlation'))
        ), {})
        # Legacy statistics responses included the input rows, not a result table.
        if not artifacts and step.get("tool") == "statistics" and step.get("parameters", {}).get("return_table") is not True:
            continue
        snapshots.append({
            "id": message.id,
            "content": message.content,
            "question": metadata.get("question"),
            "saved_at": message.created_at.isoformat() + "Z" if message.created_at else None,
            "result": result,
            "artifacts": artifacts,
            "tables": list(dict.fromkeys(source for table in (metadata.get("analysis_package") or {}).get("tables",[]) for source in table.get("source",{}).get("tables",[]))) or step.get("tables", []),
            "calculation": calculation,
            'analysisPackage':metadata.get('analysis_package'),
            'analysisStatus':metadata.get('analysis_status'),
        })
    return snapshots


@router.delete("/{project_id}/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_analysis(project_id: str, analysis_id: str, db: Session = Depends(get_db)):
    from app.services.chart_artifacts import stage_artifact_deletion
    message = db.query(DBChatHistory.id, func.json_extract(DBChatHistory.metadata_json, '$.artifacts').label('artifacts')).filter(
        DBChatHistory.project_id == project_id, DBChatHistory.id == analysis_id,
        DBChatHistory.role == "assistant", func.json_valid(DBChatHistory.metadata_json) == 1,
    ).first()
    if not message:
        raise HTTPException(status_code=404, detail="Saved analysis not found")

    def artifact_ids(raw):
        try:
            values = json.loads(raw or '[]')
        except (ValueError, TypeError):
            return set()
        return {item['id'] for item in values if isinstance(item, dict) and isinstance(item.get('id'), str)} if isinstance(values, list) else set()

    owned = artifact_ids(message.artifacts)
    # Keep artifacts still referenced by another saved analysis in this project.
    others = db.query(func.json_extract(DBChatHistory.metadata_json, '$.artifacts')).filter(
        DBChatHistory.project_id == project_id, DBChatHistory.id != analysis_id,
        func.json_valid(DBChatHistory.metadata_json) == 1,
    ).all()
    referenced = set().union(*(artifact_ids(row[0]) for row in others)) if others else set()
    try:
        with stage_artifact_deletion(project_id, owned - referenced):
            db.query(DBChatHistory).filter(DBChatHistory.id == analysis_id, DBChatHistory.project_id == project_id).update({
                DBChatHistory.metadata_json: func.json_set(
                    func.json_remove(DBChatHistory.metadata_json, '$.results', '$.chart_base64', '$.artifacts','$.analysis_package'),
                    '$.analysis_deleted', True)
            }, synchronize_session=False)
            db.commit()
    except OSError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not remove the analysis chart files. Please try again.")
    except Exception:
        db.rollback()
        raise
    return None


@router.get("/{project_id}/messages")
def list_project_messages(project_id: str, before: str = None, db: Session = Depends(get_db)):
    from sqlalchemy import and_, or_
    safe_metadata = case((func.length(DBChatHistory.metadata_json) <= 8 * 1024 * 1024,
                          DBChatHistory.metadata_json), else_=None).label('metadata')
    query = db.query(DBChatHistory.id, DBChatHistory.role, DBChatHistory.content,
                     DBChatHistory.created_at, safe_metadata).filter(DBChatHistory.project_id == project_id)
    if before:
        cursor = db.query(DBChatHistory.id, DBChatHistory.created_at).filter(DBChatHistory.id == before, DBChatHistory.project_id == project_id).first()
        if not cursor:
            raise HTTPException(status_code=404, detail="Chat history cursor not found")
        query = query.filter(or_(DBChatHistory.created_at < cursor.created_at,
                                and_(DBChatHistory.created_at == cursor.created_at, DBChatHistory.id < cursor.id)))
    rows = query.order_by(DBChatHistory.created_at.desc(), DBChatHistory.id.desc()).limit(51).all()
    page = rows[:50]
    return {"messages": [{"id": row.id, "role": row.role, "content": row.content,
                          "created_at": row.created_at.isoformat() + 'Z', "metadata_json": row.metadata}
                         for row in reversed(page)],
            "has_more": len(rows) > 50, "before": page[-1].id if page else None}


@router.get("/{project_id}/artifacts/{artifact_id}/{role}")
def read_chart_artifact(project_id: str, artifact_id: str, role: str, db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    from app.services.chart_artifacts import artifact_file
    if role not in ('figure', 'image', 'download') or not ProjectService.get_project(db, project_id):
        raise HTTPException(status_code=404, detail="Chart artifact not found")
    try:
        path, metadata = artifact_file(project_id, artifact_id, role)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Chart artifact not found")
    if role == 'figure':
        if metadata['kind'] != 'plotly':
            raise HTTPException(status_code=404, detail="Figure data unavailable")
        return FileResponse(path, media_type='application/json', headers={'X-Content-Type-Options': 'nosniff'})
    if role == 'image' and metadata['kind'] == 'png':
        return FileResponse(path, media_type='image/png', headers={'X-Content-Type-Options': 'nosniff'})
    if role == 'image':
        raise HTTPException(status_code=404, detail="Image unavailable")
    return FileResponse(path, media_type='application/octet-stream', filename=path.name,
                        headers={'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "sandbox", 'Access-Control-Expose-Headers': 'Content-Disposition'})
