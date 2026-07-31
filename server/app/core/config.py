import os
import logging # used for printing logs
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    APP_NAME: str = os.getenv("APP_NAME", "Offline AI Data Analyst")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"
    HOST: str = os.getenv("HOST", "0.0.0.0")  # Bind to 0.0.0.0 for Docker compatibility
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Workspace storage paths (mount point in Docker)
    WORKSPACE_DIR: str = os.getenv(
        "WORKSPACE_DIR", 
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../workspace"))
    )
    
    # Pre-loaded fixed datasets catalog directory
    DATASETS_DIR: str = os.getenv(
        "DATASETS_DIR",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../datasets"))
    )
    
    # Database configurations
    METADATA_DB_URL: str = os.getenv("METADATA_DB_URL", "sqlite:///workspace/metadata.db")
    
    # Ollama configurations
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:latest")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# Configure logging format and default level
def setup_logging():
    logging.basicConfig(
        level=logging.INFO if not settings.DEBUG else logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler()
        ]
    )
