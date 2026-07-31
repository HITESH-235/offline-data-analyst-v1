import os
import uuid
import shutil
import json
import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.project import DBProject
from app.utils.workspace import (
    initialize_project_dirs,
    get_project_dir,
    get_projects_path
)

logger = logging.getLogger(__name__)

class ProjectService:
    @staticmethod
    def create_project(db: Session, name: str) -> DBProject:
        """
        Creates a new project in the SQLite DB and initializes its physical directories on disk.
        """
        # Ensure project directories are created
        initialize_project_dirs(name)
        
        # Check if project already exists in database
        db_project = db.query(DBProject).filter(DBProject.name == name).first()
        if db_project:
            return db_project
            
        # Create database entry
        project_id = str(uuid.uuid4())
        new_project = DBProject(id=project_id, name=name)
        db.add(new_project)
        db.commit()
        db.refresh(new_project)
        
        # Save structural metadata file inside workspace/projects/<name>/metadata/metadata.json
        ProjectService.save_metadata(name, {
            "id": project_id,
            "name": name,
            "created_at": new_project.created_at.isoformat()
        })
        
        logger.info(f"Project '{name}' registered in database and disk workspace.")
        return new_project

    @staticmethod
    def get_project(db: Session, project_id: str) -> Optional[DBProject]:
        """
        Retrieves a project by its unique ID.
        """
        return db.query(DBProject).filter(DBProject.id == project_id).first()

    @staticmethod
    def get_project_by_name(db: Session, name: str) -> Optional[DBProject]:
        """
        Retrieves a project by name.
        """
        return db.query(DBProject).filter(DBProject.name == name).first()

    @staticmethod
    def list_projects(db: Session) -> List[DBProject]:
        """
        Retrieves a list of all active projects.
        """
        return db.query(DBProject).all()

    @staticmethod
    def rename_project(db: Session, project_id: str, new_name: str) -> Optional[DBProject]:
        """
        Renames a project. Also updates the project's folder on disk.
        """
        project = db.query(DBProject).filter(DBProject.id == project_id).first()
        if not project:
            return None
            
        old_name = project.name
        old_dir = get_project_dir(old_name)
        new_dir = get_project_dir(new_name)
        
        # Perform rename on disk first
        if os.path.exists(old_dir):
            if os.path.exists(new_dir):
                raise FileExistsError(f"Destination project folder '{new_name}' already exists.")
            os.rename(old_dir, new_dir)
            
        # Update database entry
        project.name = new_name
        db.commit()
        db.refresh(project)
        
        # Update metadata.json file
        meta = ProjectService.load_metadata(new_name) or {}
        meta["name"] = new_name
        ProjectService.save_metadata(new_name, meta)
        
        logger.info(f"Project '{old_name}' renamed to '{new_name}' successfully.")
        return project

    @staticmethod
    def delete_project(db: Session, project_id: str) -> bool:
        """
        Deletes a project from the SQLite DB and permanently removes its directory from disk.
        """
        project = db.query(DBProject).filter(DBProject.id == project_id).first()
        if not project:
            return False
            
        project_name = project.name
        project_dir = get_project_dir(project_name)
        
        # Remove from database
        db.delete(project)
        db.commit()
        
        # Remove physical directory
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
            
        logger.info(f"Project '{project_name}' and its workspace have been deleted.")
        return True

    @staticmethod
    def save_metadata(project_name: str, metadata: dict) -> None:
        """
        Saves custom metadata to metadata/metadata.json inside the project workspace.
        """
        project_dir = get_project_dir(project_name)
        meta_file = os.path.join(project_dir, "metadata", "metadata.json")
        os.makedirs(os.path.dirname(meta_file), exist_ok=True)
        with open(meta_file, "w") as f:
            json.dump(metadata, f, indent=4)

    @staticmethod
    def load_metadata(project_name: str) -> Optional[dict]:
        """
        Loads custom metadata from metadata/metadata.json inside the project workspace.
        """
        project_dir = get_project_dir(project_name)
        meta_file = os.path.join(project_dir, "metadata", "metadata.json")
        if not os.path.exists(meta_file):
            return None
        with open(meta_file, "r") as f:
            return json.load(f)
