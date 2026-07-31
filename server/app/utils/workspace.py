import os
import shutil
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

# List of standard subdirectories required in a production project workspace
PROJECT_SUBDIRS = ["data", "chat", "charts", "reports", "metadata", "analysis"]

def initialize_workspace() -> str:
    """
    Initializes the root workspace directory and projects subdirectory.
    Returns the absolute path to the workspace directory.
    """
    workspace_path = os.path.abspath(settings.WORKSPACE_DIR)
    projects_path = os.path.join(workspace_path, "projects")
    
    try:
        os.makedirs(projects_path, exist_ok=True)
        logger.info(f"Workspace initialized successfully at: {workspace_path}")
    except Exception as e:
        logger.error(f"Failed to initialize workspace at {workspace_path}: {e}")
        raise IOError(f"Could not create workspace folders: {e}")
        
    return workspace_path

def get_workspace_path() -> str:
    """
    Returns the absolute path of the workspace.
    """
    return os.path.abspath(settings.WORKSPACE_DIR)

def get_projects_path() -> str:
    """
    Returns the absolute path of the projects directory.
    """
    return os.path.join(get_workspace_path(), "projects")

def get_project_dir(project_name: str) -> str:
    """
    Returns the path to a specific project folder inside the workspace.
    """
    # Safe naming mapping: replace spaces/unusual characters or use direct slug
    safe_name = "".join([c if c.isalnum() or c in "-_" else "_" for c in project_name])
    return os.path.join(get_projects_path(), safe_name)

def verify_project_structure(project_name: str) -> bool:
    """
    Verifies that all required subdirectories exist for a given project.
    Returns True if valid, False otherwise.
    """
    project_dir = get_project_dir(project_name)
    if not os.path.exists(project_dir):
        return False
        
    for subdir in PROJECT_SUBDIRS:
        subdir_path = os.path.join(project_dir, subdir)
        if not os.path.isdir(subdir_path):
            logger.warning(f"Missing subdirectory '{subdir}' in project path: {project_dir}")
            return False
            
    return True

def initialize_project_dirs(project_name: str) -> str:
    """
    Creates a project folder and all its required subdirectories.
    Returns the absolute path of the project.
    """
    project_dir = get_project_dir(project_name)
    os.makedirs(project_dir, exist_ok=True)
    
    for subdir in PROJECT_SUBDIRS:
        os.makedirs(os.path.join(project_dir, subdir), exist_ok=True)
        
    logger.info(f"Initialized folder structure for project '{project_name}' at: {project_dir}")
    return project_dir
