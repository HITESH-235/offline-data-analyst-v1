import os
import uuid
import shutil
import json
import logging
from pathlib import Path
from sqlalchemy.orm import Session
from app.models.project import DBProject
from app.models.chat import DBChatHistory
from app.models.dataset import DBDataset
from app.utils.workspace import initialize_project_dirs, get_project_dir

logger = logging.getLogger(__name__)


class ProjectService:
    @staticmethod
    def create_project(db: Session, name: str) -> DBProject:
        existing = ProjectService.get_project_by_name(db, name)
        if existing:
            return existing
        project = DBProject(id=str(uuid.uuid4()), name=name)
        db.add(project)
        db.commit()
        db.refresh(project)
        initialize_project_dirs(project.id)
        ProjectService.save_metadata(project.id, {"id": project.id, "name": name, "created_at": project.created_at.isoformat()})
        return project

    @staticmethod
    def get_project(db: Session, project_id: str):
        return db.query(DBProject).filter(DBProject.id == project_id).first()

    @staticmethod
    def get_project_by_name(db: Session, name: str):
        return db.query(DBProject).filter(DBProject.name == name).first()

    @staticmethod
    def list_projects(db: Session):
        return db.query(DBProject).all()

    @staticmethod
    def rename_project(db: Session, project_id: str, new_name: str):
        project = ProjectService.get_project(db, project_id)
        if not project:
            return None
        other = ProjectService.get_project_by_name(db, new_name)
        if other and other.id != project_id:
            raise FileExistsError(f"Project '{new_name}' already exists.")
        project.name = new_name
        db.commit()
        db.refresh(project)
        metadata = ProjectService.load_metadata(project.id) or {"id": project.id}
        metadata["name"] = new_name
        ProjectService.save_metadata(project.id, metadata)
        return project

    @staticmethod
    def delete_project(db: Session, project_id: str) -> bool:
        project = ProjectService.get_project(db, project_id)
        if not project:
            return False
        directory = get_project_dir(project.id)
        # Explicitly remove dependent records even on SQLite connections without FK enforcement.
        db.query(DBChatHistory).filter(DBChatHistory.project_id == project.id).delete(synchronize_session=False)
        db.query(DBDataset).filter(DBDataset.project_id == project.id).delete(synchronize_session=False)
        db.delete(project)
        db.commit()
        if os.path.exists(directory):
            shutil.rmtree(directory)
        return True

    @staticmethod
    def save_metadata(project_id: str, metadata: dict):
        path = Path(get_project_dir(project_id)) / 'metadata' / 'metadata.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata, indent=4))

    @staticmethod
    def load_metadata(project_id: str):
        path = Path(get_project_dir(project_id)) / 'metadata' / 'metadata.json'
        return json.loads(path.read_text()) if path.exists() else None
