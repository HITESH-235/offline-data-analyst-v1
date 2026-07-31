from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.storage.sqlite.session import get_db
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
