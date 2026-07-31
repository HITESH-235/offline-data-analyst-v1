from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from app.storage.sqlite.session import Base

# --- SQLAlchemy Table Model ---
class DBDataset(Base):
    __tablename__ = "datasets"
    
    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    filepath = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    row_count = Column(Integer, nullable=False)
    parent_db = Column(String, nullable=True)
    table_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# --- Pydantic Data Schemas ---
class DatasetBase(BaseModel): # base model for all dataset
    filename: str
    file_size_bytes: int
    row_count: int
    parent_db: Optional[str] = None
    table_name: Optional[str] = None

class Dataset(DatasetBase): # output model rep complete dataset stored in db
    id: str
    project_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    model_config = ConfigDict(from_attributes=True) # turns sqla -> pydantic objects

class DatasetPreview(BaseModel): 
    columns: list
    data: list
    row_count: int
