# While chat.py stores the messages and dataset.py stores files, 
# this creates the parent project records that bind them

from datetime import datetime
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, String, DateTime
from app.storage.sqlite.session import Base

# --- SQLite Database Table Model ---
class DBProject(Base):
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# --- Pydantic API Request/Response Schemas ---
class ProjectBase(BaseModel):
    name: str

class ProjectCreate(ProjectBase):
    pass

class ProjectRename(BaseModel):
    new_name: str

class Project(ProjectBase):
    id: str
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
